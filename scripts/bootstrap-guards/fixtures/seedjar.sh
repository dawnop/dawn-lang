#!/bin/sh
# The launcher contract supplies a fixed offline seed and released std tree so
# it can exercise bootstrap ordering without touching a cache or the network.
seed_jar() {
  printf '%s\n' "${DAWN_SEED:-$ROOT/.fake/seed.jar}"
}

seed_std_dir() {
  printf '%s\n' "$ROOT/.fake/seed-std"
}
