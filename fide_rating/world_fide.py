"""
Apply FIDE Elo to ALL global Othello games with two-pass bootstrap.

Pass 1: everyone starts at 1500, K=40 throughout, full chronological run.
        → produces "seed" ratings used to compute initial bootstrap ratings.

Pass 2: for each player, initial rating = FIDE performance rating of their
        first N=9 games, using opponents' Pass-1 ratings.
        Formula: R_init = avg_opp + dp(p)
        where dp(p) = 400 * log10(p/(1-p)), capped at ±800.

Pass 3: full chronological run from these bootstrap initials, K=40/20/10.

Active filter: game in last 38 months from ref date (2026-04-14).
"""
import os, re, sys, json, time, math
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bel_rating import (
    parse_joueurs, EXTRACT_DIR, parse_elo_file, parse_date, BASE,
)
from fide_rating import (
    INITIAL_RATING, NEW_PLAYER_THRESHOLD, HIGH_RATING_FLOOR,
    k_factor, expected_score,
)

BOOTSTRAP_GAMES = 9
# Bayesian prior: phantom games at 1500/50% to shrink small-sample bootstraps.
# Without this, a 1-0 player gets avg_opp+800 from the dp cap.
PRIOR_GAMES = 9
PRIOR_RATING = 1500
PRIOR_SCORE = 0.5


def collect_all_games_global_chrono(exclude_pids=None):
    """Walk ALL .ELO files, return list of games sorted by date.
    Each game has a 't' field with the tournament name (filename without .ELO).

    exclude_pids: optional set of player IDs to filter out — any game involving
    one of these IDs is skipped. Use for filtering out computer programs (which
    are not in the current joueurs.txt and shouldn't pollute the human rating).
    """
    exclude_pids = exclude_pids or set()
    games = []
    files_processed = 0
    skipped = 0
    for root, _, files in os.walk(EXTRACT_DIR):
        for fname in files:
            if not fname.endswith('.ELO'):
                continue
            path = os.path.join(root, fname)
            files_processed += 1
            tournament = fname[:-4]
            date_str, file_games = parse_elo_file(path)
            dt = parse_date(date_str) if date_str else None
            for a, b, res in file_games:
                if a in exclude_pids or b in exclude_pids:
                    skipped += 1
                    continue
                games.append({'date': dt, 'a': a, 'b': b, 'result': res, 't': tournament})
    suffix = f' (skipped {skipped} games involving {len(exclude_pids)} excluded IDs)' if exclude_pids else ''
    print(f'  Processed {files_processed} .ELO files, {len(games)} games{suffix}')
    games.sort(key=lambda g: (g['date'] or datetime.min, g['a'], g['b']))
    return games


def get_program_ids(joueurs=None):
    """Return the set of player IDs that appear in games but are missing from
    joueurs.txt. These are (in practice) computer programs WOF removed from
    the active roster. Use as `exclude_pids` to filter them out.

    IDs in the 9,900,000+ range are exempt: that's our reserved synthetic range
    for players who don't have a WOF ID yet (e.g., a first national tournament
    of an entirely-new country). See ftd_to_elo.convert(synthetic_ids=True)."""
    if joueurs is None:
        from bel_rating import parse_joueurs
        joueurs = parse_joueurs()
    joueurs_ids = set(joueurs.keys())
    seen = set()
    for root, _, files in os.walk(EXTRACT_DIR):
        for fname in files:
            if not fname.endswith('.ELO'):
                continue
            _, file_games = parse_elo_file(os.path.join(root, fname))
            for a, b, _ in file_games:
                seen.add(a); seen.add(b)
    return {pid for pid in (seen - joueurs_ids) if pid < 9_900_000}


