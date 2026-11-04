// Fake news-site server for the extension tests.
// Chromium maps every hostname to 127.0.0.1 (--host-resolver-rules), so this one
// server answers for www.wsj.com, www.nytimes.com, ... on ports 80 and 443.
// Usage: node server.js <cert.pem> <key.pem>
'use strict';
const http = require('http');
const https = require('https');
const fs = require('fs');

const [certFile, keyFile] = process.argv.slice(2);
const log = [];

function handler(req, res) {
  const host = (req.headers.host || '').split(':')[0];
  const url = new URL(req.url, 'https://' + host);
  if (url.pathname === '/__log') {
    res.setHeader('content-type', 'application/json');
    return res.end(JSON.stringify(log));
  }
  if (url.pathname === '/__reset') {
    log.length = 0;
    return res.end('ok');
  }
  log.push({ host, url: req.url, referer: req.headers.referer || null, cookie: req.headers.cookie || null });
  if (url.pathname.endsWith('.js') || url.pathname.endsWith('.php')) {
    res.setHeader('content-type', 'application/javascript');
    return res.end('/* js */');
  }
  if (url.pathname.startsWith('/beacon')) {
    return res.end('ok');
  }
  // A page that loads the paywall scripts the extensions block, and reports
  // (via a beacon) what was in localStorage before it writes to it.
  res.setHeader('content-type', 'text/html');
  res.end(`<!doctype html><html><head>
<script src="/sub.js"></script>
<script src="https://ssnt.tribdss.com/meter.js"></script>
<script src="/x/paywall-script.php"></script>
<script src="/htz/js/inter.js"></script>
</head><body>page ${host}
<script>var v = localStorage.getItem('x'); new Image().src = '/beacon?ls=' + v; localStorage.setItem('x', '1');</script>
</body></html>`);
}

http.createServer(handler).listen(80, '127.0.0.1');
https.createServer({ key: fs.readFileSync(keyFile), cert: fs.readFileSync(certFile) }, handler).listen(443, '127.0.0.1', () => {
  console.log('test server listening on 127.0.0.1:80 and :443');
});
