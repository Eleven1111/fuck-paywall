'use strict';
// Runs the WSJ userscript against a fake paywalled page and a fake AMP response,
// with the jQuery version it @requires (and the old jquery-latest 1.11.1 as a control).
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
const { REPO, createReporter } = require('./lib');

const DIR = path.join(REPO, 'The Wall Street Journal Full Text Articles');
const AMP = `<!doctype html><html amp><head><script async src="x.js"></script></head><body><main><article>
<div amp-access="access"><p>FULL TEXT PARAGRAPH 1</p><p>FULL TEXT PARAGRAPH 2</p><amp-img src="a.jpg?width=100"></amp-img></div>
</article></main></body></html>`;

async function runScript(browser, jquerySource, userscript) {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.setContent('<div class="wsj-snippet-body"><p>teaser only</p></div><div class="wsj-snippet-login">Subscribe</div>');
  await page.addScriptTag({ content: jquerySource });
  await page.evaluate(({ amp, us }) => {
    window.GM_xmlhttpRequest = (params) => { window.__url = params.url; setTimeout(() => params.onload({ responseText: amp }), 10); };
    (0, eval)(us);
  }, { amp: AMP, us: userscript });
  await page.waitForTimeout(500);
  const result = {
    version: await page.evaluate(() => jQuery.fn.jquery),
    url: await page.evaluate(() => window.__url),
    body: (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ').trim(),
    errors,
  };
  await page.close();
  return result;
}

(async () => {
  const { check, finish } = createReporter('WSJ userscript');
  const browser = await chromium.launch();
  try {
    for (const file of ['The Wall Street Journal Full Text Articles.user.js', 'The Wall Street Journal Full Text Articles.txt']) {
      const us = fs.readFileSync(path.join(DIR, file), 'utf8');
      const m = us.match(/@require\s+https:\/\/code\.jquery\.com\/jquery-(\d+\.\d+\.\d+)\.min\.js/);
      check(`${file}: @require pins an exact jQuery version`, !!m, us.match(/@require.*/) && us.match(/@require.*/)[0]);
      if (!m) continue;
      const pinned = require('jquery/package.json').version;
      check(`${file}: pinned jQuery (${m[1]}) matches the tested version (${pinned})`, m[1] === pinned);

      const jq = fs.readFileSync(require.resolve('jquery/dist/jquery.min.js'), 'utf8');
      const r = await runScript(browser, jq, us);
      check(`${file}: replaces the teaser with the AMP full text (jQuery ${r.version})`,
        r.body === 'FULL TEXT PARAGRAPH 1 FULL TEXT PARAGRAPH 2' && r.url.startsWith('/amp') && !r.errors.length, JSON.stringify(r));

      const jqOld = fs.readFileSync(require.resolve('jquery-1.11.1/dist/jquery.min.js'), 'utf8');
      const old = await runScript(browser, jqOld, us);
      check(`${file}: same result as with the old jquery-latest (${old.version})`, old.body === r.body, JSON.stringify(old));
    }
  } catch (e) {
    check('test run completed without exceptions', false, e.stack);
  } finally {
    await browser.close();
    finish();
  }
})();
