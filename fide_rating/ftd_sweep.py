"""Weekend auto-sweep: detect FTD tournaments that are live or starting today
and emit the ids + tracking window for the Actions gate.

Sweeps from just below the highest cached tournament id up to +20 beyond it
(FTD ids are roughly chronological). A hit is any event with >=4 players whose
expected_start is today (UTC), or that started yesterday and has games played
(two-day events). Ids already covered by the .ftd_finalized marker are skipped.

Prints exactly one machine-readable line among the fetch noise:
  ARM ids=<space-separated ids> until=<YYYY-MM-DDTHH:MM>   (UTC)
or
  NONE
The workflow greps for it:  grep -E '^(ARM|NONE)'
"""
import sys, os, json, re
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(BASE)
sys.path.insert(0, BASE)
from shift1800_live import fetch_tournament_full

done_ids = set()
try:
    marker = open(os.path.join(PROJECT, '.ftd_finalized')).read().split('@')[0]
    done_ids = {int(x) for x in marker.split()}
except Exception:
    pass

cached = []
for f in os.listdir(PROJECT):
    m = re.match(r'tournament_(\d+)\.json$', f)
    if m:
        cached.append(int(m.group(1)))
hi = max(cached, default=590)
start_id = int(sys.argv[1]) if len(sys.argv) > 1 else max(hi - 2, 400)
end_id = int(sys.argv[2]) if len(sys.argv) > 2 else hi + 20

now = datetime.now(timezone.utc)
today = now.date()
yesterday = today - timedelta(days=1)
print(f'Sweeping FTD {start_id}-{end_id} for events live on {today} (UTC)...',
      file=sys.stderr)

hits = []
for tid in range(start_id, end_id + 1):
    if tid in done_ids:
        continue
    try:
        d = fetch_tournament_full(tid)
    except Exception:
        continue
    info = d.get('info') or {}
    start = (info.get('expected_start') or '')[:10]
    end = (info.get('expected_end') or '')[:16]
    cur = info.get('current_round') or 0
    n_pl = len(d.get('players_list') or [])
    live_today = (start == str(today)
                  or (cur and str(yesterday) <= start <= str(today)))
    if live_today and n_pl >= 4:
        hits.append((tid, end))
        with open(os.path.join(PROJECT, f'tournament_{tid}.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False)
        print(f'  hit: {tid} {info.get("name")} start={start} end={end} '
              f'players={n_pl} round={cur}', file=sys.stderr)

if not hits:
    print('NONE')
else:
    default_until = (now + timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M')
    ends = [e for _, e in hits if re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', e or '')]
    if ends:
        dt = datetime.strptime(max(ends), '%Y-%m-%dT%H:%M') + timedelta(minutes=45)
        until = dt.strftime('%Y-%m-%dT%H:%M')
    else:
        until = default_until
    print(f'ARM ids={" ".join(str(t) for t, _ in hits)} until={until}')
