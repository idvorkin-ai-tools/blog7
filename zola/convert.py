#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pyyaml", "typer"]
# ///
"""Convert every Jekyll page into Zola content (bead blog-pzp).

usage: convert.py            # writes zola/content/, prints a JSON report

Sources: the _d, _posts, _td, _ig66, _test collections plus the root
front-matter pages. Feed-like root files (feed.xml, sitemap.xml, search*.json,
links.jsonp) are Zola templates instead, see templates/.

Per page:
- Front matter -> YAML front matter Zola accepts: title, path, date, aliases
  (from redirect_from), taxonomies.tags, template (from layout), and the whole
  original front matter under extra (keys with '-' get '_').
- {% include x.html k="v" %} -> {{<x k="v" />}} (Tera 2 component call).
- {% post_url %} -> the target's path; {% comment %} blocks dropped.
- Heading ids pinned to the kramdown/GFM slug ({#id}) so deep links survive.
- Relative links resolved against the page's Jekyll URL, because /x and /x/
  resolve "y" differently.
- kramdown-only syntax: markdown="1" stripped, {:start="N"} applied to the
  list, a blank line added after a lone HTML tag line that is followed by
  Markdown (CommonMark keeps an HTML block open until a blank line).
- .html sources (no Markdown in Jekyll either) and pages listed in
  TEMPLATE_PAGES become templates, so CommonMark never sees their HTML.

Anything Liquid left over fails the conversion, so nothing ships silently.
"""

import datetime
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / ".claude/skills/toc"))
from toc import slugify as toc_slugify  # noqa: E402  the GFM slug rule kramdown's GFM parser uses

CONTENT = HERE / "content"
GENERATED = HERE / "templates" / "generated"
COLLECTIONS = {"_d": "d", "_td": "td", "_ig66": "ig66", "_test": "test", "_posts": None}
# Root files rendered by a template of their own name (feeds/json) — skipped here.
FEED_FILES = {
    "feed.xml",
    "sitemap.xml",
    "search.json",
    "search-titles.json",
    "search-pins.json",
    "links.jsonp",
}
# Listing pages whose Liquid loops over site.* — hand-ported to Tera templates.
TEMPLATE_PAGES = {
    "index.md": "generated",
    "featured.html": "generated",
    "tags.html": "pages/tags.html",
    "categories.html": "pages/categories.html",
    "all-posts.md": "pages/all_posts.html",
    "_d/index.html": "pages/d_index.html",
    "_d/weeks.md": "pages/weeks.html",
    "_ig66/index.md": "pages/ig66_index.html",
}
# Pure-HTML pages with one small Liquid loop: fix the loop, keep the page.
FEATURED_LOOP = (
    r"\{%\s*for url in site\.data\.featured\.featured_posts\s*%\}(.*?)\{%\s*unless forloop\.last\s*%\},\{%\s*endunless\s*%\}(.*?)\{%\s*endfor\s*%\}",
    r'{% set featured = load_data(path="data/featured.yml") %}{% for url in featured.featured_posts %}\1{% if not loop.last %},{% endif %}\2{% endfor %}',
)
LIQUID_FIXES = {
    "index.md": [FEATURED_LOOP],
    "featured.html": [FEATURED_LOOP],
    "linkedin.html": [
        (r"\{\{\s*site\.google_analytics\s*\}\}", "{{ config.extra.google_analytics }}")
    ],
}
LAYOUTS = {"post": "post", "page": "page"}
LABELS = {
    "_d": "d",
    "_td": "td",
    "_ig66": "ig66",
    "_test": "test",
    "_posts": "posts",
}  # anything else -> empty

