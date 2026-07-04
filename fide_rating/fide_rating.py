"""
Apply the FIDE chess rating system to the Belgian Othello game pool.

Differences from the Jech/Bradley-Terry approach:
- INCREMENTAL: each game updates ratings in chronological order (vs MLE on full pool)
- Game order matters
- K-factor depends on the player's current rating + experience:
    K=40 for players with <30 rated games ("new")
    K=20 for players with rated games >=30 and rating <2400
    K=10 once a player has reached rating 2400 (sticky)
- Expected score: E = 1 / (1 + 10^((R_opp - R_self) / 400))
- New player initial rating: average opponent rating in first event +/- performance bonus
  (we'll use a simpler bootstrap: start at 1500, K=40 absorbs early adjustments)

Output: same structure as bel_rating.json so we can reuse the HTML.
"""
import os, re, sys, json, math
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bel_rating import (
    parse_joueurs, EXTRACT_DIR, parse_elo_file, parse_date,
    parse_ranglijsten_residents, collect_ftd_games,
    parse_dan_file, dan_at_snapshot, build_tournament_snapshots,
    collect_tournament_standings, find_sccs_above_threshold,
    BASE,
)

INITIAL_RATING = 1500
NEW_PLAYER_THRESHOLD = 30  # games before "established"
HIGH_RATING_FLOOR = 2400   # rating at which K stays at 10 forever


def k_factor(rating, games_played, ever_reached_2400):
    """Standard FIDE K-factor logic."""
    if ever_reached_2400:
        return 10
    if games_played < NEW_PLAYER_THRESHOLD:
        return 40
    return 20


def expected_score(r_self, r_opp):
    """FIDE expected score formula."""
    return 1.0 / (1.0 + 10 ** ((r_opp - r_self) / 400.0))


def collect_all_games_chrono(joueurs, allowed_ids, ref_date):
    """Collect all games (WOF .ELO + FTD JSON) where both players are in allowed_ids,
    dated on or before ref_date. Returns list sorted by date ascending.
    Date comparison uses .date() (day-level) so timestamped FTD games are not
    inadvertently excluded by a midnight ref_date."""
    ref_day = ref_date.date()
    games = []
    for root, _, files in os.walk(EXTRACT_DIR):
        for fname in files:
            if not fname.endswith('.ELO'):
                continue
            path = os.path.join(root, fname)
            date_str, file_games = parse_elo_file(path)
            dt = parse_date(date_str) if date_str else None
            if dt and dt.date() > ref_day:
                continue
            for a, b, res in file_games:
                if a in allowed_ids and b in allowed_ids:
                    games.append({'date': dt, 'a': a, 'b': b, 'result': res})

    # Add FTD-only games (after WOF's latest date)
    wof_latest = max((g['date'] for g in games if g['date']), default=None)
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fname in os.listdir(base):
        m = re.match(r'tournament_(\d+)\.json$', fname)
        if not m:
            continue
        ftd_games = collect_ftd_games(os.path.join(base, fname), joueurs, allowed_ids)
        if not ftd_games:
            continue
        ftd_date = ftd_games[0]['date']
        if ftd_date and ftd_date.date() > ref_day:
            continue
        if wof_latest and ftd_date and ftd_date.date() <= wof_latest.date():
            continue
        games.extend(ftd_games)

    # Sort chronologically; stable tie-breaking by player id pair
    games.sort(key=lambda g: (g['date'] or datetime.min, g['a'], g['b']))
    return games


def run_fide(games):
    """Process games in chronological order, return:
      - rating_history[pid] = list of (date_iso, rating, games_played)
      - final_state[pid] = (rating, games_played, ever_2400)
    """
    ratings = defaultdict(lambda: INITIAL_RATING)
    games_played = defaultdict(int)
    ever_2400 = defaultdict(bool)
    history = defaultdict(list)

    for g in games:
        a, b, res = g['a'], g['b'], g['result']
        ra, rb = ratings[a], ratings[b]
        ka = k_factor(ra, games_played[a], ever_2400[a])
        kb = k_factor(rb, games_played[b], ever_2400[b])
        ea = expected_score(ra, rb)
        eb = expected_score(rb, ra)
        if res == 1:
            sa, sb = 1.0, 0.0
        elif res == -1:
            sa, sb = 0.0, 1.0
        else:
            sa, sb = 0.5, 0.5
        new_ra = ra + ka * (sa - ea)
        new_rb = rb + kb * (sb - eb)
        ratings[a] = new_ra
        ratings[b] = new_rb
        games_played[a] += 1
        games_played[b] += 1
        if new_ra >= HIGH_RATING_FLOOR:
            ever_2400[a] = True
        if new_rb >= HIGH_RATING_FLOOR:
            ever_2400[b] = True
        date_iso = g['date'].strftime('%Y-%m-%d') if g['date'] else ''
        history[a].append((date_iso, new_ra, games_played[a]))
        history[b].append((date_iso, new_rb, games_played[b]))

    final = {pid: (r, games_played[pid], ever_2400[pid]) for pid, r in ratings.items()}
    return final, dict(history)


