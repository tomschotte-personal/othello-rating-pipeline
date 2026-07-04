"""
Generate a Belgian-only rating list using Bradley-Terry MLE with WOF time weights.

Steps:
1. Download yearly result zips from katouche.fr (1991-2026)
2. Parse all .ELO files
3. Filter to games where both players are BEL nationality or in the residents list
4. Apply WOF time weights (150/100/60/30/1 by months-ago bucket)
5. Compute Bradley-Terry MLE ratings
6. Filter to active players (game in last 38 months in the BEL pool)
7. Output HTML
"""
import os
import re
import json
import math
import zipfile
import urllib.request
import ssl
from datetime import datetime, timedelta
from collections import defaultdict


BASE = 'C:/Claude/o_dan'
ZIPS_DIR = os.path.join(BASE, 'wof_zips')
EXTRACT_DIR = os.path.join(BASE, 'wof_results')
JOUEURS = os.path.join(BASE, 'joueurs.txt')

# Residents are determined dynamically from the Belgian rating page.
RANGLIJSTEN_HTML = os.path.join(BASE if 'BASE' in dir() else 'C:/Claude/o_dan', 'ranglijsten.html')


def download_all_zips(start=1991, end=2026):
    os.makedirs(ZIPS_DIR, exist_ok=True)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for year in range(start, end + 1):
        path = os.path.join(ZIPS_DIR, f'{year}.zip')
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            print(f'  {year}: cached')
            continue
        url = f'http://ratings.katouche.fr/downloadFile.php?file={year}'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
                data = resp.read()
            with open(path, 'wb') as f:
                f.write(data)
            print(f'  {year}: {len(data)} bytes')
        except Exception as e:
            print(f'  {year}: ERROR {e}')


def extract_all():
    os.makedirs(EXTRACT_DIR, exist_ok=True)
    for fname in sorted(os.listdir(ZIPS_DIR)):
        if not fname.endswith('.zip'):
            continue
        path = os.path.join(ZIPS_DIR, fname)
        try:
            with zipfile.ZipFile(path) as z:
                z.extractall(EXTRACT_DIR)
        except Exception as e:
            print(f'  {fname}: extract failed - {e}')


def parse_joueurs():
    """Build {player_id: {surname, firstname, country}}."""
    players = {}
    current_country = None
    with open(JOUEURS, encoding='latin-1') as f:
        for line in f:
            m = re.match(r'pays = (\w+)', line)
            if m:
                current_country = m.group(1)
                continue
            m = re.match(r'\s*(\d+)\s+(.+?),\s+(.+?)(?:\s+%_<-?\d+>)?\s*$', line)
            if m and current_country:
                pid = int(m.group(1))
                players[pid] = {
                    'surname': m.group(2).strip(),
                    'firstname': m.group(3).strip(),
                    'country': current_country,
                }
    return players


# Map DAN.xls tournament column codes to ISO dates.
# Columns present in DAN.xls but not listed here will be ignored when computing
# per-snapshot DAN. Older columns (pre-2024) are not used by the rating page.
DAN_COLUMN_DATES = {
    'URS24': '2024-01-14',
    'PTO24': '2024-04-01',
    'EOC24': '2024-05-11',
    'OUD24': '2024-06-30',
    'MEF24': '2024-07-13',
    'DOO24': '2024-09-21',
    'AOO24': '2024-09-22',
    'BC24':  '2024-11-17',
    'OOO24': '2024-12-14',
    'URS25': '2025-01-12',
    'DIE25': '2025-03-09',
    'OPT25': '2025-04-21',
    'ZOO':   '2025-05-18',
    'MEF25': '2025-07-05',
    'OOO25': '2025-08-24',
    'BC25':  '2025-09-21',
    'KLJ25': '2025-11-09',
    'OOO25.1': '2025-12-14',
    'URS26': '2026-01-25',
    'OPT26': '2026-04-06',
    'ZONH26': '2026-05-03',
}


def _match_dan_row_to_pid(row_player_str, joueurs_by_norm, joueurs_norm_keys):
    from difflib import get_close_matches
    name = re.sub(r'\s*\{[^}]+\}', '', str(row_player_str)).strip()
    name = re.sub(r'\s*\([^)]*\)', '', name).strip()
    norm = ' '.join(name.split()).lower()
    pid = joueurs_by_norm.get(norm)
    if pid is None:
        matches = get_close_matches(norm, joueurs_norm_keys, n=1, cutoff=0.85)
        if matches:
            pid = joueurs_by_norm.get(matches[0])
    return pid


def parse_dan_file(joueurs):
    """Parse DAN.xlsx and return:
        latest:   {wof_player_id: dan_int}                 (current/latest DAN)
        history:  {wof_player_id: [(date_iso, dan_int), …]} (sorted ascending)
    Built from the column codes in DAN_COLUMN_DATES."""
    import pandas as pd

    latest = {}
    history = defaultdict(list)
    for fname in ['DAN.xlsx', 'DAN.xls']:
        path = os.path.join(BASE, fname)
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_excel(path, sheet_name='general')
        except Exception:
            continue

        cols_in_file = set(df.columns)

        # Build joueurs lookup
        joueurs_by_norm = {}
        joueurs_norm_keys = []
        for pid, p in joueurs.items():
            for variant in (f"{p['surname']} {p['firstname']}".lower(),
                            f"{p['firstname']} {p['surname']}".lower()):
                norm = ' '.join(variant.split())
                joueurs_by_norm.setdefault(norm, pid)
                joueurs_norm_keys.append(norm)

        unmatched = []
        for _, row in df.iterrows():
            if pd.isna(row.get('PLAYERS')):
                continue
            pid = _match_dan_row_to_pid(row['PLAYERS'], joueurs_by_norm, joueurs_norm_keys)
            if pid is None:
                unmatched.append(row['PLAYERS'])
                continue

            # Latest DAN from TOTAL
            total = row.get('TOTAL')
            if pd.notna(total):
                try:
                    latest[pid] = int(float(total))
                except (ValueError, TypeError):
                    pass

            # Per-tournament DAN history from known columns
            for col, dt in DAN_COLUMN_DATES.items():
                if col not in cols_in_file:
                    continue
                val = row.get(col)
                if pd.isna(val):
                    continue
                try:
                    history[pid].append((dt, int(float(val))))
                except (ValueError, TypeError):
                    continue

        if unmatched:
            print(f'  DAN entries unmatched ({len(unmatched)}): showing first 5: {unmatched[:5]}')
        break

    # Sort each player's history by date
    for pid in history:
        history[pid].sort(key=lambda x: x[0])

    return latest, dict(history)


