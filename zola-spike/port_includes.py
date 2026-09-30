#!/usr/bin/env python3
"""Mechanically translate the Liquid includes the spike needs into Tera 2 components
(Zola 0.23 removed shortcodes; content is rendered as Tera 2, then Markdown).

Only the constructs these includes use are handled: include.X, | default: 'v',
{% if include.X %}, {% case %}/{% when %}, {% comment %}. Anything left over
fails loudly so a missed construct can't ship silently.
"""

import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
out = Path(__file__).resolve().parent / "templates" / "components"
MECHANICAL = [
    "quadrant-matrix",
    "six-cell-matrix",
    "post-training-anim",
    "post-training-anim-assets",
    "youtube",
    "youtube_float_left",
    "local_image_float_right",
    "summarize-page",
]


def port(name: str, src: str) -> str:
    s = re.sub(
        r"\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}", "", src, flags=re.S
    )
    params = sorted(set(re.findall(r"include\.(\w+)", s)))
    s = re.sub(
        r"\{\{\s*include\.(\w+)\s*\|\s*default:\s*'([^']*)'\s*\}\}",
        r"{{ \1 or '\2' }}",
        s,
    )
    s = re.sub(r"\{\{\s*include\.(\w+)\s*\}\}", r'{{ \1 or "" }}', s)
    s = re.sub(r"\{%\s*if include\.(\w+)\s*%\}", r"{% if \1 %}", s)
    s = re.sub(
        r"\{%\s*case include\.(\w+)\s*%\}\s*\{%\s*when \"(\w+)\"\s*%\}",
        r'{% if \1 == "\2" %}',
        s,
    )
    s = re.sub(r"\{%\s*when \"(\w+)\"\s*%\}", r'{% elif name == "\1" %}', s)
    s = s.replace("{% endcase %}", "{% endif %}")
    left = re.findall(r"\{%(?!\s*(?:if|elif|else|endif)\b).*?%\}|include\.", s)
    if left:
        sys.exit(f"{name}: unported liquid: {left[:3]}")
    cname = name.replace("-", "_")
    sig = ", ".join(f"{p}=None" for p in params)
    return f"{{% component {cname}({sig}) -%}}\n{s.strip()}\n{{%- endcomponent {cname} %}}\n"


def flatten(src: str) -> str:
    """Make component output survive CommonMark.

    kramdown parses an HTML block to its matching close tag; CommonMark ends it
    at the first blank line, and 4-space-indented lines after that become an
    escaped code block. So: dedent every line, drop blank lines outside
    <style>/<script> (CommonMark keeps those open to the close tag), and
    left-trim tag-only lines so a false {% if %} can't leave a blank line.
    """
    out, raw = [], False
    for line in src.split("\n"):
        t = line.strip()
        if re.match(r"<(style|script)\b", t):
            raw = True
        if raw:
            out.append(line)
            if re.search(r"</(style|script)>", t):
                raw = False
            continue
        if not t:
            continue
        if (
            re.fullmatch(r"(\{%-?[^%]*%\}\s*)+", t)
            and not t.startswith("{%-")
            and "component" not in t
        ):
            t = "{%-" + t[2:]
        out.append(t)
    return "\n".join(out) + "\n"


for name in MECHANICAL:
    (out / f"{name.replace('-', '_')}.html").write_text(
        port(name, (root / "_includes" / f"{name}.html").read_text())
    )
    print("ported", name)

for f in sorted(out.glob("*.html")):
    f.write_text(flatten(f.read_text()))
print("flattened", len(list(out.glob("*.html"))), "components")
