"""Open one GitHub issue per review item, skipping titles that are already open."""
import json, subprocess, sys
from pathlib import Path

path = Path(sys.argv[1])
items = json.loads(path.read_text()) if path.exists() else []
if not items:
    print('no review issues'); sys.exit(0)
out = subprocess.run(['gh', 'issue', 'list', '--state', 'open', '--limit', '200', '--json', 'title'],
                     capture_output=True, text=True)
open_titles = {i['title'] for i in json.loads(out.stdout or '[]')}
for it in items:
    if it['title'] in open_titles:
        print('already open:', it['title']); continue
    subprocess.run(['gh', 'issue', 'create', '--title', it['title'], '--body', it['body'] + '\n\n_Opened by the monthly refresh._'],
                   check=False)
    print('opened:', it['title'])
