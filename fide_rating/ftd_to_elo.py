"""Convert a cached FTD tournament JSON to the .ELO file format used by WOF.

Reads C:/Claude/o_dan/tournament_{id}.json and writes a file at the
corresponding date/name into wof_results/{year}/. Skips games where one of
the players has no WOF id (truly new players).
"""
import os, sys, json, re, argparse
from datetime import datetime
from collections import defaultdict

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
from bel_rating import parse_joueurs

EXTRACT_DIR = os.path.join(PROJECT, 'wof_results')


# FTD reports ISO-2 country codes; WOF rating files use ISO-3.
ISO2_TO_ISO3 = {
    'BE':'BEL','NL':'NLD','FR':'FRA','DE':'DEU','GB':'GBR','UK':'GBR','IT':'ITA','ES':'ESP',
    'SE':'SWE','NO':'NOR','DK':'DNK','FI':'FIN','PL':'POL','CZ':'CZE','CH':'CHE','AT':'AUT',
    'HU':'HUN','GR':'GRC','PT':'PRT','IE':'IRL','RU':'RUS','UA':'UKR','TR':'TUR','IL':'ISR',
    'JP':'JPN','CN':'CHN','TW':'TWN','HK':'HKG','SG':'SGP','MY':'MYS','TH':'THA','IN':'IND',
    'KR':'KOR','MN':'MNG','AU':'AUS','NZ':'NZL','US':'USA','CA':'CAN','MX':'MEX','BR':'BRA',
    'AR':'ARG','CL':'CHL','PE':'PER','UY':'URY','GT':'GTM','SV':'SLV','LT':'LTU','LV':'LVA',
    'EE':'EST','RO':'ROU','BG':'BGR','HR':'HRV','RS':'SRB','SI':'SVN','SK':'SVK','IS':'ISL',
    'MA':'MAR','EG':'EGY','TN':'TUN','ZA':'ZAF','CI':'CIV','ID':'IDN','PH':'PHL','VN':'VNM',
}

def to_iso3(code):
    c = (code or '').upper().strip()
    if len(c) == 2:
        return ISO2_TO_ISO3.get(c, c)
    return c


def slugify(name):
    """Make the FTD tournament name safe for a filename."""
    s = name.replace(' ', '_')
    s = re.sub(r'[^A-Za-z0-9_\-]', '', s)
    return s


def result_glyph_for(p1_score, p2_score):
    if p1_score == p2_score:
        return '='
    return '>' if p1_score > p2_score else '<'


