#!/usr/bin/env python3
"""Render the full-site diff (diff_sites.py JSON) as one HTML page.

usage: report.py <diff-report.json> <convert-report.json> <preview base URL> [sweep.json]

sweep.json (optional) is the browser sweep: per Jekyll URL, rendered height,
JS errors and links-to-page count on each site.
"""

import html
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
diff = json.loads(Path(sys.argv[1]).read_text())
conv = json.loads(Path(sys.argv[2]).read_text())
base = sys.argv[3].rstrip("/")
sweep = (
    json.loads(Path(sys.argv[4]).read_text())
    if len(sys.argv) > 4 and Path(sys.argv[4]).exists()
    else {}
)
S = diff["summary"]
e = html.escape

# Curated findings: what the numbers below mean, from reading the diffs and
# side-by-side screenshots (kept here so the page says it next to the data).
GAPS = [
    (
        "Smart quotes",
        "About 40 pages differ only in quote direction: pulldown-cmark curls '24 and 'em as ’24 and ’em "
        "where kramdown wrote ‘24 and ‘em, and a quote after an ellipsis or digit can flip. Text only; "
        "pulldown-cmark is usually the right one.",
    ),
    (
        "Footnotes",
        "Markers render as [1] instead of a bare superscript 1, and the ids change from kramdown's "
        "#fn:1 / #fnref:1 to #fn-1 / #fr-1-1, so an outside link to a footnote would miss (2 pages: /wally, /ai-relationships).",
    ),
    (
        "TOC entries that wrap a link",
        "A TOC line like [[Jump in the lake day](url)](#jump-in-the-lake-day) nests a link in a link. "
        "kramdown kept the inner link, CommonMark keeps the outer one (/resistance, /irl, /depression, "
        "/y26). The anchors still resolve.",
    ),
    (
        "Code blocks lose rouge's highlighting spans",
        'Zola writes <pre><code data-lang="x">; scripts.html adds class="language-x" back before '
        "highlight.js runs, so hljs colors the code and mermaid finds its blocks as before. Rouge's "
        "server-side token spans are gone; the site CSS barely styled them.",
    ),
    (
        "List spacing",
        "kramdown gives <p> only to the list items followed by a blank line; CommonMark makes the whole "
        "list loose. convert.py drops the blank lines kramdown treated as tight, which cut the extra "
        "paragraph margins from ~450 items to ~100 (plus ~40 now tighter than Jekyll) on about 40 "
        "pages, mostly lists whose first item holds a quote or code block. Spacing only.",
    ),
    (
        "One-page oddities",
        "A list item followed by a bare '-' was a setext heading to kramdown "
        "(/d/2016-8-1-Twelve-Tech-Forces); a ```sudo fence on /mosh drops its first line as the info "
        "string; <vapi-widget> on /tesla is an element in Zola but was text in Jekyll; $$ math is left "
        "as $$ (MathJax reads both); empty list items '-' render empty.",
    ),
    (
        "Jekyll bugs the port does not copy",
        "Inline summarize-page includes rendered as raw markup text on Jekyll (/siy, /happy, /untangled, "
        "/idle, /content-creation); Zola renders the summary link. /weeks threw a JS SyntaxError on "
        "Jekyll (a Ruby hash dumped into a script); Zola's does not. /all no longer stamps undated "
        "documents with the build date.",
    ),
    (
        "Trailing-slash URLs",
        "Every page moves from /x to /x/; Pages answers /x with a 301 to /x/ and keeps the #fragment. "
        "Canonical and og:url carry the slash. Heading ids are pinned to kramdown's, so deep links "
        "survive; the 13 ids not kept are blank tag headings on /tags and two odd headings.",
    ),
]
LEFT = [
    "Pages workflow: swap the Jekyll build step for zola/build.sh (pin Zola 0.23.6 in CI), keep Pagefind "
    "and scripts/verify-search-index.sh (it already passes on the Zola build).",
    "build_back_links.py reads Jekyll's _site/x.html: point it at zola/public (x/index.html) so "
    "back-links.json no longer needs a Jekyll build.",
    "Decide where content lives: today convert.py generates zola/content at build time from _d/ etc. "
    "Cutover either commits the converted tree (and retires Liquid includes for {{<components/>}}) or "
    "keeps the converter as the CI build step.",
    "Tooling that assumes Jekyll: justfile recipes (jekyll-serve, update-backlinks), running-servers "
    "--process jekyll, the anchor-checker and check-links pre-commit hooks, toc.py, the dev banner's "
    "git.json (now written by build.sh), .claude skills, the e2e tests, and the _ruby_compat shim.",
    "Fix or accept the handful of source quirks listed above (tables, spaced URLs, nested TOC links).",
    "Igor's eyeball pass on the preview, then flip Pages; Jekyll stays the fallback until then.",
]


