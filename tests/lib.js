'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const REPO = path.resolve(__dirname, '..');

function createReporter(title) {
  const results = [];
  return {
    check(name, cond, detail) {
      results.push({ ok: !!cond, line: `${cond ? 'PASS' : 'FAIL'}  ${name}${detail && !cond ? '  — ' + detail : ''}` });
    },
    finish() {
      console.log(`\n## ${title}`);
      results.forEach((r) => console.log(r.line));
      const failed = results.filter((r) => !r.ok).length;
      console.log(`${results.length - failed}/${results.length} passed`);
      if (failed || !results.length) process.exitCode = 1;
    },
  };
}

// Copy the extension to a temp dir so Chromium can't modify files in the repo
function copyExtension(relDir) {
  const dest = fs.mkdtempSync(path.join(os.tmpdir(), 'ext-'));
  fs.cpSync(path.join(REPO, relDir), dest, { recursive: true });
  return dest;
}

async function launchWithExtension(extDir) {
  const ctx = await chromium.launchPersistentContext('', {
    headless: true,
    channel: 'chromium', // new headless mode, which supports extensions
    ignoreHTTPSErrors: true,
    args: [
      `--disable-extensions-except=${extDir}`,
      `--load-extension=${extDir}`,
      '--no-proxy-server',
      '--host-resolver-rules=MAP * 127.0.0.1',
      '--ignore-certificate-errors',
    ],
  });
  const sw = ctx.serviceWorkers()[0] || (await ctx.waitForEvent('serviceworker', { timeout: 15000 }));
  await new Promise((r) => setTimeout(r, 1500));
  return { ctx, sw, id: new URL(sw.url()).host };
}

async function extensionInfo(ctx) {
  const p = await ctx.newPage();
  await p.goto('chrome://extensions');
  const info = await p.evaluate(() => new Promise((res) =>
    chrome.developerPrivate.getExtensionsInfo({ includeDisabled: true }, (x) => res(x.map((e) => ({
      name: e.name,
      state: e.state,
      runtimeErrors: e.runtimeErrors.map((r) => r.message),
      manifestErrors: e.manifestErrors.map((r) => r.message),
    }))))));
  await p.close();
  return info[0];
}

const server = {
  log: async () => (await fetch('http://127.0.0.1/__log')).json(),
  reset: () => fetch('http://127.0.0.1/__reset'),
};

module.exports = { REPO, createReporter, copyExtension, launchWithExtension, extensionInfo, server };
