"""Compute LIVE FIDE rating by overlaying an ongoing FTD tournament on the May 15 baseline.

Workflow:
  1. Load May 15 baseline state (re-run compute_for_date up to that date in memory).
  2. Fetch/load FTD tournament JSON (cached at C:/Claude/o_dan/tournament_{id}.json).
  3. Match FTD players to WOF IDs by name.
  4. For each completed game in the tournament, apply strict-FIDE K-factor update.
  5. Save world_fide_live.json with the new ratings + a per-player log of EC games.
"""
import os, sys, re, json, time
from datetime import datetime, timedelta
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(BASE))

# === SHIFT-1800 PATCH ===
import fide_rating, world_fide
fide_rating.INITIAL_RATING = 1800
world_fide.INITIAL_RATING = 1800
world_fide.PRIOR_RATING = 1800
# ========================

from bel_rating import parse_joueurs, parse_elo_file, EXTRACT_DIR
from world_fide import (
    collect_all_games_global_chrono, compute_for_date,
    pass1_seed_ratings, bootstrap_initial_ratings, get_program_ids,
    BOOTSTRAP_GAMES, HIGH_RATING_FLOOR, k_factor, expected_score, fide_dp,
)

PROJECT = os.path.dirname(BASE)
BASELINE_DATE = datetime(2026, 6, 30)


