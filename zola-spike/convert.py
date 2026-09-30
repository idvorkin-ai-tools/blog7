#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pyyaml", "typer"]
# ///
"""Convert Jekyll posts to Zola content for the spike (bead blog-pss).

usage: convert.py [--pin-ids] <post.md>...

- Front matter: permalink -> path, redirect_from -> aliases, tags -> taxonomies,
  the rest of the keys the layout reads -> [extra].
- {% include x.html k="v" %} -> {{ x(k="v") }} (hyphens -> underscores).
- <details markdown="1"> -> <details> (CommonMark parses markdown between
  blank lines inside an HTML block anyway).
- --pin-ids appends {#kramdown-slug} to every heading so Zola keeps the ids
  kramdown generated (toc.py's slug rule), instead of using its own slugify.

Everything else Liquid fails the conversion, so nothing is silently dropped.
"""

import datetime
import json
import re
import sys
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / ".claude/skills/toc"))
from toc import slugify  # noqa: E402  kramdown/GFM slug rule shared with the TOCs

FM = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)
INCLUDE = re.compile(r"\{%-?\s*include\s+([\w.-]+)\.html\s*(.*?)\s*-?%\}", re.S)
ARG = re.compile(r"""(\w+)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))""", re.S)
EXTRA_KEYS = [
    "ogtitle",
    "imagefeature",
    "imagefeatureblob",
    "imagefeaturelocal",
    "ai_default_image",
    "mathjax",
    "mermaid",
    "no-render-title",
    "fj",
    "search_exclude",
]


def tera_str(v: str) -> str:
    """Tera string literals have no escapes: pick a delimiter the value lacks."""
    for q in ('"', "'", "`"):
        if q not in v:
            return f"{q}{v}{q}"
    raise ValueError(f"value contains all three quote kinds: {v[:60]}")


def include_to_shortcode(m: re.Match) -> str:
    name = m.group(1).replace("-", "_")
    args = []
    for k, dq, sq, bare in ARG.findall(m.group(2)):
        val = dq if dq or (not sq and not bare) else (sq or bare)
        args.append(f"{k}={tera_str(val)}")
    return "{{<" + " ".join([name, *args]) + " />}}"


def pin_heading_ids(body: str) -> str:
    seen: dict[str, int] = {}
    out, fence = [], False
    for line in body.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        m = None if fence else re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m and not re.search(r"\{#[^}]*\}\s*$", m.group(2)):
            line = f"{m.group(1)} {m.group(2)} {{#{slugify(m.group(2), seen)}}}"
        out.append(line)
    return "\n".join(out)


def convert(src: Path, pin_ids: bool) -> tuple[str, str, dict]:
    fm_raw, body = FM.match(src.read_text()).groups()
    fm = yaml.safe_load(fm_raw) or {}
    notes = {"includes": len(INCLUDE.findall(body))}
    stem = src.stem
    dm = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})-(.*)", stem)
    path = str(fm.get("permalink") or "/" + (dm.group(4) if dm else stem))
    path = "/" + path.strip("/")

    body = re.sub(
        r"\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}", "", body, flags=re.S
    )
    body = INCLUDE.sub(include_to_shortcode, body)
    notes["details_md"] = body.count('markdown="1"')
    body = re.sub(r'\s+markdown="1"', "", body)
    notes["ial"] = re.findall(r"^\{:.*\}\s*$", body, flags=re.M)
    leftover = re.findall(r"\{%.*?%\}|\{\{(?!<).*?\}\}|\{#", body, flags=re.S)
    if leftover:
        sys.exit(f"{src}: unconverted liquid {leftover[:3]}")
    empty = re.findall(r"\]\(\s*\)", body)
    if empty:
        sys.exit(f"{src}: {len(empty)} empty link URLs, zola hard-fails on these")
    if pin_ids:
        body = pin_heading_ids(body)

    lines = [
        f"title = {json.dumps(str(fm.get('title') or stem))}",
        f"path = {json.dumps(path)}",
    ]
    date = fm.get("date")
    if isinstance(date, str):
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", date)
        date = datetime.date(*map(int, m.groups())) if m else None
    if not date and dm:
        date = datetime.date(*map(int, dm.groups()[:3]))
    if isinstance(date, (datetime.date, datetime.datetime)):
        lines.append(f"date = {date.isoformat()[:10]}")
    redirs = fm.get("redirect_from") or []
    redirs = [redirs] if isinstance(redirs, str) else redirs
    if redirs:
        lines.append(
            "aliases = ["
            + ", ".join(json.dumps("/" + str(r).strip("/")) for r in redirs)
            + "]"
        )
    notes["aliases"] = len(redirs)
    tags = fm.get("tags") or []
    tags = tags.split() if isinstance(tags, str) else tags
    if tags:
        lines.append(
            "[taxonomies]\ntags = [" + ", ".join(json.dumps(str(t)) for t in tags) + "]"
        )
    extra = [
        f"source_path = {json.dumps(str(src.relative_to(REPO)))}",
        f"permalink = {json.dumps(path)}",
    ]
    if fm.get("date"):
        extra.append(f"jekyll_date = {json.dumps(str(fm['date']))}")
    for k in EXTRA_KEYS:
        if k in fm:
            extra.append(f"{k.replace('-', '_')} = {json.dumps(fm[k])}")
    lines.append("[extra]\n" + "\n".join(extra))
    name = path.strip("/").replace("/", "-") + ".md"
    return name, "+++\n" + "\n".join(lines) + "\n+++\n" + body, notes


def main():
    args = sys.argv[1:]
    pin = "--pin-ids" in args
    files = [a for a in args if a != "--pin-ids"]
    content = HERE / "content"
    content.mkdir(exist_ok=True)
    for old in content.glob("*.md"):
        old.unlink()
    (content / "_index.md").write_text('+++\ntitle = "spike"\nsort_by = "none"\n+++\n')
    report = {}
    for f in files:
        name, text, notes = convert(REPO / f, pin)
        (content / name).write_text(text)
        report[f] = notes
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
