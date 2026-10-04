// Browser sweep for the Zola port (bead blog-pzp): every page on both sites,
// rendered height, JS errors, failed same-origin requests, links-to-page
// count. 4 pages at a time; the JSON is rewritten every 25 pages.
//
//   OUT=sweep.json URLS=urls.json ZOLA=https://preview JEKYLL=http://127.0.0.1:4472 node zola/sweep.cjs
// (JEKYLL: serve the Jekyll _site with `zola/serve.py _site 4472 --jekyll`.)
const { chromium } = require("playwright");
const fs = require("node:fs");
const { OUT, ZOLA: Z, JEKYLL: J } = process.env;
const urls = JSON.parse(fs.readFileSync(process.env.URLS, "utf8"));
(async () => {
  const browser = await chromium.launch();
  const report = {};
  const jobs = [];
  for (const u of urls)
    for (const [site, base] of [
      ["jekyll", J],
      ["zola", Z],
    ])
      jobs.push([u, site, base]);
  let i = 0;
  let done = 0;
  async function worker() {
    while (i < jobs.length) {
      const [u, site, base] = jobs[i++];
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      const page = await ctx.newPage();
      const errs = [];
      page.on("pageerror", (e) => errs.push(`pageerror: ${String(e).slice(0, 160)}`));
      page.on("console", (m) => {
        const t = m.text();
        if (m.type() === "error" && !/cursor-party|Socket error|recent-posts container|identify|status of 401/.test(t))
          errs.push(`console: ${t.slice(0, 160)}`);
      });
      page.on("response", (r) => {
        if (r.status() >= 400 && r.url().startsWith(base))
          errs.push(`http ${r.status()}: ${r.url().slice(base.length)}`);
      });
      try {
        await page.goto(base + u, { waitUntil: "load", timeout: 20000 });
        await page.waitForTimeout(1500);
        const info = await page.evaluate(() => ({
          h: document.body.scrollHeight,
          links: document.querySelectorAll("#links-to-page a").length,
          imgs: [...document.images].filter((x) => x.complete && x.naturalWidth > 0).length,
        }));
        report[u] = report[u] || {};
        report[u][site] = { errs, ...info };
        if (++done % 25 === 0) fs.writeFileSync(OUT, JSON.stringify(report));
      } catch (e) {
        report[u] = report[u] || {};
        report[u][site] = { errs: [...errs, `goto: ${String(e).slice(0, 100)}`] };
      }
      await ctx.close();
    }
  }
  await Promise.all([worker(), worker(), worker(), worker()]);
  fs.writeFileSync(OUT, JSON.stringify(report));
  await browser.close();
})();