def sha():
    try:
        return subprocess.check_output(
            ["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "?"


def card(label, value, sub="", tone=""):
    return f'<div class="card {tone}"><div class="v">{value}</div><div class="l">{e(label)}</div><div class="s">{sub}</div></div>'


inv = Counter(x["status"] for x in diff["inventory"])
GENERATED = {
    "/feed.xml",
    "/sitemap.xml",
    "/search.json",
    "/search-titles.json",
    "/redirects.json",
}
gen_diff = [
    x["url"].lstrip("/")
    for x in diff["inventory"]
    if x["status"] == "static-differs" and x["url"] in GENERATED
]
other_diff = [
    x["url"]
    for x in diff["inventory"]
    if x["status"] == "static-differs" and x["url"] not in GENERATED
]
missing_static = [
    x["url"] for x in diff["inventory"] if x["status"] == "static-missing"
]
jp, zp = S["jekyll"]["pages"], inv.get("page", 0)
ids_kept = S["heading_ids_jekyll"] - S["heading_ids_lost"]
bz, bj = S["broken_zola_only"], S["broken_jekyll"]
pairs = diff["pairs"]
sw_err_z = sum(
    1
    for u, v in sweep.items()
    if len(v.get("zola", {}).get("errs", [])) > len(v.get("jekyll", {}).get("errs", []))
)
sw_h = [
    (u, v["jekyll"].get("h"), v["zola"].get("h"))
    for u, v in sweep.items()
    if v.get("jekyll", {}).get("h") and v.get("zola", {}).get("h")
]
sw_h_off = [x for x in sw_h if abs(x[2] - x[1]) / max(x[1], 1) > 0.05]

cards = "".join(
    [
        card(
            "pages ported",
            f"{zp}/{jp}",
            "every Jekyll page has a Zola page",
            "good" if zp == jp else "bad",
        ),
        card(
            "redirects kept",
            f"{inv.get('redirect', 0)}/{S['jekyll']['redirects']}",
            "redirect_from → aliases, same targets",
        ),
        card(
            "static files",
            f"{inv.get('static', 0)}/{S['jekyll']['static']}",
            "byte-identical; "
            + (
                f"generated ({', '.join(gen_diff)}) compared below"
                + (f"; also differ: {', '.join(other_diff)}" if other_diff else "")
                + (f"; dropped: {', '.join(missing_static)}" if missing_static else "")
            ),
        ),
        card(
            "text identical",
            f"{S['identical_text']}",
            f"{S['ratio_ge_0995']} at ≥99.5% · {S['ratio_lt_095']} below 95%",
        ),
        card(
            "heading ids kept",
            f"{ids_kept}/{S['heading_ids_jekyll']}",
            "deep links #fragment survive",
        ),
        card(
            "broken links, port-made",
            f"{bz['missing']} / {bz['anchor']}",
            "missing pages / missing anchors",
            "good" if not (bz["missing"] or bz["anchor"]) else "bad",
        ),
        card(
            "broken links, already on Jekyll",
            f"{bj['missing']} / {bj['anchor']}",
            "same in both builds",
        ),
    ]
    + (
        [
            card(
                "browser sweep",
                f"{len(sweep)} pages",
                f"{sw_err_z} with more JS errors on Zola · {len(sw_h_off)} heights off by &gt;5%",
                "good" if not sw_err_z else "",
            )
        ]
        if sweep
        else []
    )
)

gen_rows = "".join(
    f"<tr><td>{e(k)}</td><td>{v.get('jekyll')}</td><td>{v.get('zola')}</td><td>{e(json.dumps({x: y for x, y in v.items() if x not in ('jekyll', 'zola')})[:400])}</td></tr>"
    for k, v in diff.get("generated", {}).items()
)


def page_row(p):
    u = p["url"]
    zu = base + (u if u.endswith("/") else u + "/")
    sw = sweep.get(u, {})
    sj, sz = sw.get("jekyll", {}), sw.get("zola", {})
    tone = "ok" if p["ratio"] == 1 else ("warn" if p["ratio"] >= 0.995 else "bad")
    diffs = "".join(
        f"<li><b>{e(op)}</b> <span class=j>{e(a)}</span> → <span class=z>{e(b)}</span></li>"
        for op, a, b in p["diffs"]
    )
    errs = "".join(f"<li>{e(x)}</li>" for x in sz.get("errs", []))
    lost = ", ".join(e(i) for i in p["ids_lost"])
    detail = ""
    if diffs or lost or errs:
        detail = f"<details><summary>details</summary><ul>{diffs}</ul>{'<p>ids lost: ' + lost + '</p>' if lost else ''}{'<p>Zola JS errors:</p><ul>' + errs + '</ul>' if errs else ''}</details>"
    return (
        f'<tr class="{tone}" data-ratio="{p["ratio"]}"><td><a href="{e(zu)}">{e(u)}</a> '
        f'<a class=prod href="https://idvork.in{e(u)}" title="live Jekyll page">prod</a><div class=src>{e(p["src"] or "")}</div>{detail}</td>'
        f"<td class=n>{p['ratio']:.4f}</td><td class=n>{p['words'][0]}/{p['words'][1]}</td>"
        f"<td class=n>{p['headings'][0]}/{p['headings'][1]}{' −' + str(p['ids_lost_n']) if p['ids_lost_n'] else ''}</td>"
        f"<td class=n>{p['images'][0]}/{p['images'][1]}</td><td class=n>{p['iframes'][0]}/{p['iframes'][1]}</td>"
        f"<td class=n>{sj.get('h', '')}/{sz.get('h', '')}</td><td class=n>{len(sj.get('errs', []))}/{len(sz.get('errs', []))}</td></tr>"
    )


def inv_row(x):
    u = x["url"]
    st = x["status"]
    tone = "ok" if st in ("page", "redirect", "static") else "bad"
    note = x.get("zola") or x.get("jekyll") or ""
    return f'<tr class="{tone}"><td>{e(u)}</td><td>{e(st)}</td><td>{e(note)}</td></tr>'


def broken_rows(d):
    return "".join(
        f"<tr><td>{e(u)}</td><td>{e(h)}</td><td>{e(w)}</td></tr>"
        for u, items in d.items()
        for h, w in items
    )


notes = conv
fixups = Counter()
for n in notes["pages"].values():
    for k in (
        "joined_img_calls",
        "blank_after_call",
        "inline_calls",
        "indented_calls",
        "raw_html_blocks",
        "blank_after_html",
    ):
        fixups[k] += n.get(k, 0)
    fixups["relative_links"] += len(n.get("relative_links", []))
    fixups["include_calls"] += sum(n.get("includes", {}).values())
    fixups["dropped_args"] += len(n.get("dropped_args", []))

doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zola Port Diff</title>
<style>
:root {{ --bg:#fbfbf9; --fg:#1d1d1b; --mut:#6b6b66; --line:#e4e2dc; --card:#fff; --good:#1f7a4d; --bad:#b3261e; --warn:#8a6100; --acc:#2456a6; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#16171a; --fg:#e8e6e1; --mut:#9a978f; --line:#2c2e33; --card:#1e2024; --good:#5cc08a; --bad:#ff7b72; --warn:#e0b04a; --acc:#7aa7ff; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif }}
main {{ max-width:1180px; margin:0 auto; padding:24px 16px 64px }}
h1 {{ font-size:26px; margin:0 0 4px }} h2 {{ font-size:19px; margin:36px 0 10px; border-bottom:1px solid var(--line); padding-bottom:6px }}
.meta {{ color:var(--mut); font-size:13px }} a {{ color:var(--acc) }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:10px; margin-top:18px }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 14px }}
.card .v {{ font-size:24px; font-weight:650; font-variant-numeric:tabular-nums }} .card .l {{ font-weight:600 }} .card .s {{ color:var(--mut); font-size:12.5px }}
.card.good .v {{ color:var(--good) }} .card.bad .v {{ color:var(--bad) }}
ul.gaps li, ul.left li {{ margin:6px 0 }}
.tw {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:var(--card) }}
table {{ border-collapse:collapse; width:100%; font-size:13px }}
th, td {{ text-align:left; padding:5px 8px; border-bottom:1px solid var(--line); vertical-align:top }}
th {{ position:sticky; top:0; background:var(--card); font-weight:600 }}
td.n {{ font-variant-numeric:tabular-nums; white-space:nowrap }}
tr.bad td:first-child {{ border-left:3px solid var(--bad) }} tr.warn td:first-child {{ border-left:3px solid var(--warn) }} tr.ok td:first-child {{ border-left:3px solid transparent }}
.src {{ color:var(--mut); font-size:11.5px }} a.prod {{ font-size:11px; color:var(--mut) }}
.j {{ color:var(--bad) }} .z {{ color:var(--good) }} details summary {{ cursor:pointer; color:var(--mut); font-size:12px }}
.ctl {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin:8px 0 }}
input[type=search] {{ padding:6px 10px; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--fg); min-width:240px }}
.scroll {{ max-height:520px; overflow:auto }}
</style></head><body><main>
<h1>Zola port of idvork.in: full-site diff</h1>
<div class="meta">Branch zola-port @ {sha()} · Zola 0.23.6 · built {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} · Jekyll baseline: the same commit's <code>jekyll build</code>.
Preview: <a href="{e(base)}/">{e(base)}</a> · raw data: <a href="diff-report.json">diff-report.json</a></div>
<div class="cards">{cards}</div>