def fetch_tournament_full(tournament_id):
    """Fetch tournament: captures players-list, standings, rounds, and info.
    Uses Playwright to intercept the websocket frame, then directly hijacks the
    same socket from a script context to request each round explicitly."""
    from playwright.sync_api import sync_playwright
    print(f'Fetching tournament {tournament_id} from flipthedisc.com...')
    msgs = []
    ws_ref = {'ws': None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def on_ws(ws):
            ws_ref['ws'] = ws
            ws.on('framereceived', lambda payload: msgs.append(payload) if isinstance(payload, str) and '42[' in payload else None)
        page.on('websocket', on_ws)

        page.goto(f'https://flipthedisc.com/live/{tournament_id}', wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(3000)
        # Each tab click triggers a different socket event:
        #   Players -> otb-players-list (with wof_ids!)
        #   Info    -> otb-info (current_round, name, ...)
        #   Rounds  -> initial otb-get-round
        # NOTE: when tournament has wrapped up the 'Rounds' tab can be disabled;
        # treat all clicks as best-effort.
        for label in ['Players', 'Info', 'Rounds']:
            try:
                btn = page.locator(f'button:has-text("{label}")').first
                if btn.is_enabled():
                    btn.click()
                    page.wait_for_timeout(2000)
            except Exception:
                pass

        # Click every round button. FTD uses class="toggle-round" with value="N"
        # where N is 1..11 for Swiss + 108=SF / 109=3-4 / 110=F for knockouts.
        round_btns = page.locator('button.toggle-round')
        n = round_btns.count()
        values = []
        for i in range(n):
            try:
                v = round_btns.nth(i).get_attribute('value')
                if v: values.append(v)
            except Exception:
                pass
        # Click each button (locate by value to be robust against text/disabled state).
        for v in values:
            sel = page.locator(f'button.toggle-round[value="{v}"]')
            try:
                if not sel.is_enabled():
                    continue
                pre = len(msgs)
                sel.click()
                for _ in range(16):
                    page.wait_for_timeout(250)
                    if any('otb-get-round' in m for m in msgs[pre:]):
                        break
            except Exception:
                pass
        browser.close()

    standings = None
    rounds_raw = []
    players_list = None
    info = None
    for m in msgs:
        mm = re.match(r'42\["([^"]+)",(.+)\]$', m, re.DOTALL)
        if not mm:
            continue
        event = mm.group(1)
        try:
            data = json.loads('[' + mm.group(2) + ']')
        except Exception:
            continue
        if event == 'new-standings' and standings is None:
            standings = data[0]
        elif event == 'otb-players-list' and players_list is None:
            players_list = data[0]
        elif event == 'otb-get-round':
            rounds_raw.append(data[0])
        elif event == 'otb-info' and info is None:
            info = data[0]

    # Deduplicate rounds. Pairings may be:
    #   - Swiss rounds: [[p1, p2], [p3, p4], ...]
    #   - Playoff rounds: ["open", [p1, p2], "open", [p3, p4], ...]
    # So iterate until we find an actual pair (a list whose first item is a dict).
    def _first_player_dict(rd):
        if not isinstance(rd, dict):
            return None
        pairings = rd.get('pairing') or []
        if not isinstance(pairings, list):
            return None
        for pair in pairings:
            if isinstance(pair, list) and pair and isinstance(pair[0], dict):
                return pair[0]
        return None

    seen = set()
    rounds = []
    for rd in rounds_raw:
        p1 = _first_player_dict(rd)
        if p1 is None:
            continue
        ts = p1.get('roundStarted', '')
        if ts not in seen:
            seen.add(ts); rounds.append(rd)
    # Order: Swiss rounds 1..11 by currentRound (1, 2, ..., 11), then
    # knockouts in the FTD-defined logical order: 108 (SF), 109 (3/4), 110 (F).
    rounds.sort(key=lambda rd: rd.get('currentRound') or 0)

    print(f'  Found: players={len(players_list or [])}  standings={len(standings or [])}  '
          f'rounds={len(rounds)}  info={"yes" if info else "no"}')
    return {
        'players_list': players_list or [],
        'standings': standings or [],
        'rounds': rounds,
        'info': info or {},
    }


def fetch_or_load_tournament(tournament_id, force_refresh=False):
    """Fetch tournament from FTD or load cached copy.

    A failed refresh falls back to the cached copy (if any) instead of raising —
    one unreachable FTD page must not abort the whole publish cycle."""
    cache = os.path.join(PROJECT, f'tournament_{tournament_id}.json')
    if force_refresh or not os.path.exists(cache):
        try:
            d = fetch_tournament_full(tournament_id)
            with open(cache, 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False)
            print(f'  Cached {cache}')
        except Exception as e:
            if os.path.exists(cache):
                print(f'  Refresh of {tournament_id} failed ({str(e)[:80]}) — using cached copy')
            else:
                print(f'  Refresh of {tournament_id} failed ({str(e)[:80]}) — no cache, using empty stub')
                d = {'players_list': [], 'standings': [], 'rounds': [], 'info': {}}
                with open(cache, 'w', encoding='utf-8') as f:
                    json.dump(d, f, ensure_ascii=False)
    else:
        print(f'  Loading {cache}')
    with open(cache, encoding='utf-8') as f:
        d = json.load(f)
    # Back-compat: old caches may not have players_list / info
    d.setdefault('players_list', [])
    d.setdefault('info', {})
    return d


ISO2_TO_WOF3 = {
    'BE':'BEL','NL':'NLD','GB':'GBR','FR':'FRA','DE':'DEU','IT':'ITA','ES':'ESP','PL':'POL',
    'SE':'SWE','NO':'NOR','DK':'DNK','FI':'FIN','US':'USA','JP':'JPN','TH':'THA','SG':'SGP',
    'HK':'HKG','CN':'CHN','CZ':'CZE','AT':'AUT','AU':'AUS','CA':'CAN','KR':'KOR','IN':'IND',
    'BR':'BRA','PT':'PRT','CH':'CHE','IE':'IRL','IL':'ISR','AR':'ARG','NZ':'NZL','RU':'RUS',
    'UA':'UKR','TR':'TUR','GR':'GRC','MX':'MEX','TW':'TWN','HU':'HUN','RO':'ROU','MN':'MNG',
    'EE':'EST','LT':'LTU','LV':'LVA','IR':'IRN','KZ':'KAZ','LK':'LKA','MY':'MYS','VN':'VNM',
    'ZA':'ZAF','CI':'CIV','DZ':'DZA','EG':'EGY','GT':'GTM','UY':'URY',
}


def match_ftd_to_wof(entries, joueurs):
    """Map FTD player id -> WOF player id.
    Unmatched players (no wof_id, not found by name) are assigned a SYNTHETIC negative ID
    (-ftd_id) so they can still participate in the rating with a provisional bootstrap.
    Returns (ftd_to_wof, unmatched_info_list, new_player_records)
      new_player_records: {synthetic_id: {'firstname','surname','country'}} ready to inject into joueurs
    """
    wof_full = {}
    wof_by_surname = defaultdict(list)
    for pid, jp in joueurs.items():
        fn = jp.get('firstname', '').lower().strip()
        sn = jp.get('surname', '').lower().strip()
        if not fn or not sn:
            continue
        wof_full[f'{fn} {sn}'] = pid
        wof_by_surname[sn].append((pid, fn))

    ftd_to_wof = {}
    unmatched_info = []
    new_player_records = {}
    for s in entries:
        fid = s.get('player_id') or s.get('id')
        if fid is None:
            continue
        wof_id = s.get('wof_id')
        if wof_id and wof_id in joueurs:
            ftd_to_wof[fid] = wof_id
            continue
        sn_raw = s.get('surname') or ''
        fn_raw = s.get('name') or ''
        sn = sn_raw.lower().strip()
        fn = fn_raw.lower().strip()
        full = f'{fn} {sn}'
        if full in wof_full:
            ftd_to_wof[fid] = wof_full[full]
            continue
        candidates = wof_by_surname.get(sn, [])
        match = None
        for pid, wfn in candidates:
            if wfn == fn:
                match = pid; break
            if fn and (wfn.startswith(fn.split()[0]) or fn.startswith(wfn.split()[0])):
                match = pid; break
        if match:
            ftd_to_wof[fid] = match
            continue
        # Truly new: assign synthetic ID
        synth_id = -int(fid)
        ftd_to_wof[fid] = synth_id
        cc_iso2 = (s.get('country_code') or '').upper().strip()
        cc_wof = ISO2_TO_WOF3.get(cc_iso2, cc_iso2 or '???')
        new_player_records[synth_id] = {
            'firstname': fn_raw.strip(),
            'surname': sn_raw.strip(),
            'country': cc_wof,
        }
        unmatched_info.append((fid, sn_raw, fn_raw))
    return ftd_to_wof, unmatched_info, new_player_records


_OTH_DIRS = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]

def othello_score_from_transcript(transcript):
    """Replay an Othello transcript ('c4e3...') and return (black_count, white_count).
    First move is BLACK. Returns (None, None) if transcript invalid."""
    if not transcript or len(transcript) < 2:
        return None, None
    # 1=black, -1=white, 0=empty. Standard start.
    board = [[0]*8 for _ in range(8)]
    board[3][3] = -1; board[4][4] = -1
    board[3][4] = 1;  board[4][3] = 1
    color = 1  # black to move
    moves = [transcript[i:i+2].lower() for i in range(0, len(transcript), 2)]
    for mv in moves:
        if len(mv) != 2: continue
        c = ord(mv[0]) - ord('a')
        r = ord(mv[1]) - ord('1')
        if not (0 <= c < 8 and 0 <= r < 8):
            continue
        if mv == 'ps':  # pass — switch color, don't place
            color = -color
            continue
        # Find flips
        flips = []
        for dc, dr in _OTH_DIRS:
            nc, nr = c + dc, r + dr
            line = []
            while 0 <= nc < 8 and 0 <= nr < 8 and board[nr][nc] == -color:
                line.append((nc, nr))
                nc += dc; nr += dr
            if line and 0 <= nc < 8 and 0 <= nr < 8 and board[nr][nc] == color:
                flips.extend(line)
        if not flips:
            # Invalid move; could be pass. Switch color and continue.
            color = -color
            continue
        board[r][c] = color
        for fc, fr in flips:
            board[fr][fc] = color
        color = -color
    black = sum(1 for row in board for v in row if v == 1)
    white = sum(1 for row in board for v in row if v == -1)
    return black, white


def extract_games(standings, rounds, ftd_to_wof):
    """Return list of completed games. result: 1 = a wins, -1 = a loses, 0 = draw.

    Two FTD formats:
      (a) Older tournaments: pairing has p1.result + p1.score (e.g., Zonhoven).
      (b) EOC and similar: result is null but p1.transcript is populated; we replay
          the game to determine the winner. Assumes p1 plays Black (i.e., p1 stores
          the transcript and makes the first move).
    """
    games = []
    for ri, rd in enumerate(rounds):
        if not isinstance(rd, dict):
            continue
        for pair in rd.get('pairing', []) or []:
            if not isinstance(pair, list) or len(pair) < 2:
                continue
            p1, p2 = pair[0], pair[1]
            if not isinstance(p1, dict) or not isinstance(p2, dict):
                continue
            id1, id2 = p1.get('id'), p2.get('id')
            if id1 is None or id2 is None:
                continue
            w1 = ftd_to_wof.get(id1)
            w2 = ftd_to_wof.get(id2)
            if w1 is None or w2 is None:
                continue

            r = p1.get('result')
            # FTD encoding:
            #   None -> game not played yet (skip)
            #   2    -> p1 wins
            #   1    -> draw
            #   0    -> p1 loses
            if r is None:
                continue
            if r == 2:
                res = 1
            elif r == 1:
                res = 0  # draw
            elif r == 0:
                res = -1
            else:
                continue

            started = (p1.get('roundStarted') or rd.get('roundStarted') or '')[:10]
            games.append({
                'a': w1, 'b': w2, 'result': res, 'round': ri + 1,
                'date': started,
            })
    return games


def apply_live(state, ec_games, ec_tournament_name='2026 European Championship',
               strict_fide=True, new_player_ids=None):
    """Apply EC games on top of baseline state. Returns updated state + per-player log.
    new_player_ids: synthetic IDs (negative) for unrated tournament participants. Their
    initial rating is computed as the FIDE performance rating of all their tournament
    games (with Bayesian prior), using opponents' BASELINE ratings."""
    ratings = dict(state['ratings'])
    games_played = defaultdict(int, state['games_played'])
    ever_2400 = defaultdict(bool, state['ever_2400'])
    last_played = dict(state['last_played'])
    game_log = defaultdict(list)
    new_player_ids = set(new_player_ids or [])

    # Pre-pass: bootstrap performance rating for each new player from their games
    # against opponents' BASELINE ratings (so the new player's rating is stable
    # within this run regardless of intra-tournament rating drift of opponents).
    new_player_results = defaultdict(list)  # synth_id -> [(opp_baseline_r, score), ...]
    for g in ec_games:
        a, b, res = g['a'], g['b'], g['result']
        if a in new_player_ids:
            opp_r = state['ratings'].get(b, 1800.0)
            sa = 1.0 if res == 1 else (0.0 if res == -1 else 0.5)
            new_player_results[a].append((opp_r, sa))
        if b in new_player_ids:
            opp_r = state['ratings'].get(a, 1800.0)
            sb = 1.0 if res == -1 else (0.0 if res == 1 else 0.5)
            new_player_results[b].append((opp_r, sb))
    PRIOR_GAMES, PRIOR_RATING, PRIOR_SCORE = 9, 1800.0, 0.5
    for npid, results in new_player_results.items():
        if not results:
            ratings[npid] = 1800.0
            continue
        opps_sum = sum(o for o, _ in results)
        scores_sum = sum(s for _, s in results)
        n = len(results)
        total_n = n + PRIOR_GAMES
        avg_opp = (opps_sum + PRIOR_GAMES * PRIOR_RATING) / total_n
        p = (scores_sum + PRIOR_GAMES * PRIOR_SCORE) / total_n
        ratings[npid] = avg_opp + fide_dp(p)

    for g in ec_games:
        a, b, res = g['a'], g['b'], g['result']
        ra = ratings.get(a, 1800.0)
        rb = ratings.get(b, 1800.0)
        ka = k_factor(ra, games_played[a], ever_2400[a])
        kb = k_factor(rb, games_played[b], ever_2400[b])
        ea = expected_score(ra, rb); eb = expected_score(rb, ra)
        if res == 1: sa, sb = 1.0, 0.0
        elif res == -1: sa, sb = 0.0, 1.0
        else: sa, sb = 0.5, 0.5
        # New (synthetic-id) players have their rating fixed at the bootstrap PR
        # for this whole tournament; only opponents update.
        a_grad = (a not in new_player_ids) and ((not strict_fide) or games_played[a] >= BOOTSTRAP_GAMES)
        b_grad = (b not in new_player_ids) and ((not strict_fide) or games_played[b] >= BOOTSTRAP_GAMES)
        delta_a = ka * (sa - ea) if a_grad else 0.0
        delta_b = kb * (sb - eb) if b_grad else 0.0
        t_name = g.get('t') or ec_tournament_name or ''
        game_log[a].append({'d': g['date'] or '', 't': t_name, 'o': b,
                            's': sa, 'dr': round(delta_a, 2), 'r': g['round']})
        game_log[b].append({'d': g['date'] or '', 't': t_name, 'o': a,
                            's': sb, 'dr': round(delta_b, 2), 'r': g['round']})
        ratings[a] = ra + delta_a
        ratings[b] = rb + delta_b
        games_played[a] += 1; games_played[b] += 1
        if ratings[a] >= HIGH_RATING_FLOOR: ever_2400[a] = True
        if ratings[b] >= HIGH_RATING_FLOOR: ever_2400[b] = True
        # Stamp last_played with the actual game date so the 'Active now' filter
        # can distinguish today's live events from older post-baseline overlays.
        g_date = g.get('date') or ''
        try:
            g_dt = datetime.strptime(g_date, '%Y-%m-%d')
        except (TypeError, ValueError):
            g_dt = datetime.now()
        if a not in last_played or last_played[a] is None or last_played[a] < g_dt:
            last_played[a] = g_dt
        if b not in last_played or last_played[b] is None or last_played[b] < g_dt:
            last_played[b] = g_dt

    return ratings, dict(games_played), dict(ever_2400), last_played, dict(game_log)


TOURNAMENT_SHORT_NAMES = {
    441: 'EOC',
    509: 'Vigonovo',
}


def build_live_snapshot(tournament_ids, ec_name=None, force_refresh=False):
    """tournament_ids: list of (id, optional_name) pairs OR a single int (back-compat)."""
    if isinstance(tournament_ids, int):
        tournament_ids = [(tournament_ids, ec_name)]
    elif isinstance(tournament_ids, list) and tournament_ids and isinstance(tournament_ids[0], int):
        tournament_ids = [(tid, None) for tid in tournament_ids]

    print(f'=== LIVE FIDE rating — tournaments {[t[0] for t in tournament_ids]} ===')
    print('Loading baseline...')
    joueurs = parse_joueurs()
    program_ids = get_program_ids(joueurs)
    all_games = collect_all_games_global_chrono(exclude_pids=program_ids)
    # Master bootstrap from the FULL game history → stable across snapshots.
    pass1_seed_ratings(all_games)
    master_initial = bootstrap_initial_ratings(all_games)
    baseline = compute_for_date(joueurs, all_games, BASELINE_DATE, None,
                                strict_fide=True, log_from_date=None,
                                master_initial=master_initial)
    state = baseline['_state']
    print(f'  Baseline: {baseline["total_active"]} active, top {baseline["players"][0]["rating"]:.0f}')

    # Fetch each tournament and collect games + participants
    all_ec_games = []
    all_ec_wof_ids = set()
    all_new_player_ids = set()
    tournament_names = []  # for display
    participant_tournaments = defaultdict(list)  # pid -> [short_names]
    for (tid, tname_override) in tournament_ids:
        print(f'\nFetching tournament {tid}...')
        td = fetch_or_load_tournament(tid, force_refresh=force_refresh)
        players_list = td['players_list']
        standings = td['standings']
        rounds = td['rounds']
        info = td['info']
        participants = players_list if players_list else standings
        tname = tname_override or info.get('name') or f'FTD #{tid}'
        tournament_names.append(tname)
        print(f'  {tname} - participants={len(participants)} rounds={len(rounds)} '
              f'current_round={info.get("current_round", "?")}')

        ftd_to_wof, unmatched, new_records = match_ftd_to_wof(participants, joueurs)
        print(f'  Matched {len(ftd_to_wof)}/{len(participants)}; '
              f'new (provisional): {len(new_records)}')
        for u in unmatched[:5]:
            print(f'    new player: id={u[0]} surname="{u[1]}" name="{u[2]}"')
        # Inject new players into joueurs and remember their synthetic IDs
        for synth_id, info_rec in new_records.items():
            joueurs[synth_id] = info_rec
            all_new_player_ids.add(synth_id)
        all_ec_wof_ids |= set(ftd_to_wof.values())
        # Record which tournament each participant is in
        t_short = TOURNAMENT_SHORT_NAMES.get(tid, tname[:8] if tname else f'#{tid}')
        for wof_id in ftd_to_wof.values():
            if t_short not in participant_tournaments[wof_id]:
                participant_tournaments[wof_id].append(t_short)

        tgames = extract_games(standings, rounds, ftd_to_wof)
        # Manual exclusions: (tournament_id, wof_id) -> set of round numbers to drop.
        # Used when an FTD operator has manually entered placeholder results for a
        # player who didn't actually play. Will be fixed at WOF later.
        MANUAL_GAME_EXCLUSIONS = {
            (575, 70017): set(range(8, 15)),  # Andreas CZYMARA, German Championship 2026 C-tier rounds 8-14
        }
        exclusion_rounds = MANUAL_GAME_EXCLUSIONS.get((tid, None), set())  # tournament-wide
        before = len(tgames)
        filtered = []
        for g in tgames:
            drop_rounds = MANUAL_GAME_EXCLUSIONS.get((tid, g['a']), set()) | MANUAL_GAME_EXCLUSIONS.get((tid, g['b']), set())
            if g['round'] in drop_rounds:
                continue
            filtered.append(g)
        if before != len(filtered):
            print(f'  Dropped {before - len(filtered)} games via MANUAL_GAME_EXCLUSIONS')
        tgames = filtered
        for g in tgames:
            g['t'] = tname
        all_ec_games.extend(tgames)
        print(f'  Completed games: {len(tgames)}')

    # Headline names for the LIVE dropdown = FTD tournaments only.
    # Post-baseline .ELO overlays still get applied below but stay out of the label,
    # UNLESS they appear in HEADLINE_OVERLAYS — those represent ongoing non-FTD
    # broadcasts (e.g. liveothello tournaments) that should show alongside the FTDs.
    HEADLINE_OVERLAYS = {
        # Past events from earlier June applied via post-baseline ELO overlay.
        # Stay silent (no entry here) — they no longer belong in the live label.
    }
    display_names = list(tournament_names)

    # Also overlay any .ELO files dated AFTER BASELINE_DATE (new tournaments
    # not yet in the official monthly baseline).
    print(f'\nLooking for post-baseline .ELO files (date > {BASELINE_DATE.date()})...')
    post_baseline = []
    for root, _, files in os.walk(EXTRACT_DIR):
        for fname in files:
            if not fname.endswith('.ELO'): continue
            try: dt = datetime.strptime(fname[:8], '%Y%m%d')
            except ValueError: continue
            if dt > BASELINE_DATE:
                post_baseline.append((dt, os.path.join(root, fname), fname))
    post_baseline.sort()
    for dt, fpath, fname in post_baseline:
        tname = fname[:-4]
        if tname in tournament_names: continue
        try:
            date_str, pgames = parse_elo_file(fpath)
        except Exception as e:
            print(f'  skip {fname}: {e}'); continue
        added = 0
        t_short = tname[9:] if len(tname) > 9 and tname[8] == '_' else tname
        for a, b, res in pgames:
            all_ec_games.append({'a': a, 'b': b, 'result': res, 'round': 0,
                                 'date': dt.strftime('%Y-%m-%d'), 't': tname})
            all_ec_wof_ids.add(a); all_ec_wof_ids.add(b)
            if t_short not in participant_tournaments[a]:
                participant_tournaments[a].append(t_short)
            if t_short not in participant_tournaments[b]:
                participant_tournaments[b].append(t_short)
            added += 1
        if added:
            print(f'  Post-baseline overlay: {fname} ({added} games)')
            tournament_names.append(tname)
            if tname in HEADLINE_OVERLAYS:
                display_names.append(HEADLINE_OVERLAYS[tname])

    # Use the first tournament name as the "headline" name shown in the dropdown
    ec_name = ' + '.join(display_names) if display_names else 'Live'
    ec_wof_ids = all_ec_wof_ids
    ec_games = all_ec_games
    print(f'\nTotal live games to apply: {len(ec_games)}')

    print('\nApplying to baseline...')
    ratings, gp, ev2400, lp, log = apply_live(
        state, ec_games,
        ec_tournament_name=None,  # per-game tournament name now in g['t']
        new_player_ids=all_new_player_ids,
    )

    # Build output: active set = anyone in last 38 months OR EC participant
    cutoff = datetime.now() - timedelta(days=int(38 * 30.4375))
    active = {pid for pid, dt in lp.items() if dt >= cutoff}
    active |= set(log.keys())
    active |= ec_wof_ids  # include all EC participants even if they haven't played yet

    players = []
    for pid in active:
        jp = joueurs.get(pid, {})
        n = gp.get(pid, 0)
        last = lp.get(pid)
        entry = {
            'id': pid,
            'rating': round(ratings.get(pid, 1800.0), 1),
            'games_played': n,
            'firstname': jp.get('firstname', '?'),
            'surname': jp.get('surname', '?'),
            'country': jp.get('country', '???'),
            'provisional': n < 30,
            'last_played': last.strftime('%Y-%m-%d') if last else '',
            'ec': 1 if pid in ec_wof_ids else 0,
        }
        if pid in participant_tournaments:
            entry['tournaments'] = participant_tournaments[pid]
        if pid in log:
            entry['log'] = log[pid]
        players.append(entry)
    players.sort(key=lambda p: -p['rating'])

    output = {
        'ref_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'baseline_date': BASELINE_DATE.strftime('%Y-%m-%d'),
        'tournament_id': ','.join(str(t[0]) for t in tournament_ids),
        'tournament_name': ec_name or 'Live',
        'ec_games_played': len(ec_games),
        'ec_rounds': len(rounds) if tournament_ids else 0,
        'total_active': len(active),
        'players': players,
    }
    out_path = os.path.join(BASE, 'world_fide_live_shift1800.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f'\nSaved {out_path}')
    print(f'Top 5 (post-{len(ec_games)} EC games):')
    for i, p in enumerate(players[:5], 1):
        log_note = f'  +{len(p.get("log",[]))}g' if p.get('log') else ''
        print(f'  {i}. {p["rating"]:>5.0f}  {p["firstname"]} {p["surname"].title()}  [{p["country"]}]{log_note}')

    # Baseline-comparison: include ALL rated players, not just May 15 active set.
    # Ranks come from the active list (1..N); inactive-but-rated players get rank=null.
    baseline_lookup = {p['id']: [i + 1, p['rating']]
                       for i, p in enumerate(baseline['players'])}
    state_ratings = baseline.get('_state', {}).get('ratings', {})
    for pid, r in state_ratings.items():
        if pid not in baseline_lookup:
            baseline_lookup[pid] = [None, round(r, 1)]
    output['baseline_lookup'] = baseline_lookup
    output.pop('_state', None)  # don't ship the raw state in the public JSON
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    return output


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('tournament_ids', type=int, nargs='*', default=[],
                    help='FTD tournament ids to overlay on baseline (none = baseline only)')
    ap.add_argument('--refresh', action='store_true',
                    help='Force re-fetch from FTD (otherwise use cache)')
    args = ap.parse_args()
    build_live_snapshot(args.tournament_ids, force_refresh=args.refresh)
