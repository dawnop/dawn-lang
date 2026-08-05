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

# The compiler's heap ceiling, set here because this is the only layer that can
# set it: systemd-run starts the unit with a clean environment, so nothing the
# runner exports reaches the compile phase.
#
# It has to be said explicitly because neither of the two things that look like
# they would cap it actually does. `bin/dawn` pins -Xmx2g (a build-box default,
# 4x this unit's MemoryMax), and the JVM does not see the cgroup: measured
# 2026-08-05, MaxHeapSize is byte-identical inside and outside a 512M scope
# despite UseContainerSupport=true, so ergonomics would aim at a quarter of
# *host* RAM. Either way the JVM aims past MemoryMax and the kernel kills it --
# contained, but as an opaque SIGKILL rather than a diagnostic.
#
# Below MemoryMax on purpose: a limit the JVM enforces itself surfaces as an
# OutOfMemoryError the runner can report, and the cgroup stays a backstop
# instead of the mechanism. Measured on hello-world: 466 MB peak RSS at 256m
# against 542 MB at 2g -- the second already over this unit's ceiling.
# -Xss is left alone: stack is reserved address space, not resident pages, and
# shrinking it would fail deeply nested programs the parser handles today.
SANDBOX_JVM_OPTS="-Xss512m -Xmx256m"

exec systemd-run \
  --quiet --wait --pipe --collect \
  --setenv="DAWN_JVM_OPTS=$SANDBOX_JVM_OPTS" \
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