def convert(tournament_id, override_date=None, override_filename=None, force_country=None,
            synthetic_ids=False):
    """synthetic_ids: when True, players without a WOF id get a synthetic id
    99_0<ftd_id> (7-digit range far outside WOF's country-prefixed scheme) so a
    tournament of entirely-new players (e.g., a first national event) can still
    be rated as a closed pool. Replace with WOF's official file once IDs are
    assigned."""
    cache = os.path.join(PROJECT, f'tournament_{tournament_id}.json')
    with open(cache, encoding='utf-8') as f:
        d = json.load(f)
    info = d.get('info', {})
    players_list = d.get('players_list', [])
    rounds = d.get('rounds', [])
    joueurs = parse_joueurs()

    # Build FTD -> WOF lookup. For players without a linked wof_id, try an exact
    # (surname, firstname) match against joueurs.txt — FTD organizers often skip
    # linking even for long-established players. synthetic_ids covers the rest.
    name_to_wof = {}
    for _wid, _jp in joueurs.items():
        _sn = (_jp.get('surname') or '').strip().lower()
        _fn = (_jp.get('firstname') or '').strip().lower()
        if _sn and _fn:
            name_to_wof[(_sn, _fn)] = _wid
    ftd_to_wof = {}
    p_info_by_wof = {}
    for s in players_list:
        wid = s.get('wof_id')
        fid = s.get('id')
        if not wid and fid:
            key = ((s.get('surname') or '').strip().lower(), (s.get('name') or '').strip().lower())
            wid = name_to_wof.get(key)
            if wid:
                print(f'  name-matched: {s.get("surname")} {s.get("name")} -> WOF {wid}')
        if not wid and fid and synthetic_ids:
            wid = 9900000 + int(fid)   # reserved synthetic range
        if wid and fid:
            ftd_to_wof[fid] = wid
            p_info_by_wof[wid] = {
                'surname': (s.get('surname') or '').upper(),
                'firstname': (s.get('name') or '').strip(),
                'country': to_iso3(s.get('country_code')),
                'rating': s.get('rating') or 0,
            }

    # Gather games
    rounds_out = defaultdict(list)  # round_label -> list of (id1, sc1, glyph, sc2, id2)
    scores = defaultdict(float)
    disc_counts = defaultdict(int)

    for rd in rounds:
        if not isinstance(rd, dict):
            continue
        cr = rd.get('currentRound', 0)
        # Map currentRound 1..N to label "N", 108→"SF", 109→"3-4", 110→"F"
        if cr == 108:
            r_label = 'SF'
        elif cr == 109:
            r_label = '3-4'
        elif cr == 110:
            r_label = 'F'
        else:
            r_label = str(cr)

        for pair in rd.get('pairing') or []:
            if not isinstance(pair, list) or len(pair) < 2:
                continue
            p1, p2 = pair[0], pair[1]
            if not isinstance(p1, dict) or not isinstance(p2, dict):
                continue
            r = p1.get('result')
            if r is None:
                continue
            id1 = p1.get('id'); id2 = p2.get('id')
            w1 = ftd_to_wof.get(id1); w2 = ftd_to_wof.get(id2)
            if not w1 or not w2:
                continue
            # Determine scores. For draws (r=1) and wins/losses based on result/score field.
            s1 = p1.get('score')
            if s1 is None:
                # Try to derive from result code alone (no disc count available)
                if r == 2:
                    s1, s2 = 64, 0  # placeholder for win
                elif r == 0:
                    s1, s2 = 0, 64
                elif r == 1:
                    s1, s2 = 32, 32
                else:
                    continue
            else:
                s2 = 64 - s1 if r != 1 else 32
                if r == 1:
                    s1 = 32
            glyph = result_glyph_for(s1, s2)
            rounds_out[r_label].append((w1, s1, glyph, s2, w2))
            # Score: 1 / 0.5 / 0
            if r == 2:
                scores[w1] += 1
            elif r == 0:
                scores[w2] += 1
            else:
                scores[w1] += 0.5; scores[w2] += 0.5
            disc_counts[w1] += s1
            disc_counts[w2] += s2

    # Order rounds: numeric first (1..N), then SF, 3-4, F
    def round_sort_key(lbl):
        if lbl == 'SF': return (1, 0)
        if lbl == '3-4': return (1, 1)
        if lbl == 'F': return (1, 2)
        try:
            return (0, int(lbl))
        except ValueError:
            return (2, lbl)
    ordered_rounds = sorted(rounds_out.keys(), key=round_sort_key)

    # Determine date / filename
    expected_start = info.get('expected_start') or ''
    if override_date:
        date_obj = override_date
    elif expected_start:
        date_obj = datetime.strptime(expected_start[:10], '%Y-%m-%d')
    else:
        date_obj = datetime.today()
    date_str = date_obj.strftime('%Y%m%d')
    date_fmt = date_obj.strftime('%d/%m/%Y')

    name = info.get('name') or f'FTD_{tournament_id}'
    city = info.get('city') or ''
    country_code = (force_country or info.get('country_code') or 'WO').upper()
    country_name = country_code

    fname = override_filename or f'{date_str}_{slugify(name)}.ELO'
    year_dir = os.path.join(EXTRACT_DIR, str(date_obj.year))
    os.makedirs(year_dir, exist_ok=True)
    out_path = os.path.join(year_dir, fname)

    # Players sorted by score desc, disc desc
    sorted_players = sorted(
        p_info_by_wof.keys(),
        key=lambda pid: (-scores.get(pid, 0), -disc_counts.get(pid, 0))
    )

    lines = []
    lines.append(f'%%Tournament: {name}')
    lines.append(f'%%Country: {country_name}')
    lines.append(f'%%Date: {date_fmt}')
    lines.append('%%Sender: auto')
    lines.append('')
    lines.append('%%Creator: FlipTheDisc.com')
    lines.append('')
    lines.append('%        id, lastname, firstname, country, score, disc-count, rating')
    lines.append('')
    for pid in sorted_players:
        p = p_info_by_wof[pid]
        sc = scores.get(pid, 0)
        sc_str = f'{sc:.1f}'.rstrip('0').rstrip('.') if sc != int(sc) else str(int(sc))
        dc = disc_counts.get(pid, 0)
        lines.append(f'%_% {pid:>6}, {p["surname"]}, {p["firstname"]}, {p["country"]}, '
                     f'{sc_str}, {dc}, {p["rating"]}')
    lines.append('%_%__________')
    lines.append('%_% Generated from FTD via ftd_to_elo.py')
    lines.append(f'%_% See: https://flipthedisc.com/live/{tournament_id}')
    lines.append('')
    for r_lbl in ordered_rounds:
        lines.append(f'%Round: {r_lbl}')
        lines.append('')
        for w1, s1, glyph, s2, w2 in rounds_out[r_lbl]:
            lines.append(f' {w1:>5} ({s1:02d}){glyph}({s2:02d}) {w2:>6}  B')
        lines.append('')

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'Wrote {out_path}: {len(sorted_players)} players, '
          f'{sum(len(v) for v in rounds_out.values())} games, {len(ordered_rounds)} rounds')
    return out_path


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('tournament_id', type=int)
    ap.add_argument('--date', help='Override date YYYY-MM-DD')
    ap.add_argument('--filename', help='Override output filename')
    args = ap.parse_args()
    od = datetime.strptime(args.date, '%Y-%m-%d') if args.date else None
    convert(args.tournament_id, override_date=od, override_filename=args.filename)
