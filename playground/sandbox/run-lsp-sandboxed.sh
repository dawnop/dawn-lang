#!/bin/sh
# Own one native Dawn LSP process for one Playground WebSocket.  The public
# gateway may choose only the action and a random 128-bit session id; every
# executable and resource/isolation property is pinned here.
set -eu

PREFIX=dawn-play-lsp-
LSP_HIDDEN_PATHS="-/opt/dawnop -/opt/vaultwarden -/var/www -/etc/letsencrypt -/etc/nginx"

valid_id() {
  [ "${#1}" -eq 32 ] || return 1
  case "$1" in
    *[!0-9a-f]*) return 1 ;;
  esac
}

action=${1:-}
case "$action" in
  cleanup)
    [ "$#" -eq 1 ] || { echo "run-lsp-sandboxed: cleanup takes no id" >&2; exit 2; }
    # systemctl expands unit globs itself and succeeds when none are loaded.
    exec /usr/bin/systemctl stop "${PREFIX}*.service"
    ;;
  run | stop)
    [ "$#" -eq 2 ] || { echo "run-lsp-sandboxed: expected action and id" >&2; exit 2; }
    session_id=$2
    valid_id "$session_id" || {
      echo "run-lsp-sandboxed: invalid session id" >&2
      exit 2
    }
    ;;
  *)
    echo "run-lsp-sandboxed: expected run, stop, or cleanup" >&2
    exit 2
    ;;
esac

unit="${PREFIX}${session_id}"
if [ "$action" = stop ]; then
  exec /usr/bin/systemctl stop "${unit}.service"
fi

# The per-session limits are backed by dawn-play-lsp.slice, whose aggregate
# limits remain effective even if the gateway is restarted mid-session.
exec /usr/bin/systemd-run \
  --quiet --wait --pipe --collect \
  --unit="$unit" \
  --property=BindsTo=dawn-play-lsp.service \
  --property=After=dawn-play-lsp.service \
  --property=Slice=dawn-play-lsp.slice \
  --property=DynamicUser=yes \
  --property=PrivateNetwork=yes \
  --property=PrivateDevices=yes \
  --property=PrivateTmp=yes \
  --property=ProtectSystem=strict \
  --property=ProtectHome=yes \
  --property=ProtectProc=invisible \
  --property=ProcSubset=pid \
  --property="InaccessiblePaths=$LSP_HIDDEN_PATHS" \
  --property=ProtectKernelTunables=yes \
  --property=ProtectKernelModules=yes \
  --property=ProtectKernelLogs=yes \
  --property=ProtectControlGroups=yes \
  --property=ProtectClock=yes \
  --property=ProtectHostname=yes \
  --property=RestrictNamespaces=yes \
  --property=RestrictSUIDSGID=yes \
  --property=RestrictRealtime=yes \
  --property=LockPersonality=yes \
  --property=NoNewPrivileges=yes \
  --property=CapabilityBoundingSet= \
  --property=SystemCallArchitectures=native \
  --property=SystemCallFilter=@system-service \
  --property=SystemCallFilter=~@privileged \
  --property=RestrictAddressFamilies=AF_UNIX \
  --property=UMask=0077 \
  --property=LimitCORE=0 \
  --property=MemoryMax=256M \
  --property=MemorySwapMax=0 \
  --property=TasksMax=16 \
  --property=CPUQuota=100% \
  --property=RuntimeMaxSec=31m \
  --property=TimeoutStopSec=3s \
  --property=WorkingDirectory=/tmp \
  -- /opt/dawn/bin/dawnc lsp