def dan_at_snapshot(history, snapshot_date):
    """Look up a player's DAN as of a given snapshot date (ISO).
    - If history has entries on/before snapshot_date: return the latest one.
    - If snapshot_date precedes ALL history entries: backward-project the
      earliest known value (rarely wrong — DAN levels usually only go up).
    - If history is empty: return None."""
    if not history:
        return None
    valid = [(d, v) for d, v in history if d <= snapshot_date]
    if valid:
        return valid[-1][1]
    return history[0][1]


def parse_ranglijsten_residents(joueurs):
    """Extract all non-BEL players (residents) from the Belgian rating list page.
    Looks them up in joueurs.txt by display name."""
    if not os.path.exists(RANGLIJSTEN_HTML):
        print(f'  WARNING: {RANGLIJSTEN_HTML} not found, no residents added')
        return set()

    with open(RANGLIJSTEN_HTML, encoding='latin-1') as f:
        html = f.read()

    rows = re.findall(r'<tr[^>]*>(.+?)</tr>', html, re.DOTALL)
    residents_found = []
    for row in rows:
        cells = re.findall(r'<td[^>]*>([^<]*)</td>', row)
        if len(cells) < 7:
            continue
        display_name = cells[0].strip()
        if display_name == 'Naam' or not display_name:
            continue
        land = cells[6].strip()
        if not land or land == 'BEL':
            continue
        # Match against joueurs.txt (display name is "Firstname Surname")
        matched_pid = None
        norm_target = re.sub(r'\s+', '', display_name.lower())
        for pid, p in joueurs.items():
            if p['country'] != land:
                continue
            full_a = re.sub(r'\s+', '', f"{p['firstname']} {p['surname']}".lower())
            full_b = re.sub(r'\s+', '', f"{p['surname']} {p['firstname']}".lower())
            if full_a == norm_target or full_b == norm_target:
                matched_pid = pid
                break
        if matched_pid:
            residents_found.append((matched_pid, display_name, land))
            print(f'  Resident: {display_name:30s} ({land}) -> ID {matched_pid}')
        else:
            print(f'  Resident: {display_name:30s} ({land}) -> NOT FOUND in joueurs.txt')
    return {pid for pid, _, _ in residents_found}


def build_tournament_snapshots(min_year=2025, custom_path=None, allowed_ids=None):
    """Auto-detect Belgian tournaments grouped by date, plus foreign tournaments
    where pool-vs-pool games occurred. Returns list of (label, datetime).
    If custom_path is provided and exists, read from there instead."""
    if custom_path and os.path.exists(custom_path):
        with open(custom_path, encoding='utf-8') as f:
            entries = json.load(f)
        out = []
        for e in entries:
            dt = datetime.strptime(e['date'], '%Y-%m-%d')
            out.append((e['name'], dt))
        return sorted(out, key=lambda x: x[1])

    # Auto-detect from WOF .ELO files
    # Stored as {date: [(name, country), ...]}
    by_date = defaultdict(list)
    for root, _, files in os.walk(EXTRACT_DIR):
        for fname in files:
            if not fname.endswith('.ELO'):
                continue
            path = os.path.join(root, fname)
            name = country = date = None
            with open(path, encoding='latin-1', errors='replace') as f:
                for line in f:
                    if line.startswith('%%Tournament:'):
                        name = line.split(':', 1)[1].strip()
                    elif line.startswith('%%Country:'):
                        country = line.split(':', 1)[1].strip()
                    elif line.startswith('%%Date:'):
                        date = line.split(':', 1)[1].strip()
                    if name and country and date:
                        break
            if not date:
                continue
            first_date = date.split(' - ')[0].strip()
            try:
                dt = datetime.strptime(first_date, '%d/%m/%Y')
            except ValueError:
                continue
            if dt.year < min_year:
                continue
            if country == 'Belgium':
                by_date[dt].append((name or fname, 'Belgium'))
            elif allowed_ids:
                _, games = parse_elo_file(path)
                n_pool = sum(1 for a, b, _ in games if a in allowed_ids and b in allowed_ids)
                if n_pool > 0:
                    by_date[dt].append((name or fname, country))

    # Also include FTD-only tournaments (those after the latest WOF date)
    wof_max = max(by_date.keys()) if by_date else None
    for fname in os.listdir(BASE):
        m = re.match(r'tournament_(\d+)\.json$', fname)
        if not m:
            continue
        try:
            with open(os.path.join(BASE, fname), encoding='utf-8') as f:
                data = json.load(f)
            rounds = data.get('rounds', [])
            if not rounds:
                continue
            ts = rounds[0]['pairing'][0][0].get('roundStarted', '')
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00')).replace(tzinfo=None)
            dt = datetime(dt.year, dt.month, dt.day)
            if dt.year < min_year:
                continue
            if wof_max is not None and dt <= wof_max:
                continue  # already in WOF
            # Use og:title or extract from data
            label = f'FTD tournament {m.group(1)} (live)'
            by_date[dt].append((label, 'Belgium'))
        except Exception as e:
            pass

    snapshots = []
    for dt in sorted(by_date.keys()):
        entries = by_date[dt]
        names = [e[0] for e in entries]
        # All entries on same date share a country (almost always)
        country = entries[0][1] if entries else 'Belgium'
        if len(names) == 1:
            label = names[0]
        else:
            label = os.path.commonprefix(names).rstrip(' -+B/').strip()
            if not label or len(label) < 4:
                label = names[0]
        snapshots.append((label, dt, country))
    return snapshots