def pass1_seed_ratings(games):
    """Pass 1: everyone starts at 1500, K=40 throughout.
    Annotates each game with the opponents' ratings GOING INTO the game (ra_before/rb_before).
    Returns final ratings (for diagnostics)."""
    ratings = defaultdict(lambda: INITIAL_RATING)
    for g in games:
        a, b, res = g['a'], g['b'], g['result']
        ra, rb = ratings[a], ratings[b]
        g['ra_before'] = ra  # causal: opponent rating at time of game
        g['rb_before'] = rb
        ea = expected_score(ra, rb)
        eb = expected_score(rb, ra)
        if res == 1: sa, sb = 1.0, 0.0
        elif res == -1: sa, sb = 0.0, 1.0
        else: sa, sb = 0.5, 0.5
        ratings[a] = ra + 40 * (sa - ea)
        ratings[b] = rb + 40 * (sb - eb)
    return dict(ratings)


def fide_dp(p):
    """FIDE performance bonus from score percentage. Capped at +/-800."""
    if p >= 1.0:
        return 800.0
    if p <= 0.0:
        return -800.0
    return 400.0 * math.log10(p / (1.0 - p))


def bootstrap_initial_ratings(games, n_games=BOOTSTRAP_GAMES, anchors=None):
    """Pass 2: initial rating = FIDE performance rating of first N games,
    using opponents' Pass-1 ratings AT THE TIME OF EACH GAME (causal).
    Requires pass1 to have annotated games with ra_before / rb_before.

    anchors: optional {pid: rating} for players we want to lock at a known
    seed rating (e.g., pre-1991 champions who would otherwise bootstrap
    too low because the dataset only starts in 1991). Overrides the PR
    computation for the listed players.
    """
    first_games = defaultdict(list)  # pid -> list of (opp_rating_at_time, score)
    for g in games:
        a, b, res = g['a'], g['b'], g['result']
        if res == 1: sa, sb = 1.0, 0.0
        elif res == -1: sa, sb = 0.0, 1.0
        else: sa, sb = 0.5, 0.5
        if len(first_games[a]) < n_games:
            first_games[a].append((g['rb_before'], sa))
        if len(first_games[b]) < n_games:
            first_games[b].append((g['ra_before'], sb))

    initial = {}
    for pid, results in first_games.items():
        opps_sum = sum(opp_r for opp_r, _ in results)
        scores_sum = sum(s for _, s in results)
        n = len(results)
        total_n = n + PRIOR_GAMES
        avg_opp = (opps_sum + PRIOR_GAMES * PRIOR_RATING) / total_n
        p = (scores_sum + PRIOR_GAMES * PRIOR_SCORE) / total_n
        initial[pid] = avg_opp + fide_dp(p)
    # Apply anchor overrides last so they win regardless of PR.
    if anchors:
        for pid, r in anchors.items():
            initial[pid] = float(r)
    return initial


