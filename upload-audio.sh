#!/usr/bin/env bash
# Upload the recordings to the Cloudflare R2 bucket that serves https://audio.bulgariandialectology.org/
# Uses Cloudflare's wrangler tool (needs Node.js). The first run opens a browser to log in to Cloudflare.
#   ./upload-audio.sh [bucket-name]
set -euo pipefail
cd "$(dirname "$0")"
BUCKET=${1:-bdlt-audio}
FILES=$(ls -t backup/*_files.tar.gz 2>/dev/null | head -1 || true)
[ -n "$FILES" ] || { echo "No *_files.tar.gz in backup/"; exit 1; }
mkdir -p build/audio
echo "Extracting audio from $FILES..."
tar xzf "$FILES" -C build/audio --strip-components=2 'files_live/audio'
n=0; total=$(ls build/audio | wc -l | tr -d ' ')
for f in build/audio/*; do
  n=$((n+1)); name=$(basename "$f")
  echo "[$n/$total] $name"
  npx --yes wrangler@4 r2 object put "$BUCKET/$name" --file "$f" --content-type audio/mpeg \
      --cache-control "public, max-age=31536000" --remote >/dev/null
done
echo "Uploaded $total files to R2 bucket $BUCKET."