FM = re.compile(r"\A---\s*\n(.*?)\n---[ \t]*\n?(.*)\Z", re.S)
INCLUDE = re.compile(
    r"\{%-?\s*include\s+([\w.-]+?)(?:\.html|\.md)?\s+(.*?)\s*-?%\}|\{%-?\s*include\s+([\w.-]+?)(?:\.html|\.md)?\s*-?%\}",
    re.S,
)
# Jekyll's include arg syntax: quoted values allow backslash escapes.
ARG = re.compile(
    r"""([\w-]+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|(\S+))""", re.S
)
COMMENT = re.compile(r"\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}", re.S)
POST_URL = re.compile(r"\{%-?\s*post_url\s+([\w./-]+)\s*-?%\}")
# Includes whose output needs page state Jekyll handed them implicitly.
# Include arguments that are URLs, resolved like the page's own links.
URL_ARGS = {
    "summarize_page": ("src",),
    "image_float_right": ("link",),
    "quote": ("url",),
    "ai_voice": ("link",),
}
# (Components that need page state declare an @page parameter instead.)
PAGE_ARGS: dict[str, dict[str, str]] = {}
# Liquid emitted these assets once per page via a global flag; components are
# stateless, so every call after the page's first gets assets=false.
ONCE_PER_PAGE = {"orchestrator_viewer", "orchestrator_stack"}
# Layout partials some template pages include directly.
PARTIALS = {
    "head",
    "site_menu",
    "toc",
    "scripts",
    "tags",
    "pagefind_attrs",
    "annotate",
    "mermaid",
}


def component_params() -> dict[str, set[str]]:
    """Declared parameters per component; Liquid ignored unknown include args,
    a Tera 2 component call errors on them, so the converter drops (and logs)
    any argument the component does not declare."""
    out = {}
    for f in (HERE / "templates" / "components").glob("*.html"):
        m = re.search(
            r"\{%-?\s*component\s+(\w+)\((.*?)\)\s*-?%\}", f.read_text(), re.S
        )
        if m:
            out[m.group(1)] = {
                a.split("=")[0].strip()
                for a in m.group(2).split(",")
                if a.strip() and not a.strip().startswith("@")
            }
    return out


PARAMS = component_params()
DEN = {str(e["num"]): e for e in json.loads((REPO / "_data/den.json").read_text())}


def slugify(text: str, seen: dict | None = None) -> str:
    """The id kramdown gave a heading: toc.py's GFM rule, applied to the text
    kramdown saw after entity decoding and smart typography (so "--" is an en
    dash that the slug drops, and "&#8217;" an apostrophe)."""
    text = html.unescape(text)
    text = (
        text.replace("---", "\u2014").replace("--", "\u2013").replace("...", "\u2026")
    )
    return toc_slugify(text, seen)


def tera_str(v: str) -> str:
    """Tera string literals have no escapes: pick a delimiter the value lacks."""
    for q in ('"', "'", "`"):
        if q not in v:
            return f"{q}{v}{q}"
    raise ValueError(f"value contains all three quote kinds: {v[:60]}")


def jekyll_url(src: str, fm: dict) -> str:
    """The URL Jekyll serves the page at, without .html and without a trailing slash."""
    p = Path(src)
    top = p.parts[0]
    if fm.get("permalink"):
        url = str(fm["permalink"])
    elif top == "_posts":
        m = re.match(r"\d{4}-\d{1,2}-\d{1,2}-(.*)", p.stem)
        url = "/" + (m.group(1) if m else p.stem)
    elif top in COLLECTIONS:
        url = f"/{COLLECTIONS[top]}/" + "/".join(p.parts[1:-1] + (p.stem,))
    else:
        url = "/" + p.with_suffix("").as_posix()
    url = re.sub(r"/index(\.html)?$", "/", url)
    url = re.sub(r"\.html$", "", url)
    url = "/" + url.strip("/")
    return url


def jekyll_base(src: str, fm: dict, url: str) -> str:
    """What the browser resolved relative links against on Jekyll: /x for
    x.html, but /x/ for a page served as x/index.html."""
    p = Path(src)
    raw = str(fm.get("permalink") or "")
    if (
        raw.endswith("/")
        or raw.endswith("/index.html")
        or (not raw and p.stem == "index")
    ):
        return url.rstrip("/") + "/"
    return url