def collect_tournament_standings(snapshot_date_iso, snapshot_country, allowed_ids, joueurs):
    """Find all .ELO files AND FTD JSON for this date and merge BEL/resident
    standings. If a player appears in multiple sources/sections, keep the max score."""
    target_date = datetime.strptime(snapshot_date_iso, '%Y-%m-%d').date()
    merged = {}  # pid -> best entry (highest score across sources)

    def upsert(entry):
        ex = merged.get(entry['pid'])
        if not ex or entry['score'] > ex['score']:
            merged[entry['pid']] = entry

    # Walk WOF .ELO files
    for root, _, files in os.walk(EXTRACT_DIR):
        for fname in files:
            if not fname.endswith('.ELO'):
                continue
            path = os.path.join(root, fname)
            file_date_str = None
            with open(path, encoding='latin-1', errors='replace') as f:
                for line in f:
                    if line.startswith('%%Date:'):
                        file_date_str = line.split(':', 1)[1].strip()
                        break
            if not file_date_str:
                continue
            first_date = file_date_str.split(' - ')[0].strip()
            try:
                file_dt = datetime.strptime(first_date, '%d/%m/%Y').date()
            except ValueError:
                continue
            if file_dt != target_date:
                continue
            # Skip the "final" sub-tournament: it's a 1-game tiebreak, score
            # there shouldn't replace the player's main-section score.
            if 'final' in fname.lower():
                continue
            for entry in parse_elo_standings(path, allowed_ids):
                upsert(entry)

    # Also walk FTD JSON files matching this date
    for fname in os.listdir(BASE):
        m = re.match(r'tournament_(\d+)\.json$', fname)
        if not m:
            continue
        try:
            with open(os.path.join(BASE, fname), encoding='utf-8') as f:
                data = json.load(f)
            ts = data['rounds'][0]['pairing'][0][0].get('roundStarted', '')
            ftd_dt = datetime.fromisoformat(ts.replace('Z', '+00:00')).date()
            if ftd_dt != target_date:
                continue
            for sp in data.get('standings', []):
                sn = sp.get('surname', '').upper()
                fn = sp.get('name', '').upper()
                pid = next(
                    (pid for pid, p in joueurs.items()
                     if p['surname'].upper() == sn and p['firstname'].upper() == fn),
                    None,
                )
                if pid is None or pid not in allowed_ids:
                    continue
                upsert({
                    'pid': pid,
                    'surname': sp['surname'],
                    'firstname': sp['name'],
                    'country': joueurs.get(pid, {}).get('country', '???'),
                    'score': sp.get('score', 0),
                })
        except Exception:
            continue

    return sorted(merged.values(), key=lambda x: -x['score'])


def parse_elo_standings(path, allowed_ids):
    """Parse a .ELO file and return the final standings filtered to allowed_ids.
    Returns list of {pid, surname, firstname, country, score} sorted by score desc."""
    standings = []
    with open(path, encoding='latin-1', errors='replace') as f:
        for line in f:
            # %_%    2795, SCHOTTE, Tom, BEL, 7, 336, 1924
            m = re.match(
                r'%_%\s*(\d+)\s*,\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*([A-Z]+)\s*,\s*([\d.]+)\s*,',
                line
            )
            if m:
                pid = int(m.group(1))
                if pid not in allowed_ids:
                    continue
                standings.append({
                    'pid': pid,
                    'surname': m.group(2).strip(),
                    'firstname': m.group(3).strip(),
                    'country': m.group(4).strip(),
                    'score': float(m.group(5)),
                })
    standings.sort(key=lambda x: -x['score'])
    return standings


def parse_elo_file(path):
    """Parse a .ELO file. Returns (date_str, list_of_games).
    Each game: (id_a, id_b, result) where result is 1 (a wins), -1 (b wins), 0 (draw).
    Handles both modern format ('123 (45)>(19) 456 B') and the older score-less
    format ('123 > 456') used in pre-2008 tournaments."""
    date = None
    games = []
    # Modern: id (sc)>(sc) id [BW]   |   Old: id > id
    modern_re = re.compile(r'\s*(\d+)\s*\(\s*\d+\s*\)\s*([><=])\s*\(\s*\d+\s*\)\s*(\d+)\s*[BW]?')
    legacy_re = re.compile(r'\s*(\d+)\s+([><=])\s+(\d+)\s*$')
    with open(path, encoding='latin-1', errors='replace') as f:
        for line in f:
            line = line.rstrip('\n')
            m = re.match(r'%%Date:\s*(\S+)', line)
            if m:
                date = m.group(1)
                continue
            m = modern_re.match(line) or legacy_re.match(line)
            if m:
                id_a = int(m.group(1))
                op = m.group(2)
                id_b = int(m.group(3))
                res = 1 if op == '>' else (-1 if op == '<' else 0)
                games.append((id_a, id_b, res))
    return date, games


def parse_date(s):
    """Parse DD/MM/YYYY -> datetime."""
    try:
        return datetime.strptime(s, '%d/%m/%Y')
    except (ValueError, TypeError):
        return None


