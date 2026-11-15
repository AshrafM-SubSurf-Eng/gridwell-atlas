#!/usr/bin/env bash
# Package site/ for GitHub Pages. site/index.html is written as a page body that
# also publishes as a Claude artifact (which supplies its own document skeleton),
# so here it gets a doctype to render in standards mode on an ordinary web host.
set -euo pipefail
rm -rf _site && mkdir -p _site
cp -r site/data _site/data
# on the open web the page gets a descriptive title for search results; the artifact copy keeps the short name
# the head ends after the first </style>; an explicit <head>...</head><body> lets strict parsers (site verification) find the meta tags
{ printf '<!doctype html>\n<html lang="en">\n<head>\n'
  sed 's|<title>GRIDWELL Atlas</title>|<title>GRIDWELL Atlas: abandoned oil and gas wells screened for geothermal (EGS) reuse</title>|' site/index.html \
    | awk '{print} !done && $0 == "</style>" {print "</head>"; print "<body>"; done = 1}'
  printf '\n</body>\n</html>\n'; } > _site/index.html
grep -q '^</head>$' _site/index.html || { echo "page head not closed: no </style> line found" >&2; exit 1; }
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
