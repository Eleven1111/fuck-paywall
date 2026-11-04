'use strict';
// Loads 媒体付费墙杀手 (MV3) into Chromium and checks its behaviour against the fake sites.
const { createReporter, copyExtension, launchWithExtension, extensionInfo, server } = require('./lib');

(async () => {
  const { check, finish } = createReporter('媒体付费墙杀手');
  const { ctx, sw, id } = await launchWithExtension(copyExtension('媒体付费墙杀手/3.0.2_0'));
  const setting = (type, url) => sw.evaluate(([t, u]) =>
    new Promise((r) => chrome.contentSettings[t].get({ primaryUrl: u }, (d) => r(d.setting))), [type, url]);
  try {
    const info = await extensionInfo(ctx);
    const mv = await sw.evaluate(() => chrome.runtime.getManifest().manifest_version);
    check('loads as an enabled MV3 extension', info.state === 'ENABLED' && mv === 3, JSON.stringify(info) + ' mv=' + mv);

    // Default block list applies on install, without opening the popup
    const d = {
      ecoJs: await setting('javascript', 'https://www.economist.com/'),
      ecoCk: await setting('cookies', 'https://www.economist.com/'),
      hbrJs: await setting('javascript', 'https://hbr.org/'),
      nytJs: await setting('javascript', 'https://www.nytimes.com/'),
      nytCk: await setting('cookies', 'https://www.nytimes.com/'),
      exJs: await setting('javascript', 'https://example.org/'),
      exCk: await setting('cookies', 'https://example.org/'),
    };
    check('default list on install: economist/hbr (power) block JS and cookies', d.ecoJs === 'block' && d.ecoCk === 'block' && d.hbrJs === 'block', JSON.stringify(d));
    check('default list on install: nytimes (regular) blocks cookies only', d.nytJs === 'allow' && d.nytCk === 'block', JSON.stringify(d));
    check('control example.org: JS and cookies allowed', d.exJs === 'allow' && d.exCk === 'allow', JSON.stringify(d));

    await server.reset();
    const p0 = await ctx.newPage();
    await p0.goto('https://www.economist.com/page');
    await p0.waitForTimeout(800);
    await p0.close();
    let log = await server.log();
    check('economist page scripts do not run', !log.some((l) => l.host === 'www.economist.com' && l.url.startsWith('/beacon')), JSON.stringify(log));

    const fences = await sw.evaluate(() => new Promise((r) => chrome.storage.sync.get('fences', (i) => r(i.fences))));
    check('default block list is loaded via fetch and stored', Array.isArray(fences) && fences.length === 7, JSON.stringify(fences));

    await ctx.addCookies([
      { name: 'meter', value: '3', domain: 'www.economist.com', path: '/' },
      { name: 'keep', value: '1', domain: 'example.org', path: '/' },
    ]);
    const page = await ctx.newPage();
    await page.goto('https://www.economist.com/page');
    await page.waitForTimeout(1200);
    const eco = await ctx.cookies('https://www.economist.com/');
    check('economist: cookies cleared when the page loads', eco.length === 0, JSON.stringify(eco));
    await page.goto('https://example.org/page');
    await page.waitForTimeout(800);
    check('control example.org: cookies kept', (await ctx.cookies('https://example.org/')).length === 1);

    const popup = await ctx.newPage();
    const popupErrors = [];
    popup.on('pageerror', (e) => popupErrors.push(e.message));
    await popup.goto(`chrome-extension://${id}/Popup/Popup.html`);
    await popup.waitForTimeout(800);
    const labels = await popup.locator('label').allInnerTexts();
    check('popup renders localized labels', labels.length === 4 && !labels.includes('PLACE_HOLDER') && !popupErrors.length, JSON.stringify(labels) + JSON.stringify(popupErrors));
    await popup.close();

    // Drive the background the same way the popup does, with a news tab active
    await page.goto('https://www.nytimes.com/page');
    await ctx.addCookies([{ name: 'n', value: '1', domain: 'www.nytimes.com', path: '/' }]);
    const ext = await ctx.newPage();
    await ext.goto(`chrome-extension://${id}/Popup/Popup.html`);
    await page.bringToFront();
    await page.waitForTimeout(500);
    const policy = await ext.evaluate(() => new Promise((res) => {
      chrome.runtime.onMessage.addListener((m) => { if (m.policy) res(m.policy); });
      chrome.runtime.sendMessage({ query: true });
      setTimeout(() => res('timeout'), 3000);
    }));
    check('query returns the current site policy (nytimes: regular)', policy === 'regular', policy);

    await server.reset();
    await ext.evaluate(() => chrome.runtime.sendMessage({ newPolicy: 'power' }));
    await page.waitForTimeout(2000);
    const js = await setting('javascript', 'https://www.nytimes.com/');
    const ck = await setting('cookies', 'https://www.nytimes.com/');
    check('switch to power: nytimes JS and cookies blocked', js === 'block' && ck === 'block', `js=${js} cookies=${ck}`);
    log = await server.log();
    check('switch to power: site tab is reloaded', log.some((l) => l.host === 'www.nytimes.com' && l.url === '/page'), JSON.stringify(log));
    check('switch to power: page scripts no longer run', !log.some((l) => l.url.startsWith('/beacon')), JSON.stringify(log));
    check('switch to power: cookies cleared', (await ctx.cookies('https://www.nytimes.com/')).length === 0);

    await ext.evaluate(() => chrome.runtime.sendMessage({ newPolicy: 'none' }));
    await page.waitForTimeout(2000);
    const js2 = await setting('javascript', 'https://www.nytimes.com/');
    check('switch to none: JS allowed again', js2 === 'allow', js2);

    const after = await extensionInfo(ctx);
    check('no runtime errors', after.runtimeErrors.length === 0, JSON.stringify(after.runtimeErrors));
  } catch (e) {
    check('test run completed without exceptions', false, e.stack);
  } finally {
    await ctx.close();
    finish();
  }
})();
