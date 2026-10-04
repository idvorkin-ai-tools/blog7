#!/usr/bin/env python3
"""Port _includes/*.html to Tera 2 components (Zola 0.23 has no shortcodes;
content is rendered as Tera 2, then Markdown).

MECHANICAL includes are translated from the Liquid source on every run, so they
track edits to _includes/. They only use: include.X, | default: 'v',
{% if include.X %}, {% case %}/{% when %}, {% comment %}, {% raw %},
site.data.X | jsonify. Anything else fails loudly.

The rest are hand-ported files in templates/components/ (see git): their Liquid
used page-global state (emit-once flags, capture/assign chains) that has no
mechanical Tera 2 equivalent. Every component, hand or mechanical, is then
flattened, because CommonMark ends an HTML block at the first blank line.
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
    "banana-back",
    "backpack-back",
    "time-allocation-buckets",
    "orchestrator-diagram",
    "den_viewer",
    "collapse",
]
DATA_EXT = {p.stem: p.name for p in (root / "_data").iterdir()}


def port(name: str, src: str) -> str:
    s = re.sub(
        r"\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}", "", src, flags=re.S
    )
    s = re.sub(
        r"\{\{\s*site\.data\.(\w+)\s*\|\s*jsonify\s*\}\}",
        lambda m: f'{{{{ load_data(path="data/{DATA_EXT[m.group(1)]}") | json_encode | safe }}}}',
        s,
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
    left = re.findall(
        r"\{%(?!-?\s*(?:if|elif|else|endif|raw|endraw)\b).*?%\}|include\.", s
    )
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
    <style>/<script>/<pre> (CommonMark keeps those open to the close tag), and
    left-trim tag-only lines so a false {% if %} can't leave a blank line.
    """
    if "flatten: off" in src:
        return src
    out, raw = [], None
    for line in src.split("\n"):
        t = line.strip()
        m = re.match(r"<(style|script|pre|textarea)\b", t)
        if m and not re.search(rf"</{m.group(1)}>", t):
            raw = m.group(1)
            if raw in ("pre", "textarea") and out and out[-1].strip():
                # Start a fresh CommonMark HTML block (type 1), which runs to
                # the close tag even across the blank lines <pre> may hold.
                out.append("")
            out.append(t)
            continue
        if raw:
            # A <script>/<style> line inside the component's one HTML block
            # must not be blank: the block would end there and the rest of
            # the code would be parsed as Markdown. <pre> keeps its blanks.
            if t or raw in ("pre", "textarea"):
                out.append(line)
            if re.search(rf"</{raw}>", t):
                raw = None
            continue
        if not t:
            continue
        if (
            re.fullmatch(r"(\{%-?[^%]*%\}\s*)+", t)
            and not t.startswith("{%-")
            and "component" not in t
            and "raw" not in t
        ):
            t = "{%-" + t[2:]
        out.append(t)
    return "\n".join(out) + "\n"


def must_sub(pattern: str, repl: str, s: str, name: str, flags=re.S) -> str:
    new, n = re.subn(pattern, repl, s, flags=flags)
    if not n:
        sys.exit(f"{name}: pattern not found, re-port by hand: {pattern[:60]}")
    return new


def strip_comments(s: str) -> str:
    return re.sub(
        r"\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}", "", s, flags=re.S
    )


def wrap(cname: str, sig: str, body: str) -> str:
    left = re.findall(
        r"\{%(?!-?\s*(?:if|elif|else|endif|raw|endraw|for|endfor|set|endset)\b).*?%\}|include\.|site\.",
        body,
    )
    if left:
        sys.exit(f"{cname}: unported liquid: {left[:3]}")
    return f"{{% component {cname}({sig}) -%}}\n{body.strip()}\n{{%- endcomponent {cname} %}}\n"