def include_to_component(m: re.Match, notes: dict) -> str:
    raw_name = m.group(1) or m.group(3)
    argstr = m.group(2) or ""
    name = raw_name.replace("-", "_")
    if name in PARTIALS:
        return f'{{% include "partials/{name}.html" %}}'
    args = []
    if name not in PARAMS:
        raise ValueError(f"no component for include {raw_name}")
    for k, dq, sq, bare in ARG.findall(argstr):
        k = k.replace("-", "_")
        if k not in PARAMS[name]:
            notes.setdefault("dropped_args", []).append(f"{name}.{k}")
            continue
        if bare:
            if bare.startswith("page."):
                args.append(f"{k}={{page.extra.{bare[5:].replace('-', '_')}}}")
                continue
            if not re.fullmatch(r"[\w./:-]+", bare):
                raise ValueError(f"include {raw_name}: bare arg {k}={bare}")
            val = bare
        else:
            val = dq if dq or not sq else sq
            val = val.replace('\\"', '"').replace("\\'", "'")
        if k in URL_ARGS.get(name, ()) and not re.match(
            r"[a-z][a-z0-9+.-]*:|/|#", val, re.I
        ):
            new = urljoin("https://idvork.in" + notes["base"], val).removeprefix(
                "https://idvork.in"
            )
            notes.setdefault("relative_links", []).append(f"{val} -> {new}")
            val = new
        args.append(f"{k}={tera_str(val)}")
    for k, expr in PAGE_ARGS.get(name, {}).items():
        args.append(f"{k}={expr}")
    if name in ONCE_PER_PAGE:
        if notes.get("assets_done"):
            args.append("assets={false}")
        notes["assets_done"] = True
    if name == "den_strip":
        kv = dict((k, dq or sq or bare) for k, dq, sq, bare in ARG.findall(argstr))
        title = DEN.get(kv["num"], {}).get("title") or kv.get("title", "")
        args.append(f"anchor={tera_str(slugify('#' + kv['num'] + ' — ' + title))}")
    notes.setdefault("includes", {}).setdefault(name, 0)
    notes["includes"][name] += 1
    return "{{<" + " ".join([name, *args]) + " />}}"


def place(m: re.Match, body: str, call: str, notes: dict) -> str:
    """Keep a component's multi-line output inside the Markdown block it sits in.

    kramdown kept an include's output inside a list item or a paragraph;
    CommonMark lets a flattened HTML line at column 0 open a new HTML block
    that swallows everything to the next blank line. So a call indented under
    a list item gets its output indented to match, and a call in the middle of
    a line gets its output joined onto that line.
    """
    if call.startswith("{%"):
        return call
    line_start = body.rfind("\n", 0, m.start()) + 1
    prefix = body[line_start : m.start()]
    if not prefix:
        return call
    if not prefix.strip():
        notes["indented_calls"] = notes.get("indented_calls", 0) + 1
        return f"{{% set _inc %}}{call}{{% endset %}}{{{{ _inc | indent(width={len(prefix)}) }}}}"
    notes["inline_calls"] = notes.get("inline_calls", 0) + 1
    return f'{{% set _inc %}}{call}{{% endset %}}{{{{ _inc | replace(from="\n", to=" ") }}}}'


def split_fences(body: str):
    """Yield (is_code, chunk) so rewrites skip fenced and indented code."""
    out, buf, fence = [], [], None
    for line in body.split("\n"):
        s = line.lstrip()
        if fence is None and (s.startswith("```") or s.startswith("~~~")):
            out.append((False, buf))
            buf, fence = [line], s[:3]
            continue
        if fence is not None:
            buf.append(line)
            if s.startswith(fence):
                out.append((True, buf))
                buf, fence = [], None
            continue
        buf.append(line)
    out.append((fence is not None, buf))
    return [(c, "\n".join(b)) for c, b in out if b]


def pin_heading_ids(text: str, seen: dict) -> str:
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m and not re.search(r"\{#[^}]*\}\s*$", m.group(2)):
            line = f"{m.group(1)} {m.group(2)} {{#{slugify(m.group(2), seen)}}}"
        elif m:
            # Already pinned: still claim the slug so later duplicates suffix.
            seen.setdefault(re.search(r"\{#([^}]*)\}", m.group(2)).group(1), 0)
        # Setext heading: a one-line paragraph underlined with === or ---.
        elif (
            re.fullmatch(r"(=+|-{2,})\s*", line)
            and out
            and out[-1].strip()
            and not re.match(r"\s|[|\-*>#<+\d]", out[-1])
            and (len(out) < 2 or not out[-2].strip())
        ):
            level = "#" if line.startswith("=") else "##"
            heading = out.pop().strip()
            line = f"{level} {heading} {{#{slugify(heading, seen)}}}"
        out.append(line)
    return "\n".join(out)


