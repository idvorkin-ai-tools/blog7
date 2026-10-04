#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["beautifulsoup4", "lxml"]
# ///
"""Diff the spike's Zola output against the Jekyll _site for the same posts.

usage: diff_sites.py <jekyll _site> <zola public> [<zola public unpinned>]

Compares #content-holder only (layout chrome is out of scope): visible text,
heading ids, internal links, images, plus alias/redirect coverage.
"""

import difflib
import json
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent


def load(p: Path):
    soup = BeautifulSoup(p.read_text(), "lxml")
    return soup.select_one("#content-holder")


def text_of(node) -> list[str]:
    node = BeautifulSoup(str(node), "lxml")
    for t in node(["script", "style", "noscript"]):
        t.decompose()
    return node.get_text(" ").split()


def headings(node):
    return [
        (h.name, h.get("id"), " ".join(h.get_text(" ").split()))
        for h in node.find_all(re.compile("^h[1-6]$"))
    ]


def ids_in(node):
    return {e.get("id") for e in node.find_all(id=True)} | {
        e.get("name") for e in node.find_all("a", attrs={"name": True})
    }


def same_page(h: str, path: str) -> str | None:
    """Fragment if h targets this page (Zola writes #x as https://idvork.in/page/#x)."""
    n = norm_link(h)
    if n.startswith("#"):
        return n[1:]
    p, _, frag = n.partition("#")
    return frag if frag and p == path else None


def links(node):
    out = []
    for a in node.find_all("a", href=True):
        h = a["href"]
        if h.startswith(("/", "#")) or "idvork.in" in h:
            out.append(h)
    return out


def norm_link(h: str) -> str:
    # Zola writes /x/ for what Jekyll serves as /x; compare on the Jekyll shape.
    h = re.sub(r"^https?://idvork\.in", "", h)
    path, _, frag = h.partition("#")
    if path not in ("", "/"):
        path = path.rstrip("/")
    return path + ("#" + frag if frag else "")


def imgs(node):
    return [i.get("src") for i in node.find_all("img")]


def word_diff(a: list[str], b: list[str], limit=6):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ops = [
        (op, " ".join(a[i1:i2])[:140], " ".join(b[j1:j2])[:140])
        for op, i1, i2, j1, j2 in sm.get_opcodes()
        if op != "equal"
    ]
    return round(sm.ratio(), 4), len(ops), ops[:limit]


def main():
    site, pub = Path(sys.argv[1]), Path(sys.argv[2])
    unpinned = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    report, totals = (
        {},
        {
            "heads": 0,
            "pinned_kept": 0,
            "unpinned_kept": 0,
            "tocpinned_broken": 0,
            "tocunpinned_broken": 0,
            "toclinks": 0,
        },
    )
    for md in sorted((HERE / "content").glob("*.md")):
        if md.name == "_index.md":
            continue
        fm = md.read_text().split("+++")[1]
        path = re.search(r'^path = "(.*)"', fm, re.M).group(1)
        aliases = re.findall(
            r'"(/[^"]*)"',
            (re.search(r"^aliases = \[(.*)\]", fm, re.M) or [None, ""])[1],
        )
        j = load(site / (path.strip("/") + ".html"))
        z = load(pub / path.strip("/") / "index.html")
        r = {}
        r["text_ratio"], r["text_diff_ops"], r["text_diff_sample"] = word_diff(
            text_of(j), text_of(z)
        )
        r["words"] = [len(text_of(j)), len(text_of(z))]
        jh, zh = headings(j), headings(z)
        r["headings"] = [len(jh), len(zh)]
        pairs = list(zip(jh, zh))
        r["ids_kept_pinned"] = sum(1 for a, b in pairs if a[1] == b[1])
        r["ids_changed_pinned"] = [(a[1], b[1]) for a, b in pairs if a[1] != b[1]][:8]
        if unpinned:
            u = load(unpinned / path.strip("/") / "index.html")
            uh = headings(u)
            r["ids_kept_unpinned"] = sum(1 for a, b in zip(jh, uh) if a[1] == b[1])
            r["ids_changed_unpinned_sample"] = [
                (a[1], b[1]) for a, b in zip(jh, uh) if a[1] != b[1]
            ][:5]
            uid = ids_in(u)
            toc = [f for f in (same_page(h, path) for h in links(u)) if f]
            r["same_page_anchor_links"] = len(toc)
            r["broken_same_page_unpinned"] = sum(1 for f in toc if f not in uid)
            totals["unpinned_kept"] += r["ids_kept_unpinned"]
            totals["tocunpinned_broken"] += r["broken_same_page_unpinned"]
        zid = ids_in(z)
        toc = [f for f in (same_page(h, path) for h in links(z)) if f]
        r["broken_same_page_pinned"] = sorted({f for f in toc if f not in zid})

        def canon(h):
            f = same_page(h, path)
            return "#" + f if f is not None else norm_link(h)

        jl, zl = [canon(h) for h in links(j)], [canon(h) for h in links(z)]
        r["links"] = [len(jl), len(zl)]
        r["links_only_jekyll"] = sorted(set(jl) - set(zl))[:8]
        r["links_only_zola"] = sorted(set(zl) - set(jl))[:8]
        ji, zi = imgs(j), imgs(z)
        r["imgs"] = [len(ji), len(zi)]
        r["imgs_only_jekyll"] = sorted(set(ji) - set(zi))
        r["imgs_only_zola"] = sorted(set(zi) - set(ji))
        r["aliases_missing"] = [
            a for a in aliases if not (pub / a.strip("/") / "index.html").exists()
        ]
        r["jekyll_redirects_without_alias"] = [
            a for a in aliases if not (site / (a.strip("/") + ".html")).exists()
        ]
        totals["heads"] += len(jh)
        totals["pinned_kept"] += r["ids_kept_pinned"]
        totals["toclinks"] += len(toc)
        totals["tocpinned_broken"] += len(r["broken_same_page_pinned"])
        report[path] = r
    print(json.dumps({"totals": totals, "pages": report}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
