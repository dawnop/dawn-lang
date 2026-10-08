#!/bin/sh
# Run one command inside a throwaway systemd sandbox. Invoked by the dawn-play
# runner as `sudo -n run-sandboxed.sh run <id> <workdir> <cmd> [args...]`, and
# as `sudo -n run-sandboxed.sh stop <id>` when that command outlives the
# runner's time limit; whitelisted for the dawn-play user in sudoers (see
# sudoers.dawn-play). Everything the runner
# passes is untrusted, so this script hardcodes every limit and never interprets
# the arguments as anything but a literal argv to exec.
#
# Threat model: the command compiles/runs arbitrary user Dawn (hence arbitrary
# JVM) code. Each invocation must not touch the network, the filesystem outside
# its own temp dir, other processes, or more than its slice of CPU/RAM/time.
#
# The runner passes the request's `box/` as <workdir>, not the request
# directory itself: the command's output files sit one level up, where the
# unit cannot rename or replace them (playground/src/play/exec.dawn).
set -eu

# The unit is named after an id the runner picks, 32 lowercase hex digits, so
# the runner can stop exactly the unit it started. It used to be anonymous,
# and on a timeout the runner could only SIGKILL `sudo`, which does not reach
# the unit `systemd-run --wait` started: the unit ran on to RuntimeMaxSec while
# the runner's gate admitted the next request (the same run/stop shape as
# run-lsp-sandboxed.sh). The id cannot name anything but a unit with this
# prefix.
PREFIX=dawn-play-run-

valid_id() {
  [ "${#1}" -eq 32 ] || return 1
  case "$1" in
    *[!0-9a-f]*) return 1 ;;
  esac
}

action=${1:-}
case "$action" in
  run)
    [ "$#" -ge 4 ] || { echo "run-sandboxed: expected run <id> <workdir> <cmd...>" >&2; exit 2; }
    ;;
  stop)
    [ "$#" -eq 2 ] || { echo "run-sandboxed: expected stop <id>" >&2; exit 2; }
    ;;
  *)
    echo "run-sandboxed: expected run or stop" >&2
    exit 2
    ;;
esac
valid_id "$2" || { echo "run-sandboxed: invalid unit id" >&2; exit 2; }
unit="${PREFIX}$2"
if [ "$action" = stop ]; then
  exec /usr/bin/systemctl stop "${unit}.service"
fi
shift 2

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

# The JDK the unit's `bin/dawn` launches the compiler on. The unit's PATH is
# systemd's default, where `java` is whatever the OS packages (the JRE other
# services share), not the pinned GraalVM CE the server is meant to match CI
# with (DEPLOY.md step 2). bin/dawn takes JAVA_HOME before it looks anywhere
# else, so naming it here is enough; the path is fixed in this root-run script,
# not taken from the caller. The run phase's `java` and the view's `javap` need
# no help: the runner puts their absolute paths on argv.
SANDBOX_JAVA_HOME=/opt/dawn/graalvm-21

# The largest file the unit may write, its stdout included: the runner opened
# that file and the unit writes through the descriptor, but RLIMIT_FSIZE is
# the writer's, so it applies all the same. MemoryMax bounds what the private
# /tmp can hold; nothing bounded the disk under the work root, and a program
# printing at full speed for the length of its run left gigabytes behind on
# the host the blog shares. A playground jar is under 100 KB and the runner
# shows 64 KB of output, so 32 MB is far from both. Past it, a write fails
# with EFBIG (the JVM ignores SIGXFSZ) and the program goes on without it.
SANDBOX_FSIZE=32M

exec systemd-run \
  --quiet --wait --pipe --collect \
  --unit="$unit" \
  --setenv="DAWN_JVM_OPTS=$SANDBOX_JVM_OPTS" \
  --setenv="JAVA_HOME=$SANDBOX_JAVA_HOME" \
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
  --property=LimitFSIZE=$SANDBOX_FSIZE \
  --property=UMask=0000 \
  --property=CPUQuota=200% \
  --property=RuntimeMaxSec=15 \
  --property=TimeoutStopSec=3s \
  --property=WorkingDirectory="$WORKDIR" \
  --property=ReadWritePaths="$WORKDIR" \
  --property=BindReadOnlyPaths=/opt/dawn \
  -- "$@"
