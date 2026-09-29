"""Convert a worldothello.org tournament page into a .ELO file.

The WOF ratings site publishes, per tournament, a standings block (with WOF
player ids) and a 'Here are all results' games table (black player, disc
score, white player, winner marked by <span class="winner">). That is enough
to rebuild a rateable .ELO file for events we never received directly
(federation submissions like the Czech GPO series).

Winner comes from each side's own winner class, never from the score alone,
so adjusted results and 32-32 playoff wins are kept (same lesson as the
katouche same-surname bug). Rounds are reconstructed greedily: a new round
starts when a player would appear twice.

Usage: python wof_page_to_elo.py <tournamentID> <output_filename.ELO>
"""
import io
import os
import re
import sys
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(BASE)


def fetch(tid):
    url = f'https://www.worldothello.org/ratings/tournament?tournamentID={tid}'
    return urllib.request.urlopen(url, timeout=30).read().decode('utf-8', 'replace')


def convert(tid, out_name=None):
    html = fetch(tid)

    m = re.search(r'<span class="tournamentStartDate">(\d{4})-(\d{2})-(\d{2})</span>:\s*'
                  r'<span class="tournamentName">([^<]+)</span>'
                  r'<span class="countryName">\(([^)]+)\)</span>', html)
    if not m:
        raise SystemExit(f'{tid}: no tournament header found')
    yyyy, mm, dd, name, country = m.groups()
    name, country = name.strip(), country.strip()

    def key(s):
        return ' '.join(s.split()).casefold()

    CC = {'Denmark': 'DNK', 'Czech Republic': 'CZE', 'France': 'FRA',
          'Israel': 'ISR', 'Great-Britain': 'GBR', 'Great Britain': 'GBR',
          'Sweden': 'SWE', 'Norway': 'NOR', 'Germany': 'DEU', 'Italy': 'ITA',
          'Netherlands': 'NLD', 'The Netherlands': 'NLD', 'Belgium': 'BEL',
          'Poland': 'POL', 'Spain': 'ESP', 'Switzerland': 'CHE', 'USA': 'USA',
          'Finland': 'FIN', 'Austria': 'AUT', 'Portugal': 'PRT', 'Japan': 'JPN',
          'Hong-Kong': 'HKG', 'Hong Kong': 'HKG', 'Russia': 'RUS',
          'China': 'CHN', 'Korea': 'KOR', 'Australia': 'AUS'}

    # Roster: id -> (display name, country) from the List of players anchors.
    roster = {}
    for pm in re.finditer(r'playerID=(\d+)">([^<(]+?)\s*\(([^)]*)\)</a>', html):
        roster[int(pm.group(1))] = (' '.join(pm.group(2).split()), pm.group(3).strip())

    # Primary id source: the List of players anchors — same name format as
    # the games table. Standings rows (which sometimes lack the country
    # column and use mixed case) are only a fallback.
    ids = {}
    for pm in re.finditer(r'playerID=(\d+)">([^<(]+?)\s*\([^)]*\)</a>', html):
        ids[key(pm.group(2))] = int(pm.group(1))
    for sm in re.finditer(r'^\s*\+?\s*(\d+),\s*([^,\n]+),\s*([^,\n]+?)\s*(?:,|$)',
                          html, re.M):
        ids.setdefault(key(f'{sm.group(2).strip()} {sm.group(3).strip()}'),
                       int(sm.group(1)))

    game_re = re.compile(
        r'<tr class="game (?:even|odd)">'
        r'<td class="blackPlayer"><span( class="winner")?>([^<]+)</span></td>'
        r'<td class="score">(\d+)-(\d+)</td>'
        r'<td class="whitePlayer"><span( class="winner")?>([^<]+)</span></td>'
        r'</tr>')
    games = []
    for gm in game_re.finditer(html):
        bwin, black, sb, sw, wwin, white = gm.groups()
        black, white = key(black), key(white)
        if black not in ids or white not in ids:
            raise SystemExit(f'{tid}: player not in standings: {black!r} / {white!r}')
        glyph = '>' if bwin else ('<' if wwin else '=')
        games.append((ids[black], int(sb), glyph, int(sw), ids[white]))
    if not games:
        raise SystemExit(f'{tid}: no games found on page')

    # Greedy round split: new round when a player repeats.
    rounds, cur, seen = [], [], set()
    for g in games:
        if g[0] in seen or g[4] in seen:
            rounds.append(cur)
            cur, seen = [], set()
        cur.append(g)
        seen |= {g[0], g[4]}
    rounds.append(cur)

    out_name = out_name or f'{yyyy}{mm}{dd}_{re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")}.ELO'
    out_path = os.path.join(PROJECT, 'wof_results', yyyy, out_name)
    lines = [f'%%Tournament: {name}',
             f'%%Country: {country}',
             f'%%Date: {dd}/{mm}/{yyyy}',
             '%%Sender: WOF site import', '',
             '%%Creator: wof_page_to_elo.py',
             f'%_% See: https://www.worldothello.org/ratings/tournament?tournamentID={tid}', '',
             '%        ID, NAME, Firstname, COUNTRY, score, disc-count', '']
    for pid in sorted({p for g in games for p in (g[0], g[4])}):
        nm, ctry = roster.get(pid, ('? ?', ''))
        # Surname = the leading all-caps tokens of the display name.
        parts = nm.split()
        n_sur = 0
        for t in parts[:-1] if len(parts) > 1 else parts:
            if t == t.upper():
                n_sur += 1
            else:
                break
        n_sur = max(n_sur, 1)
        surname = ' '.join(parts[:n_sur])
        first = ' '.join(parts[n_sur:]) or '-'
        lines.append(f'%_% {pid:>7}, {surname}, {first}, {CC.get(ctry, "???")}, 0, 0')
    lines.append('')
    for i, rd in enumerate(rounds, 1):
        lines.append(f'%Round: {i}')
        lines.append('')
        for b, sb, glyph, sw, w in rd:
            lines.append(f' {b:>6} ({sb:02d}){glyph}({sw:02d}) {w:>7}  B')
        lines.append('')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'{tid}: {out_name}: {len(ids)} players, {len(games)} games, '
          f'{len(rounds)} rounds')
    return out_path


if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    convert(int(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else None)
