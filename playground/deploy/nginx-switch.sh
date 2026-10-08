#!/bin/sh
# Prints nginx-play.conf with the runner upstream chosen: the JVM runner on
# 127.0.0.1:8087 (the file as it is, which is what is live) or the native
# runner behind dawn-play-native.socket (docs/playground-native-runner-design.md,
# K4). It only prints. Nothing here edits nginx, and redeploy.sh never calls it:
# the switch is an operator's decision, taken after canary-check.py passed and
# written into the server's nginx config by hand.
#
#   nginx-switch.sh jvm      # identical to nginx-play.conf
#   nginx-switch.sh native   # the four REST locations proxy to the unix socket
#
# Why a generator and not a second hand-kept copy of the file: the two variants
# would drift in their CORS headers and rate limits, which are the parts that
# must not differ between the runners. The one difference is the proxy_pass
# target of /api/run, /api/check, /api/compile and /api/health. The native
# variant also gets client_body_timeout 10s on the three POST locations: the
# runner process blocks reading a declared body, and nginx cutting a slow
# client is what lets it see end of input (design 3.1, lesson 2).
# /api/lsp is the WebSocket gateway on 127.0.0.1:8088, not the runner, and is
# untouched.
#
# Rolling back is the other argument, then `nginx -t && nginx -s reload`; the
# JVM unit stays installed and enabled for exactly that (design 6.2).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
conf=${2:-$here/nginx-play.conf}
SOCK=${PLAY_NATIVE_SOCKET:-/run/dawn-play/http.sock}
case "${1:-}" in
  jvm) cat "$conf" ;;
  native)
    awk -v sock="$SOCK" '
      /proxy_pass http:\/\/127\.0\.0\.1:8087\// {
        path = $2; sub(/^http:\/\/127\.0\.0\.1:8087/, "", path); sub(/;$/, "", path)
        print "    proxy_pass http://unix:" sock ":" path ";"
        if (path != "/health") print "    client_body_timeout 10s;"
        next
      }
      { print }
    ' "$conf" ;;
  *) echo "usage: $0 jvm|native [nginx-play.conf]" >&2; exit 2 ;;
esac