def collect_ftd_games(ftd_json_path, joueurs, allowed_ids):
    """Parse a flipthedisc tournament JSON into the same game format as the .ELO files.
    Maps FTD player ids -> WOF player ids by surname/firstname matching."""
    if not os.path.exists(ftd_json_path):
        return []
    with open(ftd_json_path, encoding='utf-8') as f:
        data = json.load(f)
    standings = data.get('standings', [])
    rounds = data.get('rounds', [])

    # Build FTD pid -> WOF pid map
    ftd_to_wof = {}
    for sp in standings:
        sn = sp.get('surname', '').upper()
        fn = sp.get('name', '').upper()
        for pid, p in joueurs.items():
            if p['surname'].upper() == sn and p['firstname'].upper() == fn:
                ftd_to_wof[sp['player_id']] = pid
                break

    # Deduplicate rounds by roundStarted
    seen_times = set()
    unique_rounds = []
    for rd in rounds:
        pairings = rd.get('pairing', [])
        if pairings:
            ts = pairings[0][0].get('roundStarted', '')
            if ts not in seen_times:
                seen_times.add(ts)
                unique_rounds.append(rd)

    # Determine game date
    if unique_rounds:
        ts = unique_rounds[0]['pairing'][0][0].get('roundStarted', '')
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            dt = None
    else:
        dt = None

    games = []
    for rd in unique_rounds:
        for pair in rd.get('pairing', []):
            p1 = pair[0]
            p2 = pair[1] if len(pair) > 1 else None
            if not p2 or p2.get('id') is None:
                continue
            result = p1.get('result')
            if result is None:
                continue
            pid_a_wof = ftd_to_wof.get(p1['id'])
            pid_b_wof = ftd_to_wof.get(p2['id'])
            if pid_a_wof is None or pid_b_wof is None:
                continue
            if pid_a_wof not in allowed_ids or pid_b_wof not in allowed_ids:
                continue
            # Map result: 2 = p1 wins, 0 = p2 wins, 1 = draw
            if result == 2:
                res = 1
            elif result == 0:
                res = -1
            elif result == 1:
                res = 0
            else:
                continue
            games.append({'date': dt, 'a': pid_a_wof, 'b': pid_b_wof, 'result': res})
    return games


def collect_all_games(joueurs, allowed_ids):
    """Walk all extracted .ELO files, return list of games where both players are in allowed_ids.
    Each entry: {date, a, b, result}."""
    games = []
    files_processed = 0
    files_with_dates = 0
    for root, _, files in os.walk(EXTRACT_DIR):
        for fname in files:
            if not fname.endswith('.ELO'):
                continue
            path = os.path.join(root, fname)
            files_processed += 1
            date_str, file_games = parse_elo_file(path)
            dt = parse_date(date_str) if date_str else None
            if dt:
                files_with_dates += 1
            for a, b, res in file_games:
                if a in allowed_ids and b in allowed_ids:
                    games.append({'date': dt, 'a': a, 'b': b, 'result': res})
    print(f'  Processed {files_processed} .ELO files ({files_with_dates} with dates)')
    return games


def compute_weight(game_date, ref_date, integer_months=True):
    """WOF weights: 7m@150, 7m@100, 12m@60, 12m@30, older@1.

    integer_months=True matches Jech's Quelle_Anciennete: month difference is
    (ref.year-game.year)*12 + (ref.month-game.month), discrete integer.
    """
    if game_date is None:
        return 1
    if integer_months:
        months_ago = (ref_date.year - game_date.year) * 12 + (ref_date.month - game_date.month)
    else:
        months_ago = (ref_date - game_date).days / 30.4375
    if months_ago < 0:
        return 150
    if months_ago < 7:
        return 150
    if months_ago < 14:
        return 100
    if months_ago < 26:
        return 60
    if months_ago < 38:
        return 30
    return 1


def find_sccs_above_threshold(games, players_set, min_size=10):
    """Find strongly connected components of the 'win/draw' graph with size >= min_size.
    Returns the union of qualifying SCCs (set of player IDs).

    Edges (directed):
      - winner -> loser (the winner is "stronger than" loser)
      - For draws: both directions (mutual edge)

    Then SCCs of this directed graph are the equivalence classes of "comparable"
    players (matches Jech's `composante` concept). We keep only components with
    at least `min_size` players (matches `seuil-existence`).
    """
    from collections import defaultdict
    adj = defaultdict(set)
    rev = defaultdict(set)
    for a, b, res in games:
        if a not in players_set or b not in players_set:
            continue
        if res == 1:        # a beat b → edge a -> b
            adj[a].add(b); rev[b].add(a)
        elif res == -1:     # b beat a → edge b -> a
            adj[b].add(a); rev[a].add(b)
        else:               # draw → both directions
            adj[a].add(b); rev[b].add(a)
            adj[b].add(a); rev[a].add(b)

    # Kosaraju's algorithm for SCC
    visited = set()
    order = []
    def visit(u):
        stack = [(u, iter(adj.get(u, ())))]
        visited.add(u)
        while stack:
            node, it = stack[-1]
            next_node = next(it, None)
            if next_node is None:
                order.append(node)
                stack.pop()
            elif next_node not in visited:
                visited.add(next_node)
                stack.append((next_node, iter(adj.get(next_node, ()))))

    for v in players_set:
        if v not in visited:
            visit(v)

    assigned = {}
    def assign(u, root):
        stack = [u]
        while stack:
            node = stack.pop()
            if node in assigned:
                continue
            assigned[node] = root
            for prev in rev.get(node, ()):
                if prev not in assigned:
                    stack.append(prev)

    for v in reversed(order):
        if v not in assigned:
            assign(v, v)

    # Group by root
    components = defaultdict(set)
    for v, root in assigned.items():
        components[root].add(v)

    # Keep components with size >= min_size
    out = set()
    sizes = []
    pid_to_component = {}  # player -> component id (root)
    for root, members in components.items():
        if len(members) >= min_size:
            out.update(members)
            sizes.append(len(members))
            for m in members:
                pid_to_component[m] = root
    sizes.sort(reverse=True)
    return out, sizes, pid_to_component


def compute_rating_uncertainty(games_with_weights, log_ratings):
    """Approximate per-player rating standard deviation (in Elo points) via
    the diagonal of the inverse Fisher information matrix.

    For Bradley-Terry, the Fisher info per player is:
        I_i = sum_j (w_ij * p_ij * (1 - p_ij))
    where p_ij = sigmoid(r_i - r_j), and w_ij is the game weight.
    sigma_i (in log-rating units) ~ 1/sqrt(I_i).
    Convert to Elo units by multiplying with 400/ln(10).
    """
    import math
    elo_factor = 400 / math.log(10)
    info = {pid: 0.0 for pid in log_ratings}
    for a, b, _, w in games_with_weights:
        if a not in log_ratings or b not in log_ratings:
            continue
        # log_ratings here are CENTERED log ratings (sum to 0); convert to z = R/elo_factor
        z_a = log_ratings[a]
        z_b = log_ratings[b]
        # P(a beats b) under Bradley-Terry = exp(z_a) / (exp(z_a) + exp(z_b))
        delta = z_a - z_b
        if delta > 30:
            p = 1.0
        elif delta < -30:
            p = 0.0
        else:
            p = 1.0 / (1.0 + math.exp(-delta))
        contribution = w * p * (1 - p)
        info[a] += contribution
        info[b] += contribution
    sigma = {}
    for pid, I in info.items():
        if I <= 0:
            sigma[pid] = None
        else:
            sigma[pid] = elo_factor / math.sqrt(I)
    return sigma


