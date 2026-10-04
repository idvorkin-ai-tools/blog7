#!/usr/bin/env python3
"""Give the Zola build a back-links.json its /x/ URLs can find (preview only).

build_back_links.py still reads Jekyll's _site/x.html shape, so the index is
built from the Jekyll build (CI does the same today) and copied here with every
url_info key also present as "/x/", because the bundle looks pages up by
location.pathname, which is /x/ on Zola.

ponytail: cutover needs build_back_links.py to read zola/public directly (its
"_site" and ".html" path assumptions); this shim then goes away.

usage: backlinks_shim.py <back-links.json> <zola public dir>
"""

import json
import sys
from pathlib import Path

src, out = Path(sys.argv[1]), Path(sys.argv[2])
data = json.loads(src.read_text())
info = data["url_info"]
for url in list(info):
    if url != "/" and not url.endswith("/"):
        info.setdefault(url + "/", info[url])
(out / "back-links.json").write_text(json.dumps(data))
print(f"back-links.json: {len(info)} keys (with /x/ twins)")