HTML_LINE = re.compile(
    r"^\s*(</?(div|details|summary|figure|figcaption|section|aside|nav|p|table|center|span|br|hr)\b[^>]*/?>\s*)+$"
)
MD_START = re.compile(r"^\s{0,3}([*+-]\s|\d+[.)]\s|#{1,6}\s|>|\|)")
RAW_BLOCK = re.compile(
    r"<(div|p|details|table|figure|section|center|aside|nav|blockquote|ul|ol|dl|form|iframe)\b([^>]*)>"
)


def raw_html_blocks(lines: list[str], notes: dict) -> list[str]:
    """kramdown (parse_block_html off) reads a column-0 HTML block up to its
    matching close tag as raw HTML; CommonMark ends it at the first blank line
    and parses the rest as Markdown. Drop the blank lines inside such a block
    (only those without markdown=, which kept kramdown parsing Markdown)."""
    out, i = [], 0
    while i < len(lines):
        m = RAW_BLOCK.match(lines[i])
        if not m or "markdown=" in m.group(2):
            out.append(lines[i])
            i += 1
            continue
        tag, depth, j = m.group(1), 0, i
        while j < len(lines):
            depth += len(re.findall(rf"<{tag}\b", lines[j])) - len(
                re.findall(rf"</{tag}>", lines[j])
            )
            if depth <= 0:
                break
            j += 1
        span = lines[i : j + 1]
        if j < len(lines) and any(not x.strip() for x in span):
            notes["raw_html_blocks"] = notes.get("raw_html_blocks", 0) + 1
            span = [x for x in span if x.strip()]
        out += span
        i = j + 1
    return out


def kramdownisms(text: str, notes: dict) -> str:
    lines = raw_html_blocks(text.split("\n"), notes)
    text = re.sub(r'\s+markdown="(1|block|span)"', "", "\n".join(lines))
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        m = re.fullmatch(r'\{:\s*start="?(\d+)"?\s*\}\s*', line)
        if m:
            # Apply to the ordered list that follows: CommonMark starts it at
            # its first item's number.
            for j in range(i + 1, min(i + 4, len(lines))):
                if re.match(r"\s*\d+\.\s", lines[j]):
                    lines[j] = re.sub(r"\d+", m.group(1), lines[j], count=1)
                    break
            notes.setdefault("ial_applied", []).append(line.strip())
            continue
        if re.fullmatch(r"\{:.*\}\s*", line):
            notes.setdefault("ial_dropped", []).append(line.strip())
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        call = CALL_LINE.fullmatch(line)
        if call and nxt.strip() and not CALL_LINE.fullmatch(nxt):
            if call.group(1) in INLINE_COMPONENTS and not (
                MD_START.match(nxt) or nxt.lstrip().startswith("<")
            ):
                # An <img> alone on a line opens a CommonMark HTML block that
                # swallows the paragraph below; with text after it on the same
                # line it is inline, as kramdown read it.
                lines[i + 1] = line.rstrip() + " " + nxt
                notes["joined_img_calls"] = notes.get("joined_img_calls", 0) + 1
                continue
            if call.group(1) not in MARKDOWN_COMPONENTS:
                out += [line, ""]
                notes["blank_after_call"] = notes.get("blank_after_call", 0) + 1
                continue
        out.append(line)
        if HTML_LINE.match(line) and MD_START.match(nxt):
            out.append("")
            notes["blank_after_html"] = notes.get("blank_after_html", 0) + 1
    return "\n".join(out)


