#!/usr/bin/env bash
# Offline job harness (ARC-17; EVL-16). Linux only; run as root (sudo).
#
#   sudo scripts/ci/offline-run.sh [--user NAME] [--log FILE] -- COMMAND [ARGS...]
#
# Runs COMMAND as NAME inside a fresh network namespace that has only loopback, under
# `strace -f` as a connection monitor. Fails if COMMAND fails or if any process attempted
# to reach a non-loopback address or to resolve a name (see jana_tools/offline.py).
set -euo pipefail

user="${SUDO_USER:-$(id -un)}"
log="${RUNNER_TEMP:-/tmp}/offline-egress.strace"
while [ $# -gt 0 ]; do
  case "$1" in
    --user) user="$2"; shift 2 ;;
    --log) log="$2"; shift 2 ;;
    --) shift; break ;;
    *) echo "offline-run: unknown option $1" >&2; exit 2 ;;
  esac
done
[ $# -gt 0 ] || { echo "usage: offline-run.sh [--user NAME] [--log FILE] -- COMMAND..." >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "offline-run: must run as root" >&2; exit 2; }

here="$(cd "$(dirname "$0")/../.." && pwd)"
ns="jana-offline-$$"
cleanup() { ip netns delete "$ns" 2>/dev/null || true; rm -rf "/etc/netns/$ns"; }
trap cleanup EXIT

ip netns add "$ns"
ip -n "$ns" link set lo up
# Name lookups go to a non-loopback documentation address, so any DNS query is a visible attempt.
mkdir -p "/etc/netns/$ns"
echo "nameserver 192.0.2.53" > "/etc/netns/$ns/resolv.conf"

set +e
strace -f -qq -e trace=connect,sendto,sendmsg -e signal=none -o "$log" \
  ip netns exec "$ns" sudo -u "$user" -E -H env "PATH=$PATH" "$@"
status=$?
set -e

PYTHONPATH="$here/scripts" python3 -m jana_tools.offline "$log"
monitor=$?
if [ "$status" -ne 0 ]; then echo "offline-run: command failed with status $status" >&2; exit "$status"; fi
exit "$monitor"