def compute_for_date(joueurs, all_games, REF, out_path, strict_fide=False,
                     log_from_date=None, master_initial=None):
    """Run the full 3-pass FIDE rating with given ref date.

    log_from_date: if set, attach per-player per-game logs for games on/after this date.
    master_initial: optional precomputed bootstrap dict (pid -> rating) derived from the
                    FULL game history. Pass this for stable historical snapshots — without
                    it, recently-debuted players have a snapshot-dependent bootstrap which
                    propagates retroactive drift to opponents' historical ratings.
    """
    games = [g for g in all_games if g['date'] and g['date'] <= REF]
    print(f'  Games on/before {REF.date()}: {len(games)}  strict_fide={strict_fide}  '
          f'log_from={log_from_date.date() if log_from_date else "(none)"}  '
          f'master_init={"yes" if master_initial else "no"}')
    if master_initial is not None:
        # Still annotate ra_before/rb_before so other code paths can use them.
        pass1_seed_ratings(games)
        initial = master_initial
    else:
        pass1_seed_ratings(games)
        initial = bootstrap_initial_ratings(games)
    ratings = {}
    games_played = defaultdict(int)
    ever_2400 = defaultdict(bool)
    last_played = {}
    game_log = defaultdict(list)  # pid -> [{d, t, o, s, delta}, ...]

    def get_rating(pid):
        if pid not in ratings:
            ratings[pid] = initial.get(pid, INITIAL_RATING)
        return ratings[pid]

    for g in games:
        a, b, res = g['a'], g['b'], g['result']
        ra = get_rating(a); rb = get_rating(b)
        ka = k_factor(ra, games_played[a], ever_2400[a])
        kb = k_factor(rb, games_played[b], ever_2400[b])
        ea = expected_score(ra, rb); eb = expected_score(rb, ra)
        if res == 1: sa, sb = 1.0, 0.0
        elif res == -1: sa, sb = 0.0, 1.0
        else: sa, sb = 0.5, 0.5
        a_graduated = (not strict_fide) or games_played[a] >= BOOTSTRAP_GAMES
        b_graduated = (not strict_fide) or games_played[b] >= BOOTSTRAP_GAMES
        delta_a = ka * (sa - ea) if a_graduated else 0.0
        delta_b = kb * (sb - eb) if b_graduated else 0.0

        if log_from_date and g['date'] and g['date'] > log_from_date:
            t = g.get('t', '')
            d_iso = g['date'].strftime('%Y-%m-%d')
            game_log[a].append({'d': d_iso, 't': t, 'o': b, 's': sa, 'dr': round(delta_a, 2)})
            game_log[b].append({'d': d_iso, 't': t, 'o': a, 's': sb, 'dr': round(delta_b, 2)})

        ratings[a] = ra + delta_a
        ratings[b] = rb + delta_b
        games_played[a] += 1; games_played[b] += 1
        if ratings[a] >= HIGH_RATING_FLOOR: ever_2400[a] = True
        if ratings[b] >= HIGH_RATING_FLOOR: ever_2400[b] = True
        if g['date']:
            last_played[a] = g['date']; last_played[b] = g['date']

    cutoff = REF - timedelta(days=int(38 * 30.4375))
    active = {pid for pid, dt in last_played.items() if dt >= cutoff}
    players = []
    for pid in active:
        jp = joueurs.get(pid, {})
        n_games = games_played[pid]
        entry = {
            'id': pid, 'rating': round(ratings[pid], 1),
            'initial': round(initial.get(pid, INITIAL_RATING), 1),
            'games_played': n_games,
            'firstname': jp.get('firstname', '?'),
            'surname': jp.get('surname', '?'),
            'country': jp.get('country', '???'),
            'provisional': n_games < NEW_PLAYER_THRESHOLD,
            'last_played': last_played[pid].strftime('%Y-%m-%d'),
        }
        if log_from_date and pid in game_log:
            entry['log'] = game_log[pid]
        players.append(entry)
    players.sort(key=lambda p: -p['rating'])

    output = {
        'ref_date': REF.strftime('%Y-%m-%d'),
        'algorithm': f'FIDE Elo (two-pass bootstrap, causal)',
        'total_games': len(games),
        'total_rated': len(ratings),
        'total_active': len(active),
        'players': players,
    }
    if out_path:
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f'  Saved {out_path}: {len(active)} active, top {players[0]["rating"]:.0f}')
    # Expose state for downstream live updates
    output['_state'] = {
        'ratings': dict(ratings),
        'games_played': dict(games_played),
        'ever_2400': {pid: True for pid, v in ever_2400.items() if v},
        'last_played': last_played,
    }
    return output


