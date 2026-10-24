#!/bin/sh
# The historical runner and the independent oracle must list the same class
# bytes without HotSpot startup diagnostics. Keep every javap output byte and
# disable the source of the warning for both contract halves.
exec "${JAVA_HOME:+$JAVA_HOME/bin/}javap" -J-XX:-UsePerfData "$@"
