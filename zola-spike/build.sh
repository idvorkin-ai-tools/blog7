#!/usr/bin/env bash
# Spike build: copy the _data files the templates read (Zola refuses load_data
# paths that resolve outside the site dir, so a symlink to ../_data fails),
# convert the posts, build. ZOLA defaults to the spike's unpacked binary.
set -euo pipefail
cd "$(dirname "$0")"
ZOLA=${ZOLA:-$HOME/tmp/agent/skill/zola/zola}
mkdir -p data
cp ../_data/asins.json data/
# ponytail: _data/git.json is written by the Jekyll plugin (_plugins/git_data_generator.rb);
# a real port needs a pre-build script that runs git/gh itself.
if [ -f ../_data/git.json ]; then cp ../_data/git.json data/; else echo '{"branch":"unknown","pr_number":null,"changed_pages":[]}' > data/git.json; fi
./convert.py "$@" $(cat posts.txt) > convert-report.json
"$ZOLA" build -o "${OUT:-public}" --force
