#!/usr/bin/env bash
# Runs all tests. The fake news-site server must listen on ports 80/443, so it is
# started with sudo when not running as root.
set -uo pipefail
cd "$(dirname "$0")"

work=$(mktemp -d)
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$work/key.pem" -out "$work/cert.pem" -days 1 -subj "/CN=test" 2>/dev/null

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"
$SUDO "$(command -v node)" server.js "$work/cert.pem" "$work/key.pem" > "$work/server.log" 2>&1 &
server_pid=$!
cleanup() { $SUDO kill "$server_pid" 2>/dev/null; pkill -P "$server_pid" 2>/dev/null; rm -rf "$work"; }
trap cleanup EXIT

for _ in $(seq 1 50); do
  curl -s --noproxy '*' -o /dev/null http://127.0.0.1/__log && break
  sleep 0.2
done

status=0
for t in static.test.js userscript.test.js bypass-paywalls.test.js media-killer.test.js; do
  node "$t" || status=1
done
exit $status
