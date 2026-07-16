"""Parse the official JOA 19th Ouza-sen crosstable
(https://www.othello.gr.jp/data/tour/830209/current.html, saved as
Japan/ouza19_current.html) and write the definitive .ELO file, replacing the
partial screenshot-derived version.

Each game appears twice (once per row); complementarity is validated
(winner's cell says 'win', loser's says 'loss'). Byes are excluded from games.
"""
import io, sys, os, re, html as H, unicodedata
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
text = open(os.path.join(HERE, 'ouza19_current.html'), encoding='utf-8').read()

rows = re.findall(r'<tr class="entry (?:odd|even)">(.*?)</tr>', text, re.S)
def cell(row, cls):
    m = re.search(r'<div class="'+cls+r'[^"]*"><span>(.*?)</span>', row)
    return H.unescape(m.group(1)).strip() if m else ''

players = []
for row in rows:
    tds = re.findall(r'<td class="match">(.*?)</td>', row, re.S)
    matches = []
    for rnd, td in enumerate(tds, 1):
        m = re.search(r'<div class="opponent ([a-z]+)"><span>(.*?)</span>', td)
        if m:
            matches.append((rnd, m.group(1), H.unescape(m.group(2)).strip()))
    players.append({'place': cell(row, 'place'), 'name': cell(row, 'name'),
                    'dan': cell(row, 'dan'), 'pts': cell(row, 'pts'),
                    'abbr': cell(row, 'abbr'), 'matches': matches})

by_abbr = {p['abbr']: p for p in players}
assert len(by_abbr) == len(players), 'duplicate abbreviations'

# --- validate complementarity & collect unique games ---
games = {}   # (round, winner_abbr, loser_abbr)
problems = []
for p in players:
    for rnd, res, opp in p['matches']:
        if opp == 'bye' or res == 'bye':
            continue
        q = by_abbr.get(opp)
        if q is None:
            problems.append(f"{p['abbr']} R{rnd}: unknown opponent {opp}")
            continue
        # opponent's same-round cell must point back with the opposite result
        back = [(r2, c2, o2) for r2, c2, o2 in q['matches'] if r2 == rnd]
        if not back or back[0][2] != p['abbr'] or back[0][1] == res:
            problems.append(f"{p['abbr']} R{rnd} vs {opp}: no complementary back-reference {back}")
        key = (rnd, p['abbr'], opp) if res == 'win' else (rnd, opp, p['abbr'])
        games[key] = True

print(f'players: {len(players)}   unique games: {len(games)}   problems: {len(problems)}')
for pr in problems:
    print('  PROBLEM:', pr)

# --- map to WOF ids ---
df = pd.read_excel(r'C:/Users/schotte/OneDrive - TomTom/Documents/Othello/Japan/20260608_JapanesePlayers_translated.xlsx',
                   header=None).iloc[:, :4]
df.columns = ['kanji', 'wof_id', 'sn', 'fn']
VAR = {'髙':'高', '澤':'沢', '﨑':'崎', '齋':'斎', '齊':'斉', '讓':'譲'}
def norm(k):
    k = unicodedata.normalize('NFC', str(k)).replace('　', '').replace(' ', '')
    k = re.sub(r'_w$', '', k)           # female marker on the crosstable
    return ''.join(VAR.get(c, c) for c in k)
kmap = {}
for _, r in df.iterrows():
    try:
        wid = int(r['wof_id'])
    except Exception:
        continue
    if wid > 0:
        kmap.setdefault(norm(r['kanji']), (wid, str(r['sn']).upper(), str(r['fn'])))

wof = {}
unmapped = []
for p in players:
    e = kmap.get(norm(p['name']))
    if e:
        wof[p['abbr']] = e
    else:
        unmapped.append(p['name'])
print(f'mapped: {len(wof)}/{len(players)}')
for u in unmapped:
    print('  UNMAPPED:', u)

# --- points from the standings column (優勝/２位 → numeric) ---
def pts_of(p):
    t = p['pts']
    if t == '優勝':
        return 7.0
    if t == '２位':
        return 6.0
    try:
        return float(t)
    except ValueError:
        return 0.0

# --- write ELO (only games where both players map) ---
resolved, dropped = [], []
for (rnd, w_ab, l_ab) in sorted(games):
    w, l = wof.get(w_ab), wof.get(l_ab)
    if w and l:
        resolved.append((rnd, w, l))
    else:
        dropped.append((rnd, w_ab, l_ab))
print(f'resolved games: {len(resolved)}   dropped (unmapped player): {len(dropped)}')
for d in dropped:
    print('  dropped:', d)

lines = [
    '%%Tournament: 19_Ouza_sen',
    '%%Country: Japan',
    '%%Date: 12/07/2026',
    '%%Sender: WOF rating committee (official JOA crosstable othello.gr.jp/data/tour/830209)',
    '',
    '%        id, lastname, firstname, country, score, disc-count',
    '',
]
listed = sorted((p for p in players if p['abbr'] in wof),
                key=lambda p: (-pts_of(p), int(p['place'] or 99)))
for p in listed:
    wid, sn, fn = wof[p['abbr']]
    lines.append(f'%_% {wid:>6}, {sn}, {fn}, JPN, {pts_of(p):.1f}, 0')
lines.append('')
by_round = defaultdict(list)
for rnd, w, l in resolved:
    by_round[rnd].append((w[0], l[0]))
for rnd in sorted(by_round):
    lines.append(f'%Round: {rnd}')
    lines.append('')
    for w, l in by_round[rnd]:
        lines.append(f' {w:>6} (33)>(31) {l:>6}  B')
    lines.append('')
out = os.path.join(ROOT, 'wof_results', '2026', '20260712_19_Ouza_sen.ELO')
open(out, 'w', encoding='utf-8').write('\n'.join(lines))
print(f'Wrote {out}: {len(listed)} players, {len(resolved)} games')