<h2>Worst rendering gaps</h2>
<ul class="gaps">{"".join(f"<li><b>{e(t)}.</b> {e(d)}</li>" for t, d in GAPS)}</ul>

<h2>What's left before a cutover</h2>
<ul class="left">{"".join(f"<li>{e(x)}</li>" for x in LEFT)}</ul>

<h2>How the converter changed the source</h2>
<p class="meta">{fixups["include_calls"]} include calls became components ({fixups["dropped_args"]} unknown args dropped, as Liquid ignored them) ·
{fixups["relative_links"]} relative links resolved against the Jekyll URL · {fixups["joined_img_calls"]} float images joined to their paragraph ·
{fixups["blank_after_call"] + fixups["blank_after_html"]} blank lines added after HTML · {fixups["indented_calls"]} indented and {fixups["inline_calls"]} mid-line calls kept in their block ·
{fixups["raw_html_blocks"]} raw HTML blocks kept whole · aliases dropped: {e("; ".join(notes["alias_dropped"]) or "none")} · shadowed by an alias: {e(", ".join(notes.get("shadowed_by_alias", [])) or "none")}</p>

<h2>Generated files</h2>
<div class="tw"><table><tr><th>file</th><th>Jekyll</th><th>Zola</th><th>difference</th></tr>{gen_rows}</table></div>
<p class="meta">sitemap.xml: Jekyll listed redirect stubs and skipped _d/_td; Zola lists every real page. links.jsonp is dropped (nothing loads it).</p>

