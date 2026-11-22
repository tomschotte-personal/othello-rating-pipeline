"""XOT world ranking — strict-FIDE Elo using ONLY the 17 known XOT tournaments.

Scale: shift-1800 (INITIAL_RATING = PRIOR_RATING = 1800). K=40/20/10 with the
two-pass bootstrap. Operates on .ELO files in xot_data/, independent from the
standard-rules ranking pipeline.

Output: xot_rating.json (player list + tournament list + per-player game log).
"""
import os, sys, io, json, time, argparse
from datetime import datetime
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(BASE))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import fide_rating, world_fide
fide_rating.INITIAL_RATING = 1800
world_fide.INITIAL_RATING = 1800
world_fide.PRIOR_RATING = 1800

from bel_rating import parse_joueurs, parse_elo_file
from world_fide import (
    pass1_seed_ratings, bootstrap_initial_ratings,
    compute_for_date, get_program_ids,
)

XOT_DIR = os.path.join(os.path.dirname(BASE), 'xot_data')
OUT_JSON = os.path.join(BASE, 'xot_rating.json')


def load_roster():
    """id -> (surname, firstname, country) from the xot_data roster lines.

    Players without a WOF id (synthetic 99xxxxx) or not yet in joueurs.txt
    only carry their name there; never emit "? ?" when the file knows."""
    roster = {}
    for fname in os.listdir(XOT_DIR):
        if not fname.endswith('.ELO'):
            continue
        with open(os.path.join(XOT_DIR, fname), encoding='utf-8', errors='replace') as f:
            for line in f:
                if not line.startswith('%_%'):
                    continue
                parts = [x.strip() for x in line[3:].split(',')]
                if len(parts) >= 4:
                    try:
                        roster.setdefault(int(parts[0]), (parts[1], parts[2], parts[3]))
                    except ValueError:
                        pass
    return roster


def player_name(pid, joueurs, roster):
    jp = joueurs.get(pid, {})
    sn, fn, co = jp.get('surname', '?'), jp.get('firstname', '?'), jp.get('country', '???')
    if (sn or '?').strip() in ('', '?') and pid in roster:
        sn, fn = roster[pid][0], roster[pid][1]
        if (co or '?').strip() in ('', '?', '???'):
            co = roster[pid][2]
    return sn, fn, co


def parse_date(s):
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%Y/%m/%d'):
        try: return datetime.strptime(s.strip(), fmt)
        except (ValueError, AttributeError): continue
    return None


def collect_xot_games(exclude_pids=None):
    """Walk xot_data/ and return all XOT games chronologically."""
    exclude_pids = exclude_pids or set()
    games = []
    tournaments_seen = []
    for fname in sorted(os.listdir(XOT_DIR)):
        if not fname.endswith('.ELO'):
            continue
        path = os.path.join(XOT_DIR, fname)
        date_str, file_games = parse_elo_file(path)
        dt = parse_date(date_str) if date_str else None
        tname = fname[:-4]
        n_added = 0
        for a, b, res in file_games:
            if a in exclude_pids or b in exclude_pids:
                continue
            games.append({'date': dt, 'a': a, 'b': b, 'result': res, 't': tname})
            n_added += 1
        tournaments_seen.append((tname, dt, n_added))
        print(f'  {tname[:50]:50}  date={dt and dt.date()}  games={n_added}')
    games.sort(key=lambda g: (g['date'] or datetime(1900,1,1), g['t']))
    return games, tournaments_seen


def main():
    print('=== XOT world rating ===')
    print(f'Scale: shift-1800 (INITIAL={world_fide.INITIAL_RATING}, PRIOR={world_fide.PRIOR_RATING})')
    joueurs = parse_joueurs()
    program_ids = get_program_ids(joueurs)
    games, tournaments = collect_xot_games(exclude_pids=program_ids)
    print(f'Total XOT games: {len(games)}')
    print(f'Total XOT tournaments: {len(tournaments)}')

    # Two-pass bootstrap on JUST the XOT games
    pass1_seed_ratings(games)
    master_initial = bootstrap_initial_ratings(games)
    print(f'Bootstrap initial ratings: {len(master_initial)} players')

    # Compute final ratings at "now"
    ref = datetime.now()
    out = compute_for_date(joueurs, games, ref, OUT_JSON, strict_fide=True,
                           log_from_date=None, master_initial=master_initial)
    state = out['_state']
    roster = load_roster()

    # Inject XOT-specific metadata
    with open(OUT_JSON, encoding='utf-8') as f:
        data = json.load(f)
    data['xot'] = True
    data['xot_tournaments'] = [
        {'name': t, 'date': d.strftime('%Y-%m-%d') if d else '', 'games': n}
        for t, d, n in tournaments
    ]
    # For each player, attach the list of XOT tournaments they appeared in
    per_player_tourns = defaultdict(set)
    for g in games:
        per_player_tourns[g['a']].add(g['t'])
        per_player_tourns[g['b']].add(g['t'])
    for p in data['players']:
        p['tournaments'] = sorted(per_player_tourns.get(p['id'], []))
        # XOT pool is small and young: provisional until 30 XOT games
        # (agreed threshold; the standard 9 is far too lax here).
        p['provisional'] = p.get('games_played', 0) < 30
        p['surname'], p['firstname'], p['country'] = player_name(p['id'], joueurs, roster)
    # Inactive cohort (no XOT game in the 38-month window): final ratings,
    # frozen after their last game. xot_inactive_list.py prints these.
    active_ids = {p['id'] for p in data['players']}
    inactive = []
    for pid, dt in state['last_played'].items():
        if pid in active_ids:
            continue
        sn, fn, co = player_name(pid, joueurs, roster)
        n = state['games_played'].get(pid, 0)
        inactive.append({
            'id': pid, 'rating': round(state['ratings'][pid], 1),
            'games_played': n, 'firstname': fn, 'surname': sn, 'country': co,
            'provisional': n < 30, 'last_played': dt.strftime('%Y-%m-%d'),
            'tournaments': sorted(per_player_tourns.get(pid, [])),
        })
    inactive.sort(key=lambda p: -p['rating'])
    data['inactive'] = inactive
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

    # Print top 20
    print('\nTop 20 XOT players (shift-1800 scale):')
    for i, p in enumerate(data['players'][:20], 1):
        prov = ' (prov)' if p.get('provisional') else ''
        print(f'  {i:>2}.  {p["rating"]:.1f}  {p["firstname"]} {p["surname"]:25}  [{p["country"]}]  g={p["games_played"]}{prov}')


if __name__ == '__main__':
    main()