def jech_gradient_mle_np(games_with_weights, players_set,
                          precision=10000, periode=63, preperiode=10, etoilement=8,
                          target_mean=1800, scale_factor=182.0,
                          weighted_mean_by_games=True, max_iter=50000,
                          verbose=True, log_every=500,
                          components=None):
    """Jech's exact algorithm. If `components` is provided (dict pid->component_id),
    centering is done PER component (matching Jech's `mpond[composante]`),
    otherwise centering is global."""
    """Numpy-vectorized version of jech_gradient_mle. ~100x faster."""
    import numpy as np

    # Map player IDs to dense indices
    pid_list = sorted(players_set)
    pid_to_idx = {pid: i for i, pid in enumerate(pid_list)}
    n = len(pid_list)

    # Aggregate per-pair stats
    pair_dict = {}     # (i, j) sorted by index -> [s_i, s_j, ng_i, ng_j]
    for a, b, res, w in games_with_weights:
        if a not in pid_to_idx or b not in pid_to_idx:
            continue
        ia, ib = pid_to_idx[a], pid_to_idx[b]
        if ia > ib:
            ia, ib = ib, ia
            res = -res
        rec = pair_dict.get((ia, ib))
        if rec is None:
            rec = [0.0, 0.0, 0, 0]
            pair_dict[(ia, ib)] = rec
        if res == 1:
            rec[0] += 2 * w; rec[2] += 2
        elif res == -1:
            rec[1] += 2 * w; rec[3] += 2
        else:
            rec[0] += w; rec[1] += w; rec[2] += 1; rec[3] += 1

    # Convert to numpy arrays
    n_pairs = len(pair_dict)
    pair_i = np.empty(n_pairs, dtype=np.int32)
    pair_j = np.empty(n_pairs, dtype=np.int32)
    s_i = np.empty(n_pairs, dtype=np.float64)
    s_j = np.empty(n_pairs, dtype=np.float64)
    ng = np.zeros(n, dtype=np.int64)
    for k, ((ia, ib), (si, sj, ngi, ngj)) in enumerate(pair_dict.items()):
        pair_i[k] = ia; pair_j[k] = ib
        s_i[k] = si; s_j[k] = sj
        ng[ia] += ngi + ngj
        ng[ib] += ngi + ngj

    r = np.zeros(n, dtype=np.float64)
    tchebi = np.array([2.0 / (1.0 + math.cos(math.pi * (i + 1) / (periode + 1)))
                       for i in range(periode)], dtype=np.float64)

    g_norme0 = None
    step0 = None
    seuil = None

    for it in range(1, max_iter + 1):
        # Vectorized gradient
        e_i = np.exp(r[pair_i])
        e_j = np.exp(r[pair_j])
        denom = e_i + e_j
        term = (s_i * e_j - s_j * e_i) / denom  # dL/dE_i for pair
        grad = np.zeros(n, dtype=np.float64)
        np.add.at(grad, pair_i, term)
        np.add.at(grad, pair_j, -term)

        g_norme = float(np.abs(grad).sum())

        if it == 1:
            g_norme0 = g_norme
            if g_norme0 < 0.5:
                if verbose:
                    print(f'  Converged immediately (g_norme0={g_norme0:.3f})')
                break
            seuil = g_norme0 / precision
            step0 = (n ** 0.3) / g_norme0
            if n < 10:
                step0 /= 3.0
            if verbose:
                print(f'  n={n}, n_pairs={n_pairs}, g_norme0={g_norme0:.1f}, '
                      f'step0={step0:.2e}, seuil={seuil:.3f}')

        if it <= preperiode:
            step = 1.0
        else:
            step = tchebi[((it - preperiode - 1) * etoilement) % periode]

        r += step * step0 * grad

        if verbose and (it % log_every == 0 or g_norme <= seuil):
            avanc = math.log(g_norme0 / max(g_norme, 1e-12)) / math.log(precision) * 100
            print(f'  iter {it:5d}: |g|={g_norme:.3f}, advancement {avanc:.1f}%')

        if g_norme <= seuil:
            if verbose:
                print(f'  Converged after {it} iterations')
            break
    else:
        if verbose:
            print(f'  Max iter ({max_iter}) reached, |g|={g_norme:.3f} vs seuil={seuil:.3f}')

    # Center: subtract weighted mean. Per-component if `components` given.
    if components:
        # Group players by component root
        comp_of_idx = np.array([components.get(pid_list[i], -1) for i in range(n)])
        unique_comps = np.unique(comp_of_idx)
        for comp_id in unique_comps:
            mask = (comp_of_idx == comp_id)
            if weighted_mean_by_games:
                w = ng[mask].astype(np.float64)
                tw = w.sum()
                mean_r = float((r[mask] * w).sum() / tw) if tw > 0 else float(r[mask].mean())
            else:
                mean_r = float(r[mask].mean())
            r[mask] -= mean_r
    else:
        if weighted_mean_by_games:
            total_w = ng.sum()
            if total_w > 0:
                mean_r = float((r * ng).sum() / total_w)
            else:
                mean_r = float(r.mean())
        else:
            mean_r = float(r.mean())
        r -= mean_r

    elo_ratings = {pid_list[i]: target_mean + r[i] * scale_factor for i in range(n)}
    log_ratings = {pid_list[i]: r[i] for i in range(n)}
    return elo_ratings, log_ratings


