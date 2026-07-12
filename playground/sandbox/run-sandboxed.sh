#!/bin/sh
# Run one command inside a throwaway systemd sandbox. Invoked by the dawn-play
# runner as `sudo -n run-sandboxed.sh <workdir> <cmd> [args...]`; whitelisted for
# the dawn-play user in sudoers (see sudoers.dawn-play). Everything the runner
# passes is untrusted, so this script hardcodes every limit and never interprets
# the arguments as anything but a literal argv to exec.
#
# Threat model: the command compiles/runs arbitrary user Dawn (hence arbitrary
# JVM) code. Each invocation must not touch the network, the filesystem outside
# its own temp dir, other processes, or more than its slice of CPU/RAM/time.
set -eu

WORKDIR="$1"
shift

# Refuse anything but an absolute path under a playground work root, so a
# compromised runner can't point the sandbox's writable path at, say, /etc.
# The server uses /var/lib/dawn-play/work (NOT /tmp: DynamicUser implies a
# private /tmp that ReadWritePaths can't bind into); /tmp/dawn-play-* stays
# allowed for ad-hoc local testing.
case "$WORKDIR" in
  /var/lib/dawn-play/work/* | /tmp/dawn-play-*) : ;;
  *) echo "run-sandboxed: refusing workdir $WORKDIR" >&2; exit 3 ;;
esac

exec systemd-run \
  --quiet --wait --pipe --collect \
  --property=DynamicUser=yes \
  --property=PrivateNetwork=yes \
  --property=PrivateDevices=yes \
  --property=ProtectSystem=strict \
  --property=ProtectHome=yes \
  --property=ProtectProc=invisible \
  --property="InaccessiblePaths=-/opt/dawnop -/opt/vaultwarden -/var/www -/etc/letsencrypt -/etc/nginx" \
  --property=ProtectKernelTunables=yes \
  --property=ProtectKernelModules=yes \
  --property=ProtectControlGroups=yes \
  --property=RestrictNamespaces=yes \
  --property=RestrictSUIDSGID=yes \
  --property=LockPersonality=yes \
  --property=NoNewPrivileges=yes \
  --property=CapabilityBoundingSet= \
  --property=SystemCallFilter=@system-service \
  --property=SystemCallFilter=~@privileged \
  --property=MemoryMax=512M \
  --property=MemorySwapMax=0 \
  --property=TasksMax=64 \
  --property=CPUQuota=200% \
  --property=RuntimeMaxSec=15 \
  --property=WorkingDirectory="$WORKDIR" \
  --property=ReadWritePaths="$WORKDIR" \
  --property=BindReadOnlyPaths=/opt/dawn \
  -- "$@"
