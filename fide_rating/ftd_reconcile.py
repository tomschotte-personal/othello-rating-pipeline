"""Reconcile FTD finished events against converted .ELO files.

The live sweep can miss events entirely: GitHub throttles the cron (2026-09-27
it ran 6x instead of ~96x, and the citta di Roma events started and finished
between two runs), and events below the live-window player threshold (Perth
Invitational, 2 players) never arm a window at all. This script closes those
holes after the fact:

  1. Build the set of already-converted FTD ids by scanning wof_results for
     the 'See: https://flipthedisc.com/live/<id>' line ftd_to_elo writes.
  2. Probe ids from (highest known - LOOKBACK) to (highest known + LOOKAHEAD).
     Probe results are cached in .ftd_seen.json so each id is fetched once;
     an id is re-probed only while its event is not yet finished.
  3. Convert every event that is finished, has >= 2 players and >= 1 game,
     and is not skip-listed (XOT -> XOT rating; handicap/friendly -> never
     rated). Skipped names are printed for review.

Prints 'CONVERTED <n>' on success so the workflow knows to commit.
"""
import io
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, BASE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SEEN_PATH = os.path.join(ROOT, '.ftd_seen.json')
LOOKBACK = 15
LOOKAHEAD = 10
# Never auto-rate these; they are either rated elsewhere (XOT) or not rateable.
SKIP_NAME = re.compile(r'xot|handicap|friendly', re.IGNORECASE)


def converted_ids():
    ids = set()
    results = os.path.join(ROOT, 'wof_results')
    for dirpath, _dirs, files in os.walk(results):
        for f in files:
            if not f.upper().endswith('.ELO'):
                continue
            try:
                with open(os.path.join(dirpath, f), encoding='utf-8',
                          errors='replace') as fh:
                    head = fh.read(2000)
            except OSError:
                continue
            m = re.search(r'flipthedisc\.com/live/(\d+)', head)
            if m:
                ids.add(int(m.group(1)))
    return ids


def load_seen():
    try:
        with open(SEEN_PATH, encoding='utf-8') as f:
            return {int(k): v for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


def save_seen(seen):
    with open(SEEN_PATH, 'w', encoding='utf-8') as f:
        json.dump({str(k): v for k, v in sorted(seen.items())}, f, indent=1)


def probe(tid):
    from shift1800_live import fetch_tournament_full
    try:
        d = fetch_tournament_full(tid)
    except Exception as e:
        return {'status': 'error', 'error': str(e)[:80]}
    info = d.get('info') or {}
    if not info.get('id'):
        return {'status': 'missing'}
    # Persist the cache convert() loads (fetch alone does not write it).
    with open(os.path.join(ROOT, f'tournament_{tid}.json'), 'w',
              encoding='utf-8') as f:
        json.dump(d, f)
    rounds = info.get('rounds') or 0
    cur = info.get('current_round') or 0
    finished = bool(info.get('end_date')) and cur >= rounds > 0
    return {
        'status': 'finished' if finished else 'open',
        'name': info.get('name') or '',
        'end_date': info.get('end_date') or '',
        'players': len(d.get('players_list') or d.get('standings') or []),
    }


def main():
    done = converted_ids()
    seen = load_seen()
    # The window anchors on REAL events only: probed-but-missing ids must not
    # push it forward, or unfinished business falls out of the lookback
    # (2026-09-28: 654/659 were skipped exactly this way).
    real = done | {t for t, v in seen.items()
                   if v.get('status') in ('open', 'finished')}
    hi = max(real, default=590)
    pending = {t for t, v in seen.items()
               if v.get('status') in ('open', 'error', 'finished')}
    candidates = sorted(set(range(max(hi - LOOKBACK, 400),
                                  hi + LOOKAHEAD + 1)) | pending)

    n_converted = 0
    for tid in candidates:
        if tid in done:
            continue
        cached = seen.get(tid)
        # 'missing' and skip-named finished events stay settled; anything
        # open or errored gets probed again.
        if cached and cached.get('status') == 'missing':
            continue
        if not cached or cached.get('status') != 'finished':
            fresh = probe(tid)
            # A transient fetch failure must not clobber real knowledge
            # (a probe flake once turned 'open' Torneo Pavia into 'missing').
            if (fresh.get('status') in ('missing', 'error')
                    and cached and cached.get('status') in ('open', 'finished')):
                print(f'  {tid}: probe failed, keeping status '
                      f'{cached.get("status")}: {cached.get("name", "")}')
                continue
            cached = fresh
            seen[tid] = cached
        if cached.get('status') != 'finished':
            print(f'  {tid}: {cached.get("status")} {cached.get("name", "")}')
            continue
        name = cached.get('name', '')
        if SKIP_NAME.search(name):
            print(f'  {tid}: SKIP (name rule): {name}')
            continue
        if (cached.get('players') or 0) < 2:
            print(f'  {tid}: SKIP (<2 players): {name}')
            continue
        # convert() loads the fetch cache; re-probe if it is not on disk
        # (e.g. status came from a previous run). A failed re-probe keeps the
        # 'finished' status so the next run tries again.
        if not os.path.exists(os.path.join(ROOT, f'tournament_{tid}.json')):
            fresh = probe(tid)
            if fresh.get('status') != 'finished':
                print(f'  {tid}: re-probe failed ({fresh.get("status")}), '
                      f'will retry: {name}')
                continue
            cached = fresh
            seen[tid] = cached
        print(f'  {tid}: converting finished event: {name}')
        from ftd_to_elo import convert
        try:
            out = convert(tid, synthetic_ids=True)
            print(f'    -> {out}')
            n_converted += 1
        except Exception as e:
            print(f'    FAILED: {e}')

    save_seen(seen)
    print(f'CONVERTED {n_converted}')


if __name__ == '__main__':
    main()
