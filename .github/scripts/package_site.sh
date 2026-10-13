#!/usr/bin/env bash
# Package site/ for GitHub Pages. site/index.html is written as a page body that
# also publishes as a Claude artifact (which supplies its own document skeleton),
# so here it gets a doctype to render in standards mode on an ordinary web host.
set -euo pipefail
rm -rf _site && mkdir -p _site
cp -r site/data _site/data
{ printf '<!doctype html>\n<html lang="en">\n'; cat site/index.html; printf '\n</html>\n'; } > _site/index.html
touch _site/.nojekyll
echo "packaged $(du -sh _site | cut -f1)"
