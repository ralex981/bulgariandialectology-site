#!/usr/bin/env bash
# Rebuild the static site from the Pantheon backup in ./backup
set -euo pipefail
cd "$(dirname "$0")"
DB=$(ls -t backup/*_database.sql.gz 2>/dev/null | head -1 || true)
FILES=$(ls -t backup/*_files.tar.gz 2>/dev/null | head -1 || true)
[ -n "$DB" ] || { echo "No *_database.sql.gz in backup/"; exit 1; }
[ -n "$FILES" ] || { echo "No *_files.tar.gz in backup/"; exit 1; }

python3 -c "import jinja2, phpserialize" 2>/dev/null || python3 -m pip install --user -q jinja2 phpserialize

mkdir -p build
echo "1/3  Reading database dump: $DB"
python3 -u pipeline/extract.py "$DB" build/raw.sqlite

echo "2/3  Unpacking files (without audio): $FILES"
rm -rf build/files && mkdir -p build/files
tar xzf "$FILES" -C build/files --exclude='files_live/audio/*' --exclude='files_live/styles/*' \
  --exclude='files_live/skipped.log*' 2> build/tar-warnings.log || echo "     (some archive entries skipped; see build/tar-warnings.log)"

echo "3/3  Generating site"
rm -rf site
python3 -u pipeline/build.py build/raw.sqlite build/files/files_live pipeline/headerimg site
python3 pipeline/linkcheck.py site | head -8
echo "Done. Preview with:  python3 pipeline/serve.py site"