def jech_gradient_mle(games_with_weights, players_set,
                       precision=10000, periode=63, preperiode=10, etoilement=8,
                       target_mean=1800, scale_factor=182.0,
                       weighted_mean_by_games=True, max_iter=10000, verbose=True):
    """Jech's exact MLE algorithm: gradient ascent with Chebyshev acceleration.

    Mirrors calcjech.c / haut_bas.c from Lazard's WOF source.
    - For each pair, accumulate weighted scores (Bradley-Terry sufficient stats).
    - Gradient ascent on log-likelihood.
    - Step size = step0 * tchebi[k] where step0 = n^0.3 / |g_0| and tchebi follows
      a Chebyshev schedule (anti-overshoot) cycled with stride `etoilement`.
    - Convergence: |g| < |g_0| / precision (default 10000 = 4 orders of magnitude).
    - Center: subtract mean of log-ratings, weighted by game count.
    - Scale to Elo: 1800 + 182 * (centered log-rating).
    """
    # Aggregate per-pair weighted scores. Use GRANULARITE-style: win=2, draw=1.
    pairs = {}            # (a, b) sorted -> [s_a, s_b, ng_a, ng_b]
    nb_parties = defaultdict(int)
    for a, b, res, w in games_with_weights:
        if a > b:
            a, b = b, a
            res = -res
        key = (a, b)
        rec = pairs.get(key)
        if rec is None:
            rec = [0.0, 0.0, 0, 0]
            pairs[key] = rec
        if res == 1:        # a wins
            rec[0] += 2 * w; rec[2] += 2
        elif res == -1:     # b wins
            rec[1] += 2 * w; rec[3] += 2
        else:               # draw
            rec[0] += w; rec[1] += w; rec[2] += 1; rec[3] += 1

    # nb_parties[player] = sum of (ng_a + ng_b) over pairs they're in (Jech style)
    for (a, b), (_, _, ng_a, ng_b) in pairs.items():
        nb_parties[a] += ng_a + ng_b
        nb_parties[b] += ng_a + ng_b

    players_list = list(players_set)
    r = {pid: 0.0 for pid in players_list}

    # Chebyshev acceleration table: tchebi[i] = 2/(1+cos(pi*(i+1)/(periode+1)))
    tchebi = [2.0 / (1.0 + math.cos(math.pi * (i + 1) / (periode + 1))) for i in range(periode)]

    n_players = len(players_list)
    g_norme0 = None
    step0 = None
    seuil = None

    for it in range(1, max_iter + 1):
        # Compute gradient: dL/dE_a = (s_a * e_b - s_b * e_a) / (e_a + e_b)
        grad = {pid: 0.0 for pid in players_list}
        for (a, b), (s_a, s_b, _, _) in pairs.items():
            e_a = math.exp(r[a])
            e_b = math.exp(r[b])
            denom = e_a + e_b
            if denom <= 0:
                continue
            term = (s_a * e_b - s_b * e_a) / denom
            grad[a] += term
            grad[b] -= term

        g_norme = sum(abs(v) for v in grad.values())

        if it == 1:
            g_norme0 = g_norme
            if g_norme0 < 0.5:
                if verbose:
                    print(f'  Converged immediately (g_norme0={g_norme0:.3f})')
                break
            seuil = g_norme0 / precision
            step0 = (n_players ** 0.3) / g_norme0
            if n_players < 10:
                step0 /= 3.0
            if verbose:
                print(f'  g_norme0={g_norme0:.1f}, step0={step0:.4f}, seuil={seuil:.3f}')

        # Step schedule: first `preperiode` iterations use step=1
        if it <= preperiode:
            step = 1.0
        else:
            step = tchebi[((it - preperiode - 1) * etoilement) % periode]

        # Move: r += step * step0 * grad (ascent on log-likelihood)
        delta = step * step0
        for pid in players_list:
            r[pid] += delta * grad[pid]

        if verbose and (it % 500 == 0 or g_norme <= seuil):
            avanc = math.log(g_norme0 / max(g_norme, 1e-12)) / math.log(precision) * 100
            print(f'  iter {it:5d}: |g|={g_norme:.3f}, advancement {avanc:.1f}%')

        if g_norme <= seuil:
            if verbose:
                print(f'  Converged after {it} iterations (|g|={g_norme:.3f} < seuil={seuil:.3f})')
            break
    else:
        if verbose:
            print(f'  Max iter ({max_iter}) reached, |g|={g_norme:.3f} vs seuil={seuil:.3f}')

    # Center: subtract games-weighted mean (Jech: calcul-moyenne=1)
    if weighted_mean_by_games:
        total_w = sum(nb_parties.get(pid, 0) for pid in r)
        if total_w > 0:
            mean_r = sum(r[pid] * nb_parties.get(pid, 0) for pid in r) / total_w
        else:
            mean_r = sum(r.values()) / max(len(r), 1)
    else:
        mean_r = sum(r.values()) / max(len(r), 1)
    for pid in r:
        r[pid] -= mean_r

    elo = {pid: target_mean + r[pid] * scale_factor for pid in r}
    return elo, r


def find_rateable_set(games, players_set):
    """Find the subset of players who can be reliably rated, per WOF FAQ Q5:
    'You have to draw against someone already in the list, or win a game against a
    rated player and lose against another (or the same) player.'

    Iteratively prune players who have only wins, only losses, and no draws
    against the currently-rateable set, until the set stabilizes.
    """
    rateable = set(players_set)
    while True:
        # For each rateable player, count wins/losses/draws vs rateable opponents only
        from collections import defaultdict as dd
        wins = dd(int); losses = dd(int); draws = dd(int)
        for a, b, res in games:
            if a not in rateable or b not in rateable:
                continue
            if res == 1:
                wins[a] += 1; losses[b] += 1
            elif res == -1:
                wins[b] += 1; losses[a] += 1
            else:
                draws[a] += 1; draws[b] += 1

        to_remove = set()
        for pid in rateable:
            # Player is anchored if: any draw, OR (at least one win AND at least one loss)
            anchored = (draws[pid] > 0) or (wins[pid] > 0 and losses[pid] > 0)
            if not anchored:
                to_remove.add(pid)

        if not to_remove:
            break
        rateable -= to_remove
    return rateable


