# Zola spike (bead blog-pss) — throwaway

15 representative posts ported to Zola 0.23.6 and diffed against the Jekyll `_site`.
Results are in the blog-pss bead comment and `diff-report.json`.

```bash
bundle exec jekyll build   # (with the _ruby_compat.rb RUBYOPT) — the baseline _site
OUT=/tmp/zola-unpinned ./build.sh   # Zola's own heading slugs
./build.sh --pin-ids                # kramdown slugs pinned as {#id}
./diff_sites.py ../_site public /tmp/zola-unpinned > diff-report.json
```

- `convert.py` — front matter + `{% include %}` → Tera 2 component calls (`{{<name k="v" />}}`).
- `port_includes.py` — mechanical Liquid → component port for simple includes, then
  flattens every component (CommonMark ends an HTML block at a blank line).
- `templates/` — minimal port of `post.html` + head/menu/scripts/annotate.
