#!/usr/bin/env bash
# Copy the recordings from the Pantheon files backup into site/ so the local preview plays audio.
# (For the public site, host the audio separately and build with AUDIO_BASE instead; see README.)
set -euo pipefail
cd "$(dirname "$0")"
FILES=$(ls -t backup/*_files.tar.gz 2>/dev/null | head -1 || true)
[ -n "$FILES" ] || { echo "No *_files.tar.gz in backup/"; exit 1; }
[ -d site ] || { echo "Run ./build.sh first"; exit 1; }
mkdir -p site/sites/default/files
echo "Extracting audio from $FILES (about 1 GB)..."
tar xzf "$FILES" -C site/sites/default/files --strip-components=1 'files_live/audio'
echo "Done: $(ls site/sites/default/files/audio | wc -l | tr -d ' ') audio files in site/sites/default/files/audio"