def bradley_terry_mle(games_with_weights, players_set, max_iter=200, tol=0.01,
                       prior_strength=0.0, target_mean=1500, scale_factor=None,
                       weighted_mean_by_games=False):
    """Iterative Bradley-Terry MLE.

    Args:
        prior_strength: virtual draw against r=0 with this weight (compresses toward mean)
        target_mean: final Elo mean (Jech uses 1800; standard Elo uses 1500)
        scale_factor: log-rating to Elo multiplier (Jech uses 182 = 200/ln(3);
                       Elo standard uses ~173.7 = 400/ln(10))
        weighted_mean_by_games: if True, center using per-player unweighted-game-count
                                 weighted mean (Jech's `calcul-moyenne=1` config)
    """
    if scale_factor is None:
        scale_factor = 400 / math.log(10)
    """Iterative Bradley-Terry MLE with weighted games.
    Each game: (a, b, result, weight).
    Returns dict {pid: rating}, where rating is on Elo scale (mean ~1500)."""
    # Use log-rating r = R/400 ln(10), so P(A beats B) = sigma(r_A - r_B)
    # Bradley-Terry: P(A wins) = exp(r_A) / (exp(r_A) + exp(r_B))
    r = {pid: 0.0 for pid in players_set}

    # Build per-player game records: list of (opponent, weight, score)
    # score = 1 (win), 0.5 (draw), 0 (loss) from this player's perspective
    by_player = defaultdict(list)
    game_counts = defaultdict(int)  # unweighted game count per player (for Jech's mean)
    for a, b, res, w in games_with_weights:
        game_counts[a] += 1
        game_counts[b] += 1
        if res == 1:
            by_player[a].append((b, w, 1.0))
            by_player[b].append((a, w, 0.0))
        elif res == -1:
            by_player[a].append((b, w, 0.0))
            by_player[b].append((a, w, 1.0))
        else:
            by_player[a].append((b, w, 0.5))
            by_player[b].append((a, w, 0.5))

    # Iterative MLE update (Minorization-Maximization for Bradley-Terry):
    # exp(r_i) = sum(w*s_ij) / sum(w * 1/(exp(r_i) + exp(r_j)))
    # where s_ij is i's score vs j and weighting is by w
    # We iterate with a damping factor to ensure stability.
    for it in range(max_iter):
        new_r = {}
        max_change = 0.0
        for pid in players_set:
            games_p = by_player.get(pid, [])
            if not games_p:
                new_r[pid] = r[pid]
                continue
            num = 0.0  # sum of w*s
            den = 0.0  # sum of w / (exp(r_i) + exp(r_j))
            er_i = math.exp(r[pid])
            for opp, w, s in games_p:
                er_j = math.exp(r[opp])
                num += w * s
                den += w / (er_i + er_j)
            # Prior: virtual draw against a rating-0 reference player.
            # This shrinks ratings toward the mean (centering).
            if prior_strength > 0:
                num += prior_strength * 0.5
                den += prior_strength / (er_i + 1.0)
            if num <= 0 or den <= 0:
                new_r[pid] = r[pid]  # cannot be rated
                continue
            new_er = num / den
            new_r_val = math.log(new_er) if new_er > 0 else r[pid]
            # Damp to avoid oscillation
            new_r[pid] = 0.5 * r[pid] + 0.5 * new_r_val
            max_change = max(max_change, abs(new_r[pid] - r[pid]))

        # Anchor: subtract mean to keep ratings centered.
        # Jech weights by game count (config: calcul-moyenne=1).
        if weighted_mean_by_games:
            total_w = sum(game_counts.get(pid, 1) for pid in new_r)
            mean_r = sum(new_r[pid] * game_counts.get(pid, 1) for pid in new_r) / max(total_w, 1)
        else:
            mean_r = sum(new_r.values()) / len(new_r)
        for pid in new_r:
            new_r[pid] -= mean_r

        r = new_r
        if max_change < tol:
            print(f'  Converged after {it+1} iterations')
            break
    else:
        print(f'  Max iterations ({max_iter}) reached, final max change: {max_change:.4f}')

    # Convert log-rating to Elo scale using the chosen scale factor & target mean
    elo_ratings = {pid: target_mean + r[pid] * scale_factor for pid in r}
    return elo_ratings, r  # Return both Elo and centered log-ratings


