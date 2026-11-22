"""XOT events from FlipTheDisc -> xot_data/ (the XOT world rating), for CI.

XOT events never enter the main rating: ftd_sweep / ftd_reconcile skip them on
the name and on FTD's own xot flag. This job picks them up instead:

  1. Candidates: every FTD id that .ftd_seen.json (written by ftd_reconcile)
     knows as XOT, plus the ids just above the highest known one (new events
     created since the last reconcile), probed here.
  2. Events that have started and are not yet complete in xot_data are fetched
     and converted (synthetic ids for newcomers, as xot_live.py does). The
     .ELO lands in wof_results/<year>/ first and is MOVED to xot_data/ - it
     must never stay in wof_results.
  3. Prints 'CHANGED <n>'; the workflow then reruns xot_rating + xot_html and
     pushes the XOT pages repo.

Run from fide_rating/:  python xot_ci.py [--ids 673 690]
"""
import argparse
import io
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, BASE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

XOT_DIR = os.path.join(ROOT, 'xot_data')
SEEN_PATH = os.path.join(ROOT, '.ftd_seen.json')
XOT_NAME = re.compile(r'\bxot\b', re.IGNORECASE)
LOOKAHEAD = 6


def game_lines(path):
    with open(path, encoding='utf-8') as f:
        return [l for l in f if l.startswith(' ') and ('>' in l or '<' in l or '=' in l)]


def xot_files():
    """FTD id -> xot_data .ELO path (from the 'flipthedisc.com/live/<id>' footer)."""
    out = {}
    for f in os.listdir(XOT_DIR):
        if f.endswith('.ELO'):
            with open(os.path.join(XOT_DIR, f), encoding='utf-8', errors='replace') as fh:
                m = re.search(r'flipthedisc\.com/live/(\d+)', fh.read())
            if m:
                out[int(m.group(1))] = os.path.join(XOT_DIR, f)
    return out


def cache_path(tid):
    return os.path.join(ROOT, f'tournament_{tid}.json')


def load_cache(tid):
    try:
        with open(cache_path(tid), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def fetch(tid):
    """Fresh FTD fetch, written to the cache convert() reads. Finished events
    come without players_list: keep the WOF ids from the previous cache."""
    from shift1800_live import fetch_tournament_full
    d = fetch_tournament_full(tid)
    # FTD answers an unknown id with another event (the WOC, id 571): treat as missing.
    if (d.get('info') or {}).get('id') != tid:
        return None
    if not d.get('players_list'):
        d['players_list'] = load_cache(tid).get('players_list') or []
    with open(cache_path(tid), 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, default=str)
    return d


def is_xot(info):
    return bool(info.get('xot')) or bool(XOT_NAME.search(info.get('name') or ''))


def started(info, now):
    t = info.get('start_date') or info.get('expected_start')
    if not t:
        return True
    return datetime.fromisoformat(t.replace('Z', '+00:00')) <= now + timedelta(minutes=30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ids', type=int, nargs='*', help='only these FTD ids')
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    seen = {}
    if os.path.exists(SEEN_PATH):
        with open(SEEN_PATH, encoding='utf-8') as f:
            seen = {int(k): v for k, v in json.load(f).items()}
    have = xot_files()

    if a.ids:
        cands = set(a.ids)
    else:
        cands = {t for t, v in seen.items() if v.get('xot') or XOT_NAME.search(v.get('name') or '')}
        real = [t for t, v in seen.items() if v.get('status') in ('open', 'finished')]
        hi = max(real + list(have), default=600)
        cands |= set(range(hi + 1, hi + LOOKAHEAD + 1))   # created since the last reconcile
    print(f'XOT candidates: {sorted(cands)}')

    changed = 0
    for tid in sorted(cands):
        info = (load_cache(tid).get('info') or {})
        # Done: in xot_data and our last fetch already saw the event finished.
        if tid in have and info.get('end_date') and (info.get('current_round') or 0) >= (info.get('rounds') or 1):
            continue
        if info and not started(info, now) and not a.ids:
            print(f'  {tid}: {info.get("name")} starts {info.get("expected_start")} - not yet')
            continue
        try:
            d = fetch(tid)
        except Exception as e:
            print(f'  {tid}: fetch failed: {e}')
            continue
        if d is None:
            continue
        info = d['info']
        if not is_xot(info):
            continue
        print(f'CACHE tournament_{tid}.json')
        if not started(info, now):
            print(f'  {tid}: {info.get("name")} starts {info.get("expected_start")} - not yet')
            continue
        import ftd_to_elo
        tmp = ftd_to_elo.convert(tid, synthetic_ids=True)
        dst = have.get(tid) or os.path.join(XOT_DIR, os.path.basename(tmp))
        games = game_lines(tmp)
        old = game_lines(dst) if os.path.exists(dst) else []
        if len(games) < len(old):          # partial fetch: never shrink
            print(f'  {tid}: fetch gave {len(games)} games < {len(old)} on disk - kept')
            os.remove(tmp)
            continue
        if games and games != old:
            shutil.move(tmp, dst)
            changed += 1
            print(f'  {tid}: {info.get("name")}: {len(games)} games -> {os.path.relpath(dst, ROOT)}')
        else:
            os.remove(tmp)
            print(f'  {tid}: {info.get("name")}: unchanged ({len(games)} games)')
    print(f'CHANGED {changed}')


if __name__ == '__main__':
    main()
