# Sourced, not run: exports every line scripts/site-figures.sh prints as
# DAWN_SITE_FIG_<KEY>, for the two scripts that start the site generator
# (site/build.sh and scripts/site-dist-diff.sh).
#
# One file because there are two callers, and two copies of this loop would be
# two places for a key to be spelled differently. The figures script runs in a
# command substitution of its own, so a producer that fails stops the caller
# under its `set -e` rather than exporting half a set; a producer that prints
# nothing is exported as empty, and the generator is what refuses it.
site_figures_out="$(./scripts/site-figures.sh)"
while IFS='=' read -r site_fig_key site_fig_value; do
  [ -n "$site_fig_key" ] || continue
  export "DAWN_SITE_FIG_$(printf '%s' "$site_fig_key" | tr '[:lower:]' '[:upper:]')=$site_fig_value"
done <<< "$site_figures_out"
unset site_figures_out site_fig_key site_fig_value
