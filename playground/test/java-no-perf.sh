#!/bin/sh
# Paired HTTP contracts also run older runner binaries whose JVM argv cannot
# be changed here. PLAY_JAVA points at this entry for both halves, so a VM
# warning never becomes program output even for the historical baseline.
exec "${JAVA_HOME:+$JAVA_HOME/bin/}java" -XX:-UsePerfData "$@"
