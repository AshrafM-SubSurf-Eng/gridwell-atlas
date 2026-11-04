#!/usr/bin/env bash
# Package site/ for GitHub Pages. site/index.html is written as a page body that
# also publishes as a Claude artifact (which supplies its own document skeleton),
# so here it gets a doctype to render in standards mode on an ordinary web host.
set -euo pipefail
rm -rf _site && mkdir -p _site
cp -r site/data _site/data
# on the open web the page gets a descriptive title for search results; the artifact copy keeps the short name
{ printf '<!doctype html>\n<html lang="en">\n'; sed 's|<title>GRIDWELL Atlas</title>|<title>GRIDWELL Atlas: abandoned oil and gas wells screened for geothermal (EGS) reuse</title>|' site/index.html; printf '\n</html>\n'; } > _site/index.html
# search-engine files: a sitemap dated by this deploy, and any site-verification file kept in site/
cat > _site/sitemap.xml <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://ashrafm-subsurf-eng.github.io/gridwell-atlas/</loc><lastmod>$(date -u +%Y-%m-%d)</lastmod><changefreq>monthly</changefreq></url>
</urlset>
EOF
for f in site/google*.html; do [ -e "$f" ] && cp "$f" _site/; done
touch _site/.nojekyll
echo "packaged $(du -sh _site | cut -f1)"