def main():
    print('=== Step 1: Download yearly result zips ===')
    download_all_zips()

    print('\n=== Step 2: Extract all zips ===')
    extract_all()

    print('\n=== Step 3: Parse joueurs.txt ===')
    joueurs = parse_joueurs()
    print(f'  Total players: {len(joueurs)}')

    print('\n=== Step 4: Determine BEL+resident pool ===')
    bel_ids = {pid for pid, p in joueurs.items() if p['country'] == 'BEL'}
    print(f'  BEL nationality: {len(bel_ids)}')
    resident_ids = parse_ranglijsten_residents(joueurs)
    allowed_ids = bel_ids | resident_ids
    print(f'  Total pool: {len(allowed_ids)}')

    print('\n=== Step 5: Collect games where both players in pool ===')
    games = collect_all_games(joueurs, allowed_ids)
    print(f'  Filtered games (from WOF): {len(games)}')

    # Latest game date in WOF data
    wof_latest = max((g['date'] for g in games if g['date']), default=None)
    print(f'  Latest WOF game date: {wof_latest.strftime("%Y-%m-%d") if wof_latest else "?"}')

    # Add games from cached FlipTheDisc tournaments AFTER the latest WOF date
    # (older FTD tournaments are already in WOF data)
    for fname in sorted(os.listdir(BASE)):
        m = re.match(r'tournament_(\d+)\.json$', fname)
        if not m:
            continue
        ftd_games = collect_ftd_games(os.path.join(BASE, fname), joueurs, allowed_ids)
        if not ftd_games:
            continue
        # Skip if its date is on or before the latest WOF date (already in WOF)
        ftd_date = ftd_games[0]['date']
        if wof_latest and ftd_date and ftd_date.date() <= wof_latest.date():
            print(f'  Skipping FTD tournament {m.group(1)} ({ftd_date.strftime("%Y-%m-%d")}) — already in WOF')
            continue
        games.extend(ftd_games)
        print(f'  Adding FTD tournament {m.group(1)} ({ftd_date.strftime("%Y-%m-%d") if ftd_date else "?"}): {len(ftd_games)} games')
    print(f'  Total games: {len(games)}')

    # Load DAN history (per-tournament) plus latest fallback
    print('\n=== Loading DAN levels ===')
    dan_latest, dan_history = parse_dan_file(joueurs)
    print(f'  DAN players matched: {len(dan_latest)}, with column-history: {len(dan_history)}')

    # Compute snapshots (each: filter games by date cutoff and run MLE)
    def compute_snapshot(label, games_subset):
        if not games_subset:
            return None
        dates_s = [g['date'] for g in games_subset if g['date']]
        ref = max(dates_s) if dates_s else datetime.now()
        cutoff_s = ref - timedelta(days=int(38 * 30.4375))
        active_s = set()
        for g in games_subset:
            if g['date'] and g['date'] >= cutoff_s:
                active_s.add(g['a']); active_s.add(g['b'])
        players_s = set()
        for g in games_subset:
            players_s.add(g['a']); players_s.add(g['b'])
        # Use the SCC core (seuil-existence=10 in WOF; we use 2 here since pool is small)
        raw_results = [(g['a'], g['b'], g['result']) for g in games_subset]
        rateable, sccs, pid_to_comp = find_sccs_above_threshold(
            raw_results, players_s, min_size=2)
        weighted_s = [(g['a'], g['b'], g['result'],
                       compute_weight(g['date'], ref, integer_months=True))
                      for g in games_subset
                      if g['a'] in rateable and g['b'] in rateable]
        n_unrated = len(active_s - rateable)
        print(f'\n=== {label} (ref={ref.strftime("%Y-%m-%d")}, games={len(games_subset)}, active={len(active_s)}, unrated={n_unrated}) ===')
        ratings_s, log_ratings_s = jech_gradient_mle_np(
            weighted_s, rateable,
            precision=10000, periode=63, preperiode=10, etoilement=8,
            target_mean=1800, scale_factor=200 / math.log(3),
            weighted_mean_by_games=True,
            components=pid_to_comp,
            max_iter=50000, verbose=False,
        )
        sigma_s = compute_rating_uncertainty(weighted_s, log_ratings_s)
        active_rateable = {pid: r for pid, r in ratings_s.items() if pid in active_s}
        active_unrated = active_s - rateable

        snap_iso = ref.strftime('%Y-%m-%d')
        rated_list = []
        for pid, rating in sorted(active_rateable.items(), key=lambda x: -x[1]):
            jp = joueurs.get(pid, {})
            dan_at = dan_at_snapshot(dan_history.get(pid), snap_iso)
            if dan_at is None:
                dan_at = dan_latest.get(pid)
            sigma = sigma_s.get(pid)
            rated_list.append({
                'id': pid,
                'rating': round(rating, 1),
                'sigma': round(sigma, 1) if sigma is not None else None,
                # Threshold tuned to our small dense BEL pool; WOF uses 200 on a sparser dataset.
                'provisional': sigma is None or sigma > 50,
                'firstname': jp.get('firstname', '?'),
                'surname': jp.get('surname', '?'),
                'country': jp.get('country', '???'),
                'dan': dan_at,
            })
        unrated_list = sorted(
            [
                {
                    'id': pid,
                    'firstname': joueurs.get(pid, {}).get('firstname', '?'),
                    'surname': joueurs.get(pid, {}).get('surname', '?'),
                    'country': joueurs.get(pid, {}).get('country', '???'),
                }
                for pid in active_unrated
            ],
            key=lambda p: (p['surname'], p['firstname']),
        )
        return {
            'label': label,
            'ref_date': ref.strftime('%Y-%m-%d'),
            'year': ref.year,
            'total_games': len(games_subset),
            'total_active': len(active_s),
            'total_rated': len(active_rateable),
            'total_unrated': len(active_unrated),
            'players': rated_list,
            'unrated': unrated_list,
            'standings': [],  # filled in after compute_snapshot returns
        }

    # Auto-detect Belgian + foreign-with-pool-games tournaments from WOF result files.
    snapshot_defs = build_tournament_snapshots(min_year=2024, allowed_ids=allowed_ids)
    print(f'\n=== {len(snapshot_defs)} snapshot points detected ===')
    for label, dt, ctry in snapshot_defs:
        print(f'  {dt.strftime("%Y-%m-%d")}  [{ctry}] {label}')

    snapshots = []
    prev_cutoff = None
    for label, cutoff, country in snapshot_defs:
        sub_games = [g for g in games if g['date'] and g['date'].date() <= cutoff.date()]
        snap = compute_snapshot(label, sub_games)
        if snap is None:
            continue
        snap['country'] = country
        if prev_cutoff is None:
            played_at = None
        else:
            played_at = set()
            for g in games:
                if g['date'] and g['date'].date() == cutoff.date():
                    played_at.add(g['a'])
                    played_at.add(g['b'])
        if played_at is not None:
            for p in snap['players']:
                p['played_since_prev'] = p['id'] in played_at

        # Tournament standings (within BEL/resident pool)
        snap_iso = cutoff.strftime('%Y-%m-%d')
        snap['standings'] = collect_tournament_standings(snap_iso, country, allowed_ids, joueurs)

        snapshots.append(snap)
        prev_cutoff = cutoff

    # Compute biggest-mover stats per snapshot (using diff vs previous)
    for i, snap in enumerate(snapshots):
        if i == 0:
            snap['biggest_movers'] = {}
            continue
        prev = snapshots[i - 1]
        prev_lookup = {p['id']: p['rating'] for p in prev['players']}
        gainers = []
        losers = []
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
        'snapshots': snapshots,
    }
    with open(os.path.join(BASE, 'bel_rating.json'), 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f'\nSaved bel_rating.json with {len(output["snapshots"])} snapshots')


if __name__ == '__main__':
    main()