def main():
    print('Loading data...')
    joueurs = parse_joueurs()
    bel_ids = {pid for pid, p in joueurs.items() if p['country'] == 'BEL'}
    resident_ids = parse_ranglijsten_residents(joueurs)
    allowed_ids = bel_ids | resident_ids
    print(f'Pool: {len(allowed_ids)} (BEL: {len(bel_ids)}, residents: {len(resident_ids)})')

    print('\nLoading DAN history...')
    dan_latest, dan_history = parse_dan_file(joueurs)

    print('\nDetecting tournament dates for snapshots...')
    snapshot_defs = build_tournament_snapshots(min_year=2024, allowed_ids=allowed_ids)
    print(f'  {len(snapshot_defs)} snapshots: {snapshot_defs[0][1].date()} to {snapshot_defs[-1][1].date()}')

    # For each snapshot date, run FIDE up to that date and record state
    snapshots = []
    prev_cutoff = None
    for label, cutoff, country in snapshot_defs:
        games = collect_all_games_chrono(joueurs, allowed_ids, cutoff)
        final, history = run_fide(games)

        # Active = game in last 38 months
        cutoff_active = cutoff - timedelta(days=int(38 * 30.4375))
        active = set()
        for g in games:
            if g['date'] and g['date'] >= cutoff_active:
                active.add(g['a']); active.add(g['b'])

        # Compute "played_since_prev" for the diff column
        if prev_cutoff is None:
            played_at = None
        else:
            played_at = set()
            for g in games:
                if g['date'] and g['date'].date() == cutoff.date():
                    played_at.add(g['a']); played_at.add(g['b'])

        # Build rated player list (active, with some games)
        rated_list = []
        for pid in active:
            if pid not in final:
                continue
            rating, n_games, achieved_2400 = final[pid]
            jp = joueurs.get(pid, {})
            dan_at = dan_at_snapshot(dan_history.get(pid), cutoff.strftime('%Y-%m-%d'))
            if dan_at is None:
                dan_at = dan_latest.get(pid)
            entry = {
                'id': pid,
                'rating': round(rating, 1),
                'sigma': None,  # FIDE doesn't compute uncertainty
                'provisional': n_games < NEW_PLAYER_THRESHOLD,
                'firstname': jp.get('firstname', '?'),
                'surname': jp.get('surname', '?'),
                'country': jp.get('country', '???'),
                'dan': dan_at,
                'games_played': n_games,
            }
            if played_at is not None:
                entry['played_since_prev'] = pid in played_at
            rated_list.append(entry)
        rated_list.sort(key=lambda x: -x['rating'])

        # Standings for the tournament summary card
        snap_iso = cutoff.strftime('%Y-%m-%d')
        standings = collect_tournament_standings(snap_iso, country, allowed_ids, joueurs)

        snap = {
            'label': label,
            'ref_date': snap_iso,
            'year': cutoff.year,
            'country': country,
            'total_games': len(games),
            'total_active': len(active),
            'total_rated': len(rated_list),
            'total_unrated': 0,
            'players': rated_list,
            'unrated': [],
            'standings': standings,
        }
        snapshots.append(snap)
        prev_cutoff = cutoff
        top = rated_list[:3]
        top_str = ', '.join(f'{p["firstname"]} {p["surname"].title()}={p["rating"]:.0f}' for p in top)
        print(f'  {snap_iso}  {label[:40]:40s} top3: {top_str}')

    # Biggest movers per snapshot (vs previous)
    for i, snap in enumerate(snapshots):
        if i == 0:
            snap['biggest_movers'] = {}
            continue
        prev = snapshots[i - 1]
        prev_lookup = {p['id']: p['rating'] for p in prev['players']}
        gainers, losers = [], []
        for p in snap['players']:
            if not p.get('played_since_prev'):
                continue
            old = prev_lookup.get(p['id'])
            if old is None:
                continue
            d = p['rating'] - old
            entry = {'id': p['id'], 'name': f"{p['firstname']} {p['surname'].title()}",
                     'rating': p['rating'], 'diff': round(d, 1)}
            if d > 0:
                gainers.append(entry)
            elif d < 0:
                losers.append(entry)
        gainers.sort(key=lambda x: -x['diff'])
        losers.sort(key=lambda x: x['diff'])
        snap['biggest_movers'] = {
            'top_gainers': gainers[:3],
            'top_losers': losers[:3],
        }

    output = {
        'total_pool': len(allowed_ids),
        'algorithm': 'FIDE Elo (incremental, K=40/20/10)',
        'snapshots': snapshots,
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fide_rating.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f'\nSaved {out_path} with {len(snapshots)} snapshots')


if __name__ == '__main__':
    main()
