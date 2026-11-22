"""XOT world ranking HTML generator — single-snapshot page styled like the
main worldothellorating site. Reads xot_rating.json, writes pages_xot/index.html.
"""
import os, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(BASE, 'xot_rating.json')
OUT  = os.path.join(BASE, 'pages_xot', 'index.html')

with open(SNAP, encoding='utf-8') as f:
    data = json.load(f)

# Optional previous snapshot (e.g. pre-latest-event) for the diff column.
PREV = os.path.join(BASE, 'xot_prev.json')
prev_r = {}
if os.path.exists(PREV):
    with open(PREV, encoding='utf-8') as f:
        for p in json.load(f)['players']:
            prev_r[p['id']] = p.get('rating')

players = data['players']
tournaments = data.get('xot_tournaments', [])

# Fill missing names/countries from the xot_data ELO rosters: players without
# a WOF id (synthetic 99xxxxx range) or not yet in joueurs.txt still carry
# their name on every roster line — never show "? ?" when the file knows.
XOT_DIR = os.path.join(os.path.dirname(BASE), 'xot_data')
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
for p in players:
    if (p.get('surname') or '?').strip() in ('', '?') and p['id'] in roster:
        sn, fn, co = roster[p['id']]
        p['surname'], p['firstname'] = sn, fn
        if (p.get('country') or '?').strip() in ('', '?', '???'):
            p['country'] = co
ref_date = data.get('ref_date', '')
n_games = data.get('n_games_total', sum(t['games'] for t in tournaments))

# Tournaments sorted newest first for the badge legend
tournaments_sorted = sorted(tournaments, key=lambda t: t.get('date',''), reverse=True)

# Short tournament label = drop the YYYYMMDD_ prefix
def short(t):
    n = t['name']
    return n[9:] if len(n) > 9 and n[8] == '_' else n

# Compact players for JS: id, full name, country, rating, games, active, prov, tourns
def country_code(c):
    return (c or '').upper()

players_js = []
for p in players:
    players_js.append({
        'id': p['id'],
        'fn': p.get('firstname',''),
        'sn': p.get('surname','').title(),
        'c':  country_code(p.get('country','')),
        'r':  int(round(p.get('rating', 0))),
        'g':  p.get('games_played', 0),
        'pr': 1 if p.get('provisional') else 0,
        'l':  p.get('last_played',''),
        'ts': [short({'name': t}) for t in p.get('tournaments', [])],
        'd':  (int(round(p.get('rating', 0) - prev_r[p['id']]))
               if p['id'] in prev_r and prev_r[p['id']] is not None else None),
    })

# Sort by rating desc (already in API order, but resort here for safety)
players_js.sort(key=lambda p: -p['r'])

CONTINENT = {
    'JPN':'Asia&Oceania&Africa','CHN':'Asia&Oceania&Africa','SGP':'Asia&Oceania&Africa','MNG':'Asia&Oceania&Africa',
    'AUS':'Asia&Oceania&Africa','HKG':'Asia&Oceania&Africa','TWN':'Asia&Oceania&Africa','MYS':'Asia&Oceania&Africa',
    'IND':'Asia&Oceania&Africa','THA':'Asia&Oceania&Africa','KOR':'Asia&Oceania&Africa',
    'BEL':'Europe','NLD':'Europe','DEU':'Europe','FRA':'Europe','ITA':'Europe','ESP':'Europe',
    'GBR':'Europe','SWE':'Europe','NOR':'Europe','DNK':'Europe','POL':'Europe','CZE':'Europe',
    'FIN':'Europe','HUN':'Europe','RUS':'Europe','UKR':'Europe','GRC':'Europe','PRT':'Europe',
    'CHE':'Europe','AUT':'Europe','IRL':'Europe','TUR':'Europe',
    'USA':'America','CAN':'America','BRA':'America','ARG':'America','MEX':'America','CHL':'America',
}

countries = sorted({p['c'] for p in players_js if p['c']})

HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>World Othello XOT Rating</title>
<style>
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       margin: 0; background: #f7fafc; color: #2d3748; }
.container { max-width: 1180px; margin: 0 auto; padding: 24px; }
h1 { margin: 0 0 4px; font-size: 26px; }
.subtitle { color: #4a5568; margin: 0 0 18px; font-size: 14px; }
.stats { display: flex; gap: 14px; margin-bottom: 18px; flex-wrap: wrap; }
.stat { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px; flex: 1 1 200px; }
.stat .label { font-size: 11px; color: #718096; text-transform: uppercase; letter-spacing: 0.05em; }
.stat .value { font-size: 22px; font-weight: 700; color: #2b6cb0; }
.filters { display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
           background: white; border: 1px solid #e2e8f0; border-radius: 8px;
           padding: 12px 14px; margin-bottom: 14px; font-size: 13px; }
.filters input, .filters select { padding: 7px 9px; border: 1px solid #cbd5e0;
                                  border-radius: 6px; font-size: 14px; }
.filters label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.search { min-width: 220px; }
table { width: 100%; border-collapse: collapse; background: white;
        border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }
th, td { padding: 7px 11px; border-bottom: 1px solid #edf2f7; text-align: left; font-size: 14px; }
th { background: #edf2f7; color: #4a5568; font-size: 12px; text-transform: uppercase;
     letter-spacing: 0.04em; }
tbody tr:hover { background: #f7fafc; }
.rank, .rating, .games { text-align: right; font-variant-numeric: tabular-nums; }
.rating { font-weight: 700; color: #2b6cb0; }
.prov { display: inline-block; padding: 1px 5px; margin-left: 6px; font-size: 10px;
        background: #cbd5e0; color: #2d3748; border-radius: 3px; }
.t-count { display: inline-block; min-width: 26px; text-align: center;
           padding: 1px 7px; background: #2b6cb0; color: white; border-radius: 10px;
           font-size: 11px; font-weight: 700; cursor: help; }
.visible-count { color: #718096; font-size: 13px; }
.t-list { margin-top: 18px; padding: 14px 16px; background: white;
          border: 1px solid #e2e8f0; border-radius: 8px; font-size: 13px; }
.t-list h3 { margin: 0 0 8px; font-size: 14px; color: #4a5568; text-transform: uppercase;
             letter-spacing: 0.04em; }
.t-list ul { margin: 0; padding: 0; list-style: none; columns: 2; }
.t-list li { padding: 2px 0; color: #2d3748; }
.t-list .t-date { color: #718096; margin-right: 8px; font-variant-numeric: tabular-nums; }
.t-list .t-games { color: #a0aec0; margin-left: 6px; font-size: 11px; }
.footer { margin-top: 18px; color: #718096; font-size: 12px; text-align: center; }
</style>
</head>
<body>
<div class="container">
<h1>World Othello XOT Rating</h1>
<p class="subtitle">The world ranking for XOT.</p>

<div class="stats">
  <div class="stat"><div class="label">Reference date</div><div class="value">__REF_DATE__</div></div>
  <div class="stat"><div class="label">XOT tournaments</div><div class="value">__N_TOURNS__</div></div>
  <div class="stat"><div class="label">XOT games</div><div class="value">__N_GAMES__</div></div>
  <div class="stat"><div class="label">Players ranked</div><div class="value">__N_PLAYERS__</div></div>
</div>

<div class="filters">
  <input type="text" class="search" id="search" placeholder="Search player..." />
  <select id="continent-filter"><option value="">All continents</option><option>Europe</option><option>Asia&Oceania&Africa</option><option>America</option></select>
  <select id="country-filter"><option value="">All countries</option>__COUNTRY_OPTIONS__</select>
  <select id="tourn-filter"><option value="">All tournaments</option>__TOURN_OPTIONS__</select>
  <label><input type="checkbox" id="hide-prov" /> Hide provisional</label>
  <span class="visible-count" id="visible-count"></span>
</div>

<table id="rt">
  <thead><tr><th class="rank">#</th><th>Player</th><th>Country</th><th class="rating">Rating</th><th class="rating">&Delta;</th><th class="games">Games</th><th title="hover a count for the tournament names">Tourn.</th></tr></thead>
  <tbody id="rt-body"></tbody>
</table>

<div class="t-list">
  <h3>XOT tournaments included (__N_TOURNS__)</h3>
  <ul>__T_LIST__</ul>
</div>

<p class="footer">Strict-FIDE Elo on XOT tournaments only. Scale matches the main worldothellorating site (shift-1800). K=40/20/10 with two-pass bootstrap. Ratings are provisional until a player has 30 XOT games.<br>
Built __REF_DATE__ — <a href="https://www.worldothello.org/">worldothello.org</a> · <a href="https://flipthedisc.com/">flipthedisc.com</a></p>
</div>

<script>
const PLAYERS = __PLAYERS_JSON__;
const LATEST = __LATEST_JSON__;  // most recent event: diffs shown only for its participants
const CONTINENT = __CONTINENT_JSON__;

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// Global rank = position in the full rating-sorted list, independent of
// any active filter (searching a player must show their real ranking).
PLAYERS.forEach((p, i) => { p.rank = i + 1; });

function render() {
    const q = document.getElementById('search').value.trim().toLowerCase();
    const cont = document.getElementById('continent-filter').value;
    const country = document.getElementById('country-filter').value;
    const tourn = document.getElementById('tourn-filter').value;
    const hideProv = document.getElementById('hide-prov').checked;
    const rows = [];
    let visible = 0;
    PLAYERS.forEach(p => {
        const full = (p.fn + ' ' + p.sn).toLowerCase();
        if (q && !full.includes(q)) return;
        if (cont && CONTINENT[p.c] !== cont) return;
        if (country && p.c !== country) return;
        if (tourn && !(p.ts || []).includes(tourn)) return;
        if (hideProv && p.pr) return;
        visible++;
        const prov = p.pr ? '<span class="prov">prov</span>' : '';
        // Tournament count; full names on hover (newest first)
        const tsList = (p.ts || []).slice().reverse();
        const badges = tsList.length
            ? `<span class="t-count" title="${escapeHtml(tsList.join(String.fromCharCode(10)))}">${tsList.length}</span>`
            : '';
        // Diff in rating points vs previous snapshot. Shown for everyone;
        // provisional players' deltas are muted (K=40 bootstrap swings).
        // Diff = rating change from the LATEST event, so only its
        // participants get one. (A full-recompute baseline lets the two-pass
        // bootstrap drift NON-participants by a point - never show that.)
        let dcell = '';
        if ((p.ts || []).includes(LATEST)) {
            if (p.d === null || p.d === undefined) {
                dcell = '<span style="color:#a0aec0">new</span>';
            } else if (p.d !== 0) {
                let cls = p.d > 0 ? 'color:#2f855a' : 'color:#c53030';
                if (p.pr) cls += ';opacity:0.45;font-weight:400';
                dcell = `<span style="${cls}">${p.d > 0 ? '+' : ''}${p.d}</span>`;
            }
        }
        rows.push(`<tr><td class="rank">${p.rank}</td><td>${escapeHtml(p.fn)} ${escapeHtml(p.sn)}${prov}</td><td>${escapeHtml(p.c)}</td><td class="rating">${p.r}</td><td class="rating">${dcell}</td><td class="games">${p.g}</td><td>${badges}</td></tr>`);
    });
    document.getElementById('rt-body').innerHTML = rows.join('');
    document.getElementById('visible-count').textContent = `${visible} of ${PLAYERS.length} players`;
}

['search','continent-filter','country-filter','tourn-filter','hide-prov'].forEach(id =>
    document.getElementById(id).addEventListener('input', render));
render();
</script>
</body>
</html>
'''

t_list_items = ''.join(
    f'<li><span class="t-date">{t["date"]}</span>{short(t)}<span class="t-games">({t["games"]} games)</span></li>'
    for t in tournaments_sorted
)
country_options = ''.join(f'<option>{c}</option>' for c in countries)
# Tournament filter options, newest first (the live/latest event on top)
tourn_options = ''.join(f'<option>{short(t)}</option>' for t in tournaments_sorted)

html = (HTML
    .replace('__REF_DATE__', ref_date[:10] if ref_date else '')
    .replace('__N_TOURNS__', str(len(tournaments)))
    .replace('__N_GAMES__', str(n_games))
    .replace('__N_PLAYERS__', str(len(players_js)))
    .replace('__COUNTRY_OPTIONS__', country_options)
    .replace('__TOURN_OPTIONS__', tourn_options)
    .replace('__LATEST_JSON__', json.dumps(short(tournaments_sorted[0]) if tournaments_sorted else ''))
    .replace('__T_LIST__', t_list_items)
    .replace('__PLAYERS_JSON__', json.dumps(players_js, ensure_ascii=False))
    .replace('__CONTINENT_JSON__', json.dumps(CONTINENT))
)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w', encoding='utf-8') as f:
    f.write(html)
print(f'Wrote {OUT} ({len(html)//1024} KB)')
