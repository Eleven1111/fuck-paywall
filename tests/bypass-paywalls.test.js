'use strict';
// Loads bypass-paywalls (MV3) into Chromium and checks its behaviour against the fake sites.
const { createReporter, copyExtension, launchWithExtension, extensionInfo, server } = require('./lib');

(async () => {
  const { check, finish } = createReporter('bypass-paywalls');
  const { ctx, sw, id } = await launchWithExtension(copyExtension('bypass-paywalls/bypass-paywalls-chrome-master'));
  try {
    const info = await extensionInfo(ctx);
    const mv = await sw.evaluate(() => chrome.runtime.getManifest().manifest_version);
    check('loads as an enabled MV3 extension', info.state === 'ENABLED' && mv === 3, JSON.stringify(info) + ' mv=' + mv);
    check('opens the options page on install', ctx.pages().some((p) => p.url().includes('options.html')));

    const rules = await sw.evaluate(() => chrome.declarativeNetRequest.getDynamicRules());
    const scripts = await sw.evaluate(() => chrome.scripting.getRegisteredContentScripts());
    check('creates dynamic declarativeNetRequest rules', rules.length > 50, `${rules.length} rules`);
    check('registers the content script', scripts.length === 1 && scripts[0].matches.length > 50, JSON.stringify(scripts));

    await ctx.addCookies([
      { name: 't', value: '1', domain: 'www.latimes.com', path: '/' },
      { name: 't', value: '1', domain: 'www.nytimes.com', path: '/' },
      { name: 't', value: '1', domain: 'example.org', path: '/' },
    ]);
    const page = await ctx.newPage();
    const visit = async (url) => { await server.reset(); await page.goto(url); await page.waitForTimeout(700); return server.log(); };

    let log = await visit('https://www.latimes.com/page');
    let main = log.find((l) => l.url === '/page');
    check('latimes: Referer is set to Google', main && main.referer === 'https://www.google.com/', JSON.stringify(main));
    check('latimes: Cookie header is stripped (not in allow_cookies)', main && !main.cookie, JSON.stringify(main));
    const sub = log.find((l) => l.url === '/sub.js');
    check('latimes: subresource Referer is set to Google too', sub && sub.referer === 'https://www.google.com/', JSON.stringify(sub));
    check('latimes: tribdss.com paywall script is blocked', !log.some((l) => l.host.endsWith('tribdss.com')), JSON.stringify(log));

    log = await visit('https://www.nytimes.com/page');
    main = log.find((l) => l.url === '/page');
    check('nytimes: Cookie is kept (in allow_cookies)', main && main.cookie === 't=1', JSON.stringify(main));
    check('nytimes: tribdss.com is not blocked (not a Tribune paper)', log.some((l) => l.host.endsWith('tribdss.com')));
    log = await visit('https://www.nytimes.com/page');
    let beacon = log.find((l) => l.url.startsWith('/beacon'));
    check('nytimes: content script clears localStorage', beacon && beacon.url === '/beacon?ls=null', beacon && beacon.url);

    log = await visit('https://www.wsj.com/articles/abc?mod=foo&x=1#frag');
    const wsj = log.filter((l) => l.url.startsWith('/articles/'));
    check('wsj: mod is replaced with rsswn', wsj.length === 1 && /mod=rsswn/.test(wsj[0].url) && /mod=rsswn/.test(page.url()), JSON.stringify(wsj) + ' final=' + page.url());
    check('wsj: Referer is Facebook', wsj[0] && wsj[0].referer === 'https://www.facebook.com/', JSON.stringify(wsj));
    log = await visit('https://www.wsj.com/articles/def');
    check('wsj: mod=rsswn is added without a redirect loop',
      log.filter((l) => l.url.startsWith('/articles/')).length === 1 && page.url().endsWith('/articles/def?mod=rsswn'), page.url());

    log = await visit('https://www.thenation.com/page');
    check('thenation: paywall-script.php is blocked', !log.some((l) => l.url.includes('paywall-script')), JSON.stringify(log));
    log = await visit('https://www.haaretz.co.il/page');
    check('haaretz: inter.js is blocked', !log.some((l) => l.url.includes('inter.js')), JSON.stringify(log));

    log = await visit('https://www.barrons.com/articles/x');
    check('barrons /articles: Referer is set to Google', log[0] && log[0].referer === 'https://www.google.com/', JSON.stringify(log[0]));
    log = await visit('https://www.barrons.com/other');
    check('barrons outside /articles: untouched', log[0] && log[0].referer === null, JSON.stringify(log[0]));

    await ctx.addCookies([{ name: 'w', value: '1', domain: '.wired.com', path: '/', secure: true }]);
    await visit('https://www.wired.com/page');
    await page.waitForTimeout(800);
    const wired = await ctx.cookies('https://www.wired.com/');
    check('wired: cookies are removed after page load', wired.length === 0, JSON.stringify(wired));

    await visit('https://example.org/page');
    log = await visit('https://example.org/page');
    main = log.find((l) => l.url === '/page');
    beacon = log.find((l) => l.url.startsWith('/beacon'));
    check('control example.org: cookies, Referer and localStorage untouched',
      main.cookie === 't=1' && main.referer === null && beacon.url === '/beacon?ls=1', JSON.stringify(main) + beacon.url);

    await sw.evaluate(() => new Promise((r) => chrome.storage.sync.get({ sites: {} }, (i) => {
      delete i.sites['Los Angeles Times'];
      chrome.storage.sync.set({ sites: i.sites }, r);
    })));
    await page.waitForTimeout(1000);
    log = await visit('https://www.latimes.com/page');
    main = log.find((l) => l.url === '/page');
    check('after disabling latimes in options: Referer and Cookie untouched', main.referer === null && main.cookie === 't=1', JSON.stringify(main));
    check('after disabling latimes in options: tribdss.com no longer blocked', log.some((l) => l.host.endsWith('tribdss.com')));

    const opt = await ctx.newPage();
    await opt.goto(`chrome-extension://${id}/options.html`);
    const boxes = await opt.locator('#bypass_sites input').count();
    check('options page renders the site list', boxes > 50, `${boxes} checkboxes`);

    const after = await extensionInfo(ctx);
    check('no runtime errors', after.runtimeErrors.length === 0, JSON.stringify(after.runtimeErrors));
  } catch (e) {
    check('test run completed without exceptions', false, e.stack);
  } finally {
    await ctx.close();
    finish();
  }
})();
