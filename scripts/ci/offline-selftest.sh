#!/usr/bin/env bash
# Proves the offline harness fails on egress: each probe must be caught.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
fail=0
probe() {
  if "$here/offline-run.sh" --log "${RUNNER_TEMP:-/tmp}/selftest.strace" -- "$@" >/dev/null 2>&1; then
    echo "offline-selftest: NOT caught: $*" >&2; fail=1
  else
    echo "offline-selftest: caught: $*"
  fi
}
# The probes swallow their own errors, so only the monitor can fail them.
probe sh -c 'curl -sS --max-time 5 https://example.com >/dev/null 2>&1; true'
probe sh -c 'curl -sS --max-time 5 http://1.1.1.1 >/dev/null 2>&1; true'
probe python3 -c 'import socket
try: socket.create_connection(("2606:4700:4700::1111", 443), 2)
except OSError: pass'
# Loopback traffic is allowed.
if "$here/offline-run.sh" --log "${RUNNER_TEMP:-/tmp}/selftest-lo.strace" -- \
    python3 -c 'import socket
s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen()
socket.create_connection(s.getsockname(), 2)'; then
  echo "offline-selftest: loopback allowed"
else
  echo "offline-selftest: loopback wrongly blocked" >&2; fail=1
fi
exit $fail