def main():
    print('=== Step 1: Parse joueurs.txt ===')
    joueurs = parse_joueurs()
    print(f'  Players: {len(joueurs)}')

    print('\n=== Step 2: Collect all games chronologically ===')
    t0 = time.time()
    games = collect_all_games_global_chrono()
    print(f'  Done in {time.time()-t0:.1f}s')

    REF = datetime(2026, 5, 15)
    games = [g for g in games if g['date'] and g['date'] <= REF]
    print(f'  Games on/before {REF.date()}: {len(games)}')

    print('\n=== Step 3: Pass 1 (K=40 from 1500, full chronological run) ===')
    t0 = time.time()
    seed = pass1_seed_ratings(games)
    print(f'  Done in {time.time()-t0:.1f}s; {len(seed)} seed ratings')

    print(f'\n=== Step 4: Pass 2 (bootstrap initials from first {BOOTSTRAP_GAMES} games) ===')
    t0 = time.time()
    initial = bootstrap_initial_ratings(games)
    print(f'  Done in {time.time()-t0:.1f}s; {len(initial)} initial ratings')
    init_vals = list(initial.values())
    print(f'  Initial range: {min(init_vals):.0f} .. {max(init_vals):.0f}, '
          f'mean={sum(init_vals)/len(init_vals):.0f}')

    print('\n=== Step 5: Pass 3 (FIDE K=40/20/10 from bootstrap initials) ===')
    t0 = time.time()
    ratings = {}
    games_played = defaultdict(int)
    ever_2400 = defaultdict(bool)
    last_played = {}

    def get_rating(pid):
        if pid not in ratings:
            ratings[pid] = initial.get(pid, INITIAL_RATING)
        return ratings[pid]

    for g in games:
        a, b, res = g['a'], g['b'], g['result']
        ra = get_rating(a)
        rb = get_rating(b)
        ka = k_factor(ra, games_played[a], ever_2400[a])
        kb = k_factor(rb, games_played[b], ever_2400[b])
        ea = expected_score(ra, rb)
        eb = expected_score(rb, ra)
        if res == 1: sa, sb = 1.0, 0.0
        elif res == -1: sa, sb = 0.0, 1.0
        else: sa, sb = 0.5, 0.5
        ratings[a] = ra + ka * (sa - ea)
        ratings[b] = rb + kb * (sb - eb)
        games_played[a] += 1
        games_played[b] += 1
        if ratings[a] >= HIGH_RATING_FLOOR: ever_2400[a] = True
        if ratings[b] >= HIGH_RATING_FLOOR: ever_2400[b] = True
        if g['date']:
            last_played[a] = g['date']
            last_played[b] = g['date']
    print(f'  Done in {time.time()-t0:.1f}s; rated {len(ratings)} players')

    cutoff = REF - timedelta(days=int(38 * 30.4375))
    active = {pid for pid, dt in last_played.items() if dt >= cutoff}
    print(f'  Active (game since {cutoff.date()}): {len(active)}')

    players = []
    for pid in active:
        jp = joueurs.get(pid, {})
        rating = ratings[pid]
        n_games = games_played[pid]
        players.append({
            'id': pid,
            'rating': round(rating, 1),
            'initial': round(initial.get(pid, INITIAL_RATING), 1),
            'games_played': n_games,
            'firstname': jp.get('firstname', '?'),
            'surname': jp.get('surname', '?'),
            'country': jp.get('country', '???'),
            'provisional': n_games < NEW_PLAYER_THRESHOLD,
            'last_played': last_played[pid].strftime('%Y-%m-%d'),
        })
    players.sort(key=lambda p: -p['rating'])

    output = {
        'ref_date': REF.strftime('%Y-%m-%d'),
        'algorithm': f'FIDE Elo (two-pass bootstrap: K=40 seed + first-{BOOTSTRAP_GAMES}-games performance rating + K=40/20/10)',
        'total_games': len(games),
        'total_rated': len(ratings),
        'total_active': len(active),
        'players': players,
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'world_fide.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f'\nSaved {out_path}')

    print('\nTop 20 (active):')
    for i, p in enumerate(players[:20], 1):
        prov = ' (prov)' if p['provisional'] else ''
        print(f'  {i:>3}. {p["rating"]:>5.0f}  init={p["initial"]:>4.0f}  '
              f'{p["games_played"]:>4}g  [{p["country"]}]  '
              f'{p["firstname"]} {p["surname"].title()}{prov}')


if __name__ == '__main__':
    main()