def special_ports() -> dict[str, str]:
    """Includes that kept page-global emit-once flags or capture/assign chains.

    Tera 2 components are stateless, so emit-once becomes an `assets` flag the
    converter sets to false on every call after a page's first (convert.py
    ONCE_PER_PAGE). Each port is targeted replacements on the live Liquid source
    and exits if a pattern stops matching, so an _includes/ edit can't drift
    silently.
    """
    inc = lambda n: (root / "_includes" / f"{n}.html").read_text()  # noqa: E731
    ported = {}

    s = strip_comments(inc("orchestrator-shared"))
    s = must_sub(
        r"\{%-?\s*unless\s+orc_shared_done\s*-?%\}\s*\{%-?\s*assign orc_shared_done = true\s*-?%\}",
        "",
        s,
        "orchestrator-shared",
    )
    s = must_sub(r"\{%-?\s*endunless\s*-?%\}", "", s, "orchestrator-shared")
    s = must_sub(
        r"\{\{\s*site\.data\.orchestrator_blocks\s*\|\s*jsonify\s*\}\}",
        '{{ load_data(path="data/orchestrator_blocks.yml") | json_encode | safe }}',
        s,
        "orchestrator-shared",
    )
    ported["orchestrator_shared"] = wrap("orchestrator_shared", "", s)

    s = strip_comments(inc("orchestrator-viewer-assets"))
    s = must_sub(
        r"\{%-?\s*unless\s+orc_viewer_css_done\s*-?%\}\s*\{%-?\s*assign\s+orc_viewer_css_done = true\s*-?%\}",
        "",
        s,
        "orchestrator-viewer-assets",
    )
    s = must_sub(r"\{%-?\s*endunless\s*-?%\}", "", s, "orchestrator-viewer-assets")
    ported["orchestrator_viewer_assets"] = wrap("orchestrator_viewer_assets", "", s)

    s = strip_comments(inc("orchestrator-viewer"))
    s = must_sub(
        r"\{%-?\s*include orchestrator-shared\.html\s*-?%\}\s*\{%-?\s*assign pos =\s*include\.controls \| default: \"top\"\s*-?%\}\s*\{%-?\s*assign vid = include\.id \| default:\s*\"orc-viewer\"\s*-?%\}\s*\{%-?\s*include orchestrator-viewer-assets\.html\s*-?%\}",
        "{% if assets %}\n{{<orchestrator_shared />}}\n{{<orchestrator_viewer_assets />}}\n{% endif %}\n"
        "{%- set pos = controls -%}{%- set vid = id -%}\n"
        '{%- set ob = load_data(path="data/orchestrator_blocks.yml") -%}',
        s,
        "orchestrator-viewer",
    )
    s = must_sub(
        r"\{%-\s*capture (orc_\w+)\s*-%\}", r"{%- set \1 -%}", s, "orchestrator-viewer"
    )
    s = must_sub(
        r"\{%-\s*endcapture\s*-%\}", "{%- endset -%}", s, "orchestrator-viewer"
    )
    s = must_sub(r"site\.data\.orchestrator_blocks", "ob", s, "orchestrator-viewer")
    s = must_sub(r"forloop\.index", "loop.index", s, "orchestrator-viewer")
    s = must_sub(
        r"\{\{\s*orc_bar\s*\}\}", "{{ orc_bar | safe }}", s, "orchestrator-viewer"
    )
    s = must_sub(
        r"\{\{\s*orc_story\s*\}\}", "{{ orc_story | safe }}", s, "orchestrator-viewer"
    )
    s = must_sub(
        r"\{%\s*include orchestrator-diagram\.html\s*%\}",
        "{{<orchestrator_diagram />}}",
        s,
        "orchestrator-viewer",
    )
    ported["orchestrator_viewer"] = wrap(
        "orchestrator_viewer", 'controls="top", id="orc-viewer", assets=true', s
    )

    s = strip_comments(inc("orchestrator-stack"))
    s = must_sub(
        r"\{%-?\s*include orchestrator-shared\.html\s*-?%\}\s*\{%-?\s*include\s+orchestrator-viewer-assets\.html\s*-?%\}",
        "{% if assets %}\n{{<orchestrator_shared />}}\n{{<orchestrator_viewer_assets />}}\n{% endif %}",
        s,
        "orchestrator-stack",
    )
    s = must_sub(
        r'\{%\s*include orchestrator-viewer\.html controls="top" id="orc-stack-view"\s*%\}',
        '{{<orchestrator_viewer controls="top" id="orc-stack-view" assets={false} />}}',
        s,
        "orchestrator-stack",
    )
    ported["orchestrator_stack"] = wrap("orchestrator_stack", "assets=true", s)
    return ported


for name in MECHANICAL:
    (out / f"{name.replace('-', '_')}.html").write_text(
        port(name, (root / "_includes" / f"{name}.html").read_text())
    )
    print("ported", name)
for cname, text in special_ports().items():
    (out / f"{cname}.html").write_text(text)
    print("ported (targeted)", cname)

for f in sorted(out.glob("*.html")):
    f.write_text(flatten(f.read_text()))
print("flattened", len(list(out.glob("*.html"))), "components")
