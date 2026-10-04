#!/usr/bin/env bash
# Build the tailnet preview of the Zola port into zola/public-preview:
# the site with base_url = the preview URL (so CSS, canonical links and
# same-page anchors stay on the preview), back-links.json, a Pagefind index,
# and the full-site diff report at /_port/.
#
#   PREVIEW_URL=https://host.ts.net:8448 zola/preview.sh
set -euo pipefail
cd "$(dirname "$0")"
: "${PREVIEW_URL:?set PREVIEW_URL}"
REPO=$(cd .. && pwd)

# The diff compares against an idvork.in-based build.
./build.sh
[ -f ../back-links.json ] || { echo "no back-links.json: run 'just update-backlinks' (needs a Jekyll _site)" >&2; exit 1; }
./diff_sites.py ../_site public > diff-report.json

OUT=public-preview BASE_URL="$PREVIEW_URL" ./build.sh
# ponytail: back-links.json still comes from build_back_links.py over the
# Jekyll _site (it reads _site/x.html). Keys are /x; src/main.ts trims the /x/
# trailing slash before looking a page up. Cutover: point it at zola/public.
cp ../back-links.json public-preview/back-links.json
npx --yes pagefind@1.5.2 --site public-preview > pagefind.log 2>&1 || { tail -20 pagefind.log; exit 1; }
mkdir -p public-preview/_port
python3 report.py diff-report.json convert-report.json "$PREVIEW_URL" > public-preview/_port/index.html
cp diff-report.json public-preview/_port/diff-report.json
echo "preview ready: $PREVIEW_URL  report: $PREVIEW_URL/_port/"
