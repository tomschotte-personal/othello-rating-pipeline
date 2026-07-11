"""Detect FTD tournaments that are live today (or starting today).

Sweeps a range of FTD tournament IDs and reports any whose expected_start is
today/tomorrow or that have games in progress (current_round > 0 with recent
start date). IDs are not strictly date-ordered, so the sweep range should
extend well past the last known ID.

Usage: python detect_ftd_live.py [start_id] [end_id]
"""
import sys, os, io, json
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from shift1800_live import fetch_tournament_full

start_id = int(sys.argv[1]) if len(sys.argv) > 1 else 590
end_id   = int(sys.argv[2]) if len(sys.argv) > 2 else 640

today = datetime.now().date()
window = {str(today - timedelta(days=1)), str(today), str(today + timedelta(days=1))}
print(f'Sweeping FTD {start_id}-{end_id} for events around {today}...')

hits = []
for tid in range(start_id, end_id + 1):
    try:
        d = fetch_tournament_full(tid)
    except Exception:
        continue
    info = d.get('info') or {}
    start = (info.get('expected_start') or '')[:10]
    cur = info.get('current_round') or 0
    n_pl = len(d.get('players_list') or [])
    if start in window or (cur and start >= str(today - timedelta(days=2))):
        hits.append((tid, info.get('name'), start, cur, n_pl))
        with open(os.path.join(os.path.dirname(BASE), f'tournament_{tid}.json'), 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False)

print()
print(f'=== Live/imminent tournaments found: {len(hits)} ===')
for tid, name, start, cur, n_pl in hits:
    print(f'  FTD {tid:>4}: {start}  {(name or "?")[:45]:45}  round={cur}  players={n_pl}')