CALL_LINE = re.compile(r"\{\{<(\w+)\b.*/>\}\}\s*")
# Components whose whole output is one inline <img> (float-right pictures).
INLINE_COMPONENTS = {
    "local_image_float_right",
    "blob_image_float_right",
    "image_float_right",
    "repo_image_float_right",
    "ipaste_image_float_right",
    "blob_image_float_right_w25",
    "mpl_render_float_right",
}
# Components that emit Markdown, which flows into the paragraph as kramdown did.
MARKDOWN_COMPONENTS = {
    "blob_image",
    "repo_image",
    "mpl_render",
    "this_is_part_of_saas",
    "link_blog_montage",
}


LINK_MD = re.compile(r"(\]\()(\s*<?)([^)\s>]+)")
LINK_REF = re.compile(r"^(\s{0,3}\[[^\]]+\]:\s*)(\S+)", re.M)
LINK_HTML = re.compile(r"""(\b(?:href|src)=)(["'])([^"']*)\2""")


def absolutize(text: str, base: str, notes: dict) -> str:
    """Resolve relative URLs against the Jekyll URL (served without a slash)."""

    def fix(url: str) -> str:
        if not url or re.match(r"[a-z][a-z0-9+.-]*:|/|#|\{", url, re.I):
            return url
        new = urljoin("https://idvork.in" + base, url).removeprefix("https://idvork.in")
        notes.setdefault("relative_links", []).append(f"{url} -> {new}")
        return new

    def fix_all(seg: str) -> str:
        seg = LINK_MD.sub(lambda m: m.group(1) + m.group(2) + fix(m.group(3)), seg)
        seg = LINK_REF.sub(lambda m: m.group(1) + fix(m.group(2)), seg)
        seg = LINK_HTML.sub(
            lambda m: m.group(1) + m.group(2) + fix(m.group(3)) + m.group(2), seg
        )
        return re.sub(r"\]\(\s*\)", "](#)", seg)

    # Component calls carry ids (youtube src="abc"), not URLs: leave them be.
    parts = re.split(r"(\{\{<.*?/>\}\}|`+[^`\n]*`+)", text, flags=re.S)
    return "".join(p if i % 2 else fix_all(p) for i, p in enumerate(parts))


def plain(md: str) -> str:
    """Jekyll's excerpt is the first paragraph, rendered then strip_html'd."""
    t = re.sub(r"<!--.*?-->", " ", md, flags=re.S)
    t = re.sub(r"\{\{<.*?/>\}\}", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"\{#[^}]*\}", "", t)
    t = re.sub(r"[*_`]", "", t)
    return " ".join(t.split())


def aliases_of(fm: dict) -> list[str]:
    a = fm.get("redirect_from") or []
    return ["/" + str(x).strip().strip("/") for x in ([a] if isinstance(a, str) else a)]


def jsonable(v):
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    # TOML (which Zola maps extra onto) has no null: drop None values.
    if isinstance(v, dict):
        return {
            str(k).replace("-", "_").replace(" ", "_"): jsonable(x)
            for k, x in v.items()
            if x is not None
        }
    if isinstance(v, list):
        return [jsonable(x) for x in v if x is not None]
    return v


def zola_date(fm: dict, src: str):
    d = fm.get("date")
    if isinstance(d, str):
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", d)
        d = datetime.date(*map(int, m.groups())) if m else None
    if isinstance(d, datetime.datetime):
        d = d.date()
    if not d:
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})-", Path(src).name)
        if m and Path(src).parts[0] == "_posts":
            d = datetime.date(*map(int, m.groups()))
    return d.isoformat() if isinstance(d, datetime.date) else None


def sources() -> list[str]:
    out = []
    for d in COLLECTIONS:
        for p in sorted((REPO / d).rglob("*")):
            rel = p.relative_to(REPO)
            if p.suffix in (".md", ".html", ".markdown") and not any(
                x.startswith((".", "_")) for x in rel.parts[1:]
            ):
                if p.read_bytes().startswith(b"---"):
                    out.append(rel.as_posix())
    staged = json.loads((HERE / "static-report.json").read_text())["root_pages"]
    out += [p for p in staged if p not in FEED_FILES]
    return out


