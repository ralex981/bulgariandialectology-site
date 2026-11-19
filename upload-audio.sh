#!/usr/bin/env bash
# Upload the recordings to the Cloudflare R2 bucket that serves https://audio.bulgariandialectology.org/
# Uses Cloudflare's wrangler tool (needs Node.js). The first run opens a browser to log in to Cloudflare.
#   ./upload-audio.sh [bucket-name]
set -euo pipefail
cd "$(dirname "$0")"
BUCKET=${1:-bdlt-audio}
export CLOUDFLARE_ACCOUNT_ID=${CLOUDFLARE_ACCOUNT_ID:-830938cb4157fda5ee4153a02887fffa}   # Ronnie's Cloudflare account
export WRANGLER_SEND_METRICS=false
W="npx --yes wrangler@4"

if ! $W whoami 2>/dev/null | grep -q "$CLOUDFLARE_ACCOUNT_ID"; then
  echo "Logging in to Cloudflare (a browser window will open; approve the request there)..."
  $W login
fi

FILES=$(ls -t backup/*_files.tar.gz 2>/dev/null | head -1 || true)
[ -n "$FILES" ] || { echo "No *_files.tar.gz in backup/"; exit 1; }
mkdir -p build/audio
if [ "$(ls build/audio | wc -l)" -lt 200 ]; then
  echo "Extracting audio from $FILES..."
  tar xzf "$FILES" -C build/audio --strip-components=2 'files_live/audio'
fi

n=0; total=$(ls build/audio | wc -l | tr -d ' ')
for f in build/audio/*; do
  n=$((n+1)); name=$(basename "$f")
  printf '[%d/%d] %s ... ' "$n" "$total" "$name"
  if out=$($W r2 object put "$BUCKET/$name" --file "$f" --content-type audio/mpeg \
        --cache-control "public, max-age=31536000" --remote 2>&1); then
    echo ok
  else
    echo FAILED; echo "$out" | tail -5; exit 1
  fi
done
echo "Uploaded $total files to R2 bucket $BUCKET."
