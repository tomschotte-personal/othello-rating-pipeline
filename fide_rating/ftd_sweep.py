"""Weekend auto-sweep: detect FTD tournaments that are live or starting today
and emit the ids + tracking window for the Actions gate.

Primary source: the site's own upcoming/live listing, pushed over socket.io as
an 'otb-tournaments-list' frame when loading flipthedisc.com/live. This covers
events regardless of their FTD id (organizers often register big championships
months ahead, giving them LOW ids - an id-range sweep misses exactly those;
learned the hard way with the 4th Asian-Pacific Championship, id 489).

Fallback if the listing yields nothing parseable: sweep ids around the highest
cached tournament id, as before.

A hit is any event with >=4 players whose window [expected_start, expected_end]
overlaps today (UTC). Ids in the .ftd_finalized marker are skipped.

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

now = datetime.now(timezone.utc)
today = now.date()

done_ids = set()
try:
    marker = open(os.path.join(PROJECT, '.ftd_finalized')).read().split('@')[0]
    done_ids = {int(x) for x in marker.split()}
except Exception:
    pass


def get_listing():
    """Load flipthedisc.com/live and return the tournaments list pushed over
    the socket (list of dicts with id/name/players/expected_start/expected_end)."""
    from playwright.sync_api import sync_playwright
    frames = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        pg.on('websocket', lambda ws: ws.on('framereceived',
              lambda f: frames.append(f if isinstance(f, str)
                                      else f.decode('utf-8', 'replace'))))
        pg.goto('https://flipthedisc.com/live', timeout=45000)
        pg.wait_for_timeout(8000)
        b.close()
    best = max((f for f in frames if f.startswith('42["otb-tournaments-list"')),
               key=len, default=None)
    if not best:
        return None
    return json.loads(best[2:])[1]


hits = []
listing = None
try:
    listing = get_listing()
except Exception as e:
    print(f'listing fetch failed: {e}', file=sys.stderr)

if listing is not None:
    print(f'FTD listing: {len(listing)} events', file=sys.stderr)
    for t in listing:
        tid = t.get('id')
        start = (t.get('expected_start') or '')[:10]
        end = (t.get('expected_end') or '')[:16]
        n_pl = t.get('players') or 0
        if not tid or tid in done_ids or n_pl < 4:
            continue
        end_d = end[:10] or start
        if start and start <= str(today) <= max(end_d, start):
            hits.append((int(tid), end))
            print(f'  hit: {tid} {t.get("name")} start={start} end={end} '
                  f'players={n_pl}', file=sys.stderr)
else:
    # Fallback: id-range sweep near the highest cached id
    cached = [int(m.group(1)) for f in os.listdir(PROJECT)
              if (m := re.match(r'tournament_(\d+)\.json$', f))]
    hi = max(cached, default=590)
    lo, hiid = max(hi - 2, 400), hi + 20
    print(f'listing unavailable - fallback sweep {lo}-{hiid}', file=sys.stderr)
    yesterday = today - timedelta(days=1)
    for tid in range(lo, hiid + 1):
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
        if (start == str(today) or (cur and str(yesterday) <= start <= str(today))) and n_pl >= 4:
            hits.append((tid, end))
            print(f'  hit: {tid} {info.get("name")}', file=sys.stderr)

# Prime/refresh caches for every hit so the live loop starts warm
for tid, _ in hits:
    try:
        d = fetch_tournament_full(tid)
        with open(os.path.join(PROJECT, f'tournament_{tid}.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception as e:
        print(f'  cache prime failed for {tid}: {e}', file=sys.stderr)

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