def main() -> None:
    CONTENT.mkdir(exist_ok=True)
    GENERATED.mkdir(parents=True, exist_ok=True)
    for old in list(CONTENT.glob("*.md")) + list(GENERATED.glob("*.html")):
        old.unlink()

    srcs = sources()
    parsed = {}
    for src in srcs:
        m = FM.match((REPO / src).read_text())
        if not m:
            continue
        parsed[src] = (yaml.safe_load(m.group(1)) or {}, m.group(2))

    urls = {src: jekyll_url(src, fm) for src, (fm, _) in parsed.items()}
    post_urls = {Path(s).stem: u for s, u in urls.items() if s.startswith("_posts/")}
    report = {"pages": {}, "collisions": [], "alias_dropped": [], "errors": {}}
    tag_docs: dict[str, set] = {}
    taken: dict[str, str] = {}
    for src, url in urls.items():
        if url in taken:
            report["collisions"].append(f"{url}: {taken[url]} wins over {src}")
        else:
            taken[url] = src

    # jekyll-redirect-from writes its stubs after root pages and before
    # collection documents, in page-then-document order: the last write to a
    # URL wins. So an alias beats a root page, a document beats an alias, and
    # of two pages claiming one alias the later one wins.
    def jekyll_order(src: str):
        top = Path(src).parts[0] if len(Path(src).parts) > 1 else ""
        return (["", "_posts", "_d", "_td", "_ig66", "_test"].index(top), src)

    alias_owner: dict[str, str] = {}
    for src in sorted(parsed, key=jekyll_order):
        for a in aliases_of(parsed[src][0]):
            alias_owner[a] = src
    doc_urls = {u for s_, u in urls.items() if len(Path(s_).parts) > 1}
    shadowed = {
        s_
        for s_, u in urls.items()
        if len(Path(s_).parts) == 1
        and u in {re.sub(r"\.html$", "", a) for a in alias_owner}
    }

    for src, (fm, body) in parsed.items():
        if taken[urls[src]] != src:
            continue
        if src in shadowed:
            report["shadowed_by_alias"] = report.get("shadowed_by_alias", []) + [src]
            continue
        url = urls[src]
        notes: dict = {}
        try:
            body = COMMENT.sub("", body)
            body = POST_URL.sub(lambda m: post_urls[m.group(1)], body)
            notes["base"] = jekyll_base(src, fm, url)
            body = INCLUDE.sub(
                lambda m: place(m, body, include_to_component(m, notes), notes), body
            )
            is_template = src in TEMPLATE_PAGES or src.endswith(".html")
            if not is_template:
                seen: dict = {}
                parts = []
                for code, chunk in split_fences(body):
                    if not code:
                        chunk = kramdownisms(chunk, notes)
                        chunk = absolutize(chunk, jekyll_base(src, fm, url), notes)
                        chunk = pin_heading_ids(chunk, seen)
                    parts.append(chunk)
                body = "\n".join(parts)
                left = re.findall(
                    r"\{%(?!\s*-?\s*(?:raw|endraw|set _inc|endset)\b).*?%\}|\{\{(?!<|\s*_inc\b).*?\}\}",
                    body,
                    flags=re.S,
                )
                if left:
                    raise ValueError(f"unconverted liquid {left[:3]}")
        except Exception as e:  # noqa: BLE001 — collected and fails the build below
            report["errors"][src] = str(e)
            continue

        kept = []
        for a in aliases_of(fm):
            if alias_owner.get(a) != src:
                report["alias_dropped"].append(
                    f"{a} on {src}: Jekyll wrote {alias_owner.get(a)}'s"
                )
            elif re.sub(r"\.html$", "", a) in doc_urls or a == url:
                report["alias_dropped"].append(f"{a} on {src}: a document has this URL")
            else:
                kept.append(a)

        # Jekyll's Utils.pluralized_array_from_hash: a singular `tag:` wins,
        # a string is split on whitespace.
        tag = fm.get("tag")
        tags = (
            (tag if isinstance(tag, list) else [tag]) if tag else (fm.get("tags") or [])
        )
        tags = tags.split() if isinstance(tags, str) else [str(t) for t in tags if t]
        if len(Path(src).parts) > 1:
            for t in tags:
                tag_docs.setdefault(t, set()).add(src)
        layout = str(fm.get("layout") or "")
        extra = jsonable(dict(fm))
        extra.update(
            source_path=src,
            permalink=url,
            tags_list=tags,
            # kramdown's id for a "### [title](url)" heading on listing pages.
            title_slug=slugify(str(fm.get("title") or "")),
            layout=LAYOUTS.get(layout, "empty"),
            collection=LABELS.get(Path(src).parts[0])
            if len(Path(src).parts) > 1
            else None,
            # Jekyll's Document#<=>: date (undated docs get site.time, i.e.
            # last), then path; collections iterate in label order.
            sort_key=f"{LABELS.get(Path(src).parts[0], '~')}|{zola_date(fm, src) or '9999'}|{src}",
            jekyll_date=str(fm["date"]) if fm.get("date") else None,
            # Jekyll pages (root files) have no excerpt; documents do.
            excerpt=plain(body.strip().split("\n\n")[0])
            if len(Path(src).parts) > 1 and body.strip()
            else None,
        )
        for k in ("aliases", "redirect_from", "permalink_raw"):
            extra.pop(k, None)
        zfm = {"title": str(fm.get("title") or "")}
        date = zola_date(fm, src)
        if date:
            zfm["date"] = date
        if kept:
            zfm["aliases"] = kept
        if tags:
            zfm["taxonomies"] = {"tags": tags}

        hand = TEMPLATE_PAGES.get(src)
        if is_template and hand in (None, "generated"):
            # Jekyll ran no Markdown over these (.html, or pure-HTML .md), so
            # they become templates and CommonMark never sees them.
            for pat, repl in LIQUID_FIXES.get(src, []):
                body, n = re.subn(pat, repl, body, flags=re.S)
                if not n:
                    raise SystemExit(f"{src}: Liquid fix no longer matches: {pat[:50]}")
            name = "home" if src == "index.md" else url.strip("/").replace("/", "__")
            (GENERATED / f"{name}.html").write_text(
                f'{{% extends "layouts/{extra["layout"]}.html" %}}\n'
                f"{{% block content %}}{body}{{% endblock content %}}\n"
            )
            hand = f"generated/{name}.html"
        zfm["template"] = hand or f"{extra['layout']}.html"
        if fm.get("redirect_to"):
            zfm["template"] = "redirect.html"
        if src == "index.md":
            target = CONTENT / "_index.md"
            zfm["sort_by"] = "none"
            zfm.pop("date", None)
            zfm.pop("taxonomies", None)
        else:
            target = CONTENT / ((url.strip("/").replace("/", "__") or "root") + ".md")
            zfm["path"] = url
        zfm["extra"] = jsonable(extra)
        text = "" if is_template else body
        target.write_text(
            "---\n"
            + yaml.safe_dump(zfm, allow_unicode=True, sort_keys=False)
            + "---\n"
            + text
        )
        notes.pop("base", None)
        report["pages"][src] = {"url": url, **notes}

    # jekyll-redirect-from's /redirects.json: every redirect, source -> target
    # (Jekyll URL shape, as the old site published it).
    redirects = {}
    for a, owner in alias_owner.items():
        if re.sub(r"\.html$", "", a) not in doc_urls:
            redirects[a] = "https://idvork.in" + urls[owner]
    for src_, (fm_, _) in parsed.items():
        if fm_.get("redirect_to"):
            t = str(fm_["redirect_to"])
            redirects[urls[src_]] = (
                t if t.startswith("http") else "https://idvork.in" + t
            )
    (HERE / "static" / "redirects.json").write_text(json.dumps(redirects))
    report["redirects"] = len(redirects)
    # /tags lists every tag a collection document uses, sorted like Liquid's
    # `sort` (case-sensitive), with its document count.
    (HERE / "data" / "tags.json").write_text(
        json.dumps([{"tag": t, "count": len(tag_docs[t])} for t in sorted(tag_docs)])
    )
    json.dump(report, sys.stdout, indent=1, default=str)
    print()
    if report["errors"]:
        sys.exit(
            f"{len(report['errors'])} pages failed to convert: {list(report['errors'])[:5]}"
        )


if __name__ == "__main__":
    main()
