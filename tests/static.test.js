'use strict';
// Static checks: JS syntax, manifests are valid MV3, no analytics, no leftover MV2 APIs.
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { REPO, createReporter } = require('./lib');

const { check, finish } = createReporter('static checks');
const EXTENSIONS = ['bypass-paywalls/bypass-paywalls-chrome-master', '媒体付费墙杀手/3.0.2_0'];

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return e.name === 'node_modules' || e.name === '.git' ? [] : walk(p);
    return [p];
  });
}

const files = walk(REPO);
for (const f of files.filter((f) => /\.(js|user\.js)$/.test(f) && !f.endsWith('.min.js'))) {
  let ok = true, err = '';
  try { execFileSync(process.execPath, ['--check', f], { stdio: 'pipe' }); } catch (e) { ok = false; err = e.stderr.toString(); }
  check(`syntax: ${path.relative(REPO, f)}`, ok, err);
}
for (const f of files.filter((f) => f.endsWith('.json'))) {
  let ok = true, err = '';
  try { JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { ok = false; err = e.message; }
  check(`valid JSON: ${path.relative(REPO, f)}`, ok, err);
}

const MV2_APIS = /chrome\.(browserAction|tabs\.executeScript|extension\.getURL)|webRequestBlocking|new XMLHttpRequest/;
for (const ext of EXTENSIONS) {
  const dir = path.join(REPO, ext);
  const m = JSON.parse(fs.readFileSync(path.join(dir, 'manifest.json'), 'utf8'));
  check(`${ext}: manifest_version is 3`, m.manifest_version === 3, String(m.manifest_version));
  check(`${ext}: uses a background service worker`, m.background && m.background.service_worker && !m.background.scripts, JSON.stringify(m.background));
  check(`${ext}: no webRequestBlocking permission`, !(m.permissions || []).includes('webRequestBlocking'));
  check(`${ext}: no update_url`, !m.update_url);
  const referenced = [m.background.service_worker, m.action && m.action.default_popup, m.options_ui && m.options_ui.page]
    .concat(Object.values(m.icons || {}));
  for (const ref of referenced.filter(Boolean)) {
    check(`${ext}: referenced file exists: ${ref}`, fs.existsSync(path.join(dir, ref)));
  }
  const bg = fs.readFileSync(path.join(dir, m.background.service_worker), 'utf8');
  const hit = bg.match(MV2_APIS);
  check(`${ext}: service worker uses no MV2-only APIs`, !hit, hit && hit[0]);
}

const analytics = files.filter((f) => /\.(js|html|json)$/.test(f) && !f.startsWith(__dirname) && /google-analytics\.com|_gaq/.test(fs.readFileSync(f, 'utf8')));
check('no Google Analytics code', !analytics.length, analytics.map((f) => path.relative(REPO, f)).join(', '));

finish();