<h2>Every page ({len(pairs)}), worst first</h2>
<div class="ctl"><input type="search" id="pf" placeholder="filter by URL or source"> <label><input type="checkbox" id="pd"> only pages that differ</label></div>
<div class="tw scroll"><table id="pt"><tr><th>page (Zola preview · prod)</th><th>text ratio</th><th>words J/Z</th><th>heading ids J/Z</th><th>img J/Z</th><th>iframe J/Z</th><th>height J/Z</th><th>JS err J/Z</th></tr>
{"".join(page_row(p) for p in pairs)}</table></div>

<h2>Every Jekyll URL ({len(diff["inventory"])}) and its Zola status</h2>
<div class="ctl"><input type="search" id="if" placeholder="filter URLs or status"></div>
<div class="tw scroll"><table id="it"><tr><th>Jekyll URL</th><th>Zola status</th><th>target / Zola path</th></tr>
{"".join(inv_row(x) for x in diff["inventory"])}</table></div>
<p class="meta">Extra URLs in Zola: {e(", ".join(diff["extra_in_zola"]))}</p>

<h2>Broken internal links and anchors</h2>
<p>Made by the port: <b>{bz["missing"]}</b> missing pages, <b>{bz["anchor"]}</b> missing anchors. Already broken on Jekyll and still broken on Zola: {S["broken_in_both"]}.</p>
<details><summary>Already broken on Jekyll ({bj["missing"]} missing, {bj["anchor"]} anchors)</summary>
<div class="tw scroll"><table><tr><th>page</th><th>href</th><th>problem</th></tr>{broken_rows(diff["broken_jekyll"])}</table></div></details>
{('<div class="tw"><table><tr><th>page</th><th>href</th><th>problem</th></tr>' + broken_rows(diff["broken_zola_only"]) + "</table></div>") if diff["broken_zola_only"] else ""}
</main>
<script>
function wire(inputId, tableId, extra) {{
  const q = document.getElementById(inputId), t = document.getElementById(tableId);
  const run = () => {{ const s = q.value.toLowerCase();
    for (const r of t.rows) {{ if (r.querySelector('th')) continue;
      r.style.display = (r.textContent.toLowerCase().includes(s) && (!extra || extra(r))) ? '' : 'none'; }} }};
  q.addEventListener('input', run); return run;
}}
const d = document.getElementById('pd');
const runP = wire('pf', 'pt', r => !d.checked || r.dataset.ratio !== '1.0');
d.addEventListener('change', runP); wire('if', 'it');
</script>
</body></html>"""
print(doc)
