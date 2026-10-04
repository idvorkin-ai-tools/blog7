# Zola port of idvork.in (bead blog-pzp)

A full port of the Jekyll site to Zola **0.23.6** (pinned), built on the
blog-pss spike. Jekyll stays the source of truth and the fallback: nothing in
`_d/`, `_posts/`, `_td/`, `_ig66/` or `_includes/` is edited. `build.sh`
generates the Zola site from those sources on every build.

```bash
zola/build.sh                                   # -> zola/public, base_url https://idvork.in
OUT=public-preview BASE_URL=https://host:port zola/build.sh   # preview build
```

`ZOLA` defaults to `~/tmp/agent/skill/zola/zola` (the 0.23.6 release binary).

## Pipeline

1. `stage_static.py` hard-links every file Jekyll copies verbatim into
   `static/` (Jekyll 3.9 reader rules: `_`/`.` names, `exclude:` with its
   prefix match, front-matter files are pages). Collections contribute their
   front-matter-less files under `/<collection>/`.
2. `_data/*` is copied to `data/` (Zola refuses `load_data` outside the site),
   and `data/git.json` is written for the dev banner (Jekyll's
   `_plugins/git_data_generator.rb` did this).
3. `port_includes.py` writes `templates/components/`: mechanical Liquid → Tera 2
   for the simple includes, targeted replacements for the orchestrator ones,
   then `flatten()` so CommonMark keeps each component one HTML block. The
   remaining components are hand ports (in git).
4. `convert.py` writes `content/` (and `templates/generated/` for pages Jekyll
   never ran Markdown over): front matter, includes → `{{<component />}}`
   calls, pinned kramdown heading ids, relative links resolved against the
   Jekyll URL, kramdown-only syntax. Unknown Liquid fails the build.
5. `zola build`.

Listing pages that loop over `site.*` are hand-ported templates in
`templates/pages/`; RSS and the search JSON files are `feed_filenames`
templates in `templates/`.

## Preview and diff

```bash
RUBYOPT="-r$(pwd)/_ruby_compat.rb" bundle exec jekyll build && just update-backlinks   # baseline
PREVIEW_URL=https://<host>.ts.net:<port> zola/preview.sh     # -> zola/public-preview
python3 zola/serve.py zola/public-preview <local-port>        # Pages-like: /x -> /x/, 404.html
```

`preview.sh` builds twice (idvork.in base for the diff, preview base for
serving), runs `diff_sites.py` (every Jekyll URL, page text, heading ids,
broken links/anchors in both builds) and renders it with `report.py` at
`/_port/`. `sweep.cjs` is the optional Playwright pass (heights, JS errors)
whose JSON `preview.sh` folds in via `SWEEP=`.

## Known differences from Jekyll

The report page (`/_port/`) lists them with counts. In short:

- URLs end in `/` (`/magic/` served from `/magic/index.html`); `/magic`
  redirects there. Heading ids are pinned to kramdown's, so `#fragments`
  survive.
- Redirect stubs are Zola aliases, which also carry the `#hash` along.
- Smart-quote direction, footnote markers/ids, TOC lines that nest a link,
  and rouge highlighting spans differ (pulldown-cmark vs kramdown).
- `links.jsonp` is dropped (nothing loads it). `sitemap.xml` is Zola's own
  (every page; Jekyll's listed redirect stubs and skipped `_d`/`_td`).
- Undated `_d`/`_td` documents carry no date (Jekyll stamped the build time).
- `back-links.json` still comes from `build_back_links.py` over the Jekyll
  `_site`; `src/main.ts` trims the `/x/` slash before looking a page up.
