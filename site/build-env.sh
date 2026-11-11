# The production build and its independent renderer oracle must stamp the
# same bytes. Share the defaults so an unstamped oracle cannot miss a footer
# difference in the site that is actually shipped.
DAWN_SITE_VERSION="${DAWN_SITE_VERSION:-$(sed -n 's/^pub const VERSION: String = "\(.*\)"$/\1/p' selfhost/src/version.dawn)}"
if [ -z "${DAWN_SITE_COMMIT:-}" ] && git rev-parse --git-dir >/dev/null 2>&1; then
  DAWN_SITE_COMMIT="$(git rev-parse --short=8 HEAD)"
  if [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    DAWN_SITE_COMMIT="${DAWN_SITE_COMMIT}-dirty"
  fi
fi
export DAWN_SITE_VERSION DAWN_SITE_COMMIT="${DAWN_SITE_COMMIT:-}"
export DAWN_SITE_PLAY_ORIGIN="${DAWN_SITE_PLAY_ORIGIN:-}"
