#!/usr/bin/env bash
# Build the Zola port of the blog (bead blog-pzp).
#
#   zola/build.sh                 # -> zola/public (base_url https://idvork.in)
#   OUT=dir BASE_URL=url zola/build.sh   # e.g. the tailnet preview build
#
# Steps: stage the static files Jekyll would copy, copy _data (Zola refuses
# load_data paths outside the site dir, so a symlink fails), write the dev
# banner's git.json (Jekyll's _plugins/git_data_generator.rb did this), port
# the includes, convert every page, then zola build.
set -euo pipefail
cd "$(dirname "$0")"
ZOLA=${ZOLA:-$HOME/tmp/agent/skill/zola/zola}
"$ZOLA" --version | grep -q '0\.23\.' || { echo "need zola 0.23.x" >&2; exit 1; }

./stage_static.py > static-report.json
rm -rf data && mkdir -p data && cp ../_data/*.json ../_data/*.yml data/
branch=$(git -C .. rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)
printf '{"branch":"%s","pr_number":null,"changed_pages":[]}\n' "$branch" > data/git.json
python3 port_includes.py > /dev/null
./convert.py > convert-report.json
args=(build -o "${OUT:-public}" --force)
[ -n "${BASE_URL:-}" ] && args+=(--base-url "$BASE_URL")
"$ZOLA" "${args[@]}"
