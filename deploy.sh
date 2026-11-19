#!/usr/bin/env bash
# Publish ./site to GitHub Pages by force-pushing it as a single commit to the gh-pages branch.
# (Only the latest build is kept on that branch, so the repository doesn't grow with each deploy.)
#   ./deploy.sh            -> pushes to the repo in REPO below
set -euo pipefail
cd "$(dirname "$0")"
REPO=${REPO:-git@github.com:ralex981/bulgariandialectology-site.git}
[ -f site/index.html ] || { echo "Run ./build.sh first"; exit 1; }
if [ -d site/sites/default/files/audio ] && [ -n "$(ls site/sites/default/files/audio 2>/dev/null)" ]; then
  echo "site/ contains local audio (from add-audio.sh). Rebuild with ./build.sh before deploying."; exit 1
fi
[ -f site/CNAME ] || echo "Warning: no site/CNAME (set PAGES_DOMAIN when building) - GitHub may drop the custom domain."
cd site
rm -rf .git
git init -q -b gh-pages
git config http.postBuffer 1048576000
git add -A
git -c user.name="BDLT build" -c user.email="build@bulgariandialectology.org" commit -q -m "Site build $(date -u +%Y-%m-%dT%H:%MZ)"
echo "Pushing $(git ls-files | wc -l | tr -d ' ') files to $REPO (gh-pages)..."
git push -f "$REPO" gh-pages
rm -rf .git
echo "Done. GitHub Pages will publish in a few minutes."
