"""Build a single HTML with a date selector for all FIDE rating snapshots.
Each date shows a diff vs the previous date in the list."""
import json, os
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))

DATES = [
    '2023-12-31',
    '2024-01-31', '2024-02-29', '2024-03-31', '2024-04-30', '2024-05-31',
    '2024-06-30', '2024-07-31', '2024-08-31', '2024-09-30', '2024-10-31',
    '2024-11-30',
    '2024-12-31', '2025-01-31', '2025-02-28', '2025-03-31', '2025-04-30',
    '2025-05-31', '2025-06-30', '2025-07-31', '2025-08-31', '2025-09-30',
    '2025-10-31', '2025-11-30', '2025-12-31', '2026-01-31', '2026-02-28',
    '2026-03-31', '2026-04-30', '2026-05-31', '2026-06-30',
]

# Yearly mode: year-end snapshots 2010-2025, plus current published snapshot for in-progress year.
DATES_YEARLY = [
    '2010-12-31', '2011-12-31', '2012-12-31', '2013-12-31', '2014-12-31',
    '2015-12-31', '2016-12-31', '2017-12-31', '2018-12-31', '2019-12-31',
    '2020-12-31', '2021-12-31', '2022-12-31', '2023-12-31', '2024-12-31',
    '2025-12-31', '2026-06-30',
]

COUNTRY_TO_CONTINENT = {
    # Europe
    'AUT':'EUR','BEL':'EUR','CHE':'EUR','CZE':'EUR','DEU':'EUR','DNK':'EUR','ESP':'EUR',
    'EST':'EUR','FIN':'EUR','FRA':'EUR','GBR':'EUR','GRC':'EUR','HUN':'EUR','IRL':'EUR',
    'ITA':'EUR','LTU':'EUR','LVA':'EUR','NLD':'EUR','NOR':'EUR','POL':'EUR','PRT':'EUR',
    'ROU':'EUR','RUS':'EUR','SWE':'EUR','TUR':'EUR','UKR':'EUR',
    # Asia
    'CHN':'ASI','HKG':'ASI','IND':'ASI','IRN':'ASI','ISR':'ASI','JPN':'ASI','KAZ':'ASI',
    'KOR':'ASI','LKA':'ASI','MNG':'ASI','MYS':'ASI','SGP':'ASI','THA':'ASI','TWN':'ASI',
    'VNM':'ASI',
    # Africa
    'CIV':'AFR','DZA':'AFR','EGY':'AFR','ZAF':'AFR',
    # North America
    'CAN':'NAM','GTM':'NAM','MEX':'NAM','USA':'NAM','SLV':'NAM',
    # South America
    'ARG':'SAM','BRA':'SAM','URU':'SAM','URY':'SAM',
    # Oceania
    'AUS':'OCE','NZL':'OCE',
}
CONTINENT_NAMES = {
    'EUR':'Europe','ASI':'Asia','AFR':'Africa',
    'NAM':'N. America','SAM':'S. America','OCE':'Oceania',
}

COUNTRY_TO_ISO2 = {
    'BEL':'BE','NLD':'NL','GBR':'GB','FRA':'FR','DEU':'DE','ITA':'IT','ESP':'ES','POL':'PL',
    'SWE':'SE','NOR':'NO','DNK':'DK','FIN':'FI','USA':'US','JPN':'JP','THA':'TH','SGP':'SG',
    'HKG':'HK','CHN':'CN','CZE':'CZ','AUT':'AT','AUS':'AU','CAN':'CA','KOR':'KR','IND':'IN',
    'BRA':'BR','PRT':'PT','CHE':'CH','IRL':'IE','ISR':'IL','ARG':'AR','NZL':'NZ','RUS':'RU',
    'UKR':'UA','TUR':'TR','GRC':'GR','MEX':'MX','TWN':'TW','HUN':'HU','ROU':'RO','MNG':'MN',
    'IDN':'ID','MYS':'MY','LKA':'LK','VNM':'VN','PHL':'PH','PAK':'PK','BGD':'BD','KAZ':'KZ',
    'IRN':'IR','EST':'EE','LVA':'LV','LTU':'LT','SVK':'SK','SVN':'SI','HRV':'HR','SRB':'RS',
    'BGR':'BG','MAR':'MA','EGY':'EG','TUN':'TN','ZAF':'ZA','GTM':'GT','URY':'UY','PER':'PE','SLV':'SV',
    'CHL':'CL','VEN':'VE','PRY':'PY','COL':'CO',
}


def slim(p):
    """Keep only the fields the UI needs. Falls back to the augmented joueurs
    dict when the stored snapshot has placeholder '?' values (these were
    written when the player wasn't in joueurs.txt at compute time)."""
    sn = (p.get('surname') or '').strip()
    fn = (p.get('firstname') or '').strip()
    co = (p.get('country') or '').strip()
    if sn in ('', '?') or co in ('', '?', '???'):
        aux = joueurs.get(p['id'], {})
        if sn in ('', '?') and (aux.get('surname') or '').strip():
            sn = aux['surname'].strip()
            fn = (aux.get('firstname') or '').strip() or fn
        if co in ('', '?', '???') and (aux.get('country') or '').strip():
            co = aux['country'].strip()
    if not sn: sn = '?'
    if not fn: fn = ''
    if not co: co = '???'
    out = {
        'id': p['id'],
        'r': round(p['rating'], 1),
        'fn': fn,
        'sn': sn.title() if sn != sn.upper() and len(sn) > 2 else sn,
        'c': co,
        'g': p['games_played'],
        'pr': 1 if p['provisional'] else 0,
        'l': p['last_played'],
    }
    if 'log' in p:
        out['log'] = p['log']
    if 'tournaments' in p:
        out['tournaments'] = p['tournaments']
    return out


# Build a global ID -> name lookup from joueurs.txt for opponents that don't appear in active list
sys_path = os.path.dirname(os.path.dirname(BASE))
import sys
sys.path.insert(0, os.path.dirname(BASE))
from bel_rating import parse_joueurs
joueurs = parse_joueurs()

# Augment joueurs with names extracted from ELO file rosters. WOF sometimes
# uses player IDs that aren't yet published in joueurs.txt (newly registered
# players, FTD tournaments with self-reported IDs, etc.). Without this, the
# main table would show "? ?" for them.
import os as _os
_extract_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'wof_results')
_added = 0
for _root, _, _files in _os.walk(_extract_dir):
    for _fname in _files:
        if not (_fname.endswith('.ELO') or _fname.endswith('.elo')):
            continue
        try:
            with open(_os.path.join(_root, _fname), encoding='utf-8', errors='replace') as _f:
                for _line in _f:
                    if not _line.startswith('%_%'):
                        continue
                    _parts = [_p.strip() for _p in _line[3:].split(',')]
                    if len(_parts) < 4:
                        continue
                    try:
                        _wid = int(_parts[0])
                    except (ValueError, TypeError):
                        continue
                    if _wid <= 0:
                        continue
                    _existing = joueurs.get(_wid, {})
                    _has_sn = bool((_existing.get('surname') or '').strip())
                    _has_co = bool((_existing.get('country') or '').strip())
                    if _has_sn and _has_co:
                        continue
                    if _wid not in joueurs:
                        joueurs[_wid] = {}
                        _added += 1
                    if not _has_sn:
                        joueurs[_wid]['surname']   = _parts[1]
                        joueurs[_wid]['firstname'] = _parts[2]
                    if not _has_co:
                        joueurs[_wid]['country']   = _parts[3]
                    joueurs[_wid].setdefault('provisional', False)
        except Exception:
            continue
print(f'  Augmented joueurs from ELO rosters: +{_added} player records')

snapshots = []
opp_ids_needed = set()
for d in DATES:
    fname = f'world_fide_v2_shift1800_{d.replace("-", "")}.json'
    with open(os.path.join(BASE, fname), encoding='utf-8') as f:
        data = json.load(f)
    slim_players = [slim(p) for p in data['players']]
    for p in slim_players:
        for g in p.get('log', []):
            opp_ids_needed.add(g['o'])
    snapshots.append({
        'date': d,
        'total_games': data['total_games'],
        'total_rated': data['total_rated'],
        'total_active': data['total_active'],
        'players': slim_players,
    })

# Add LIVE snapshot if available
live_path = os.path.join(BASE, 'world_fide_live_shift1800.json')
live_baseline = None  # Extended baseline (incl. inactive) for LIVE diff
live_meta = None
if os.path.exists(live_path):
    with open(live_path, encoding='utf-8') as f:
        live = json.load(f)
    live_slim = []
    for p in live['players']:
        s = slim(p)
        s['ec'] = p.get('ec', 0)
        live_slim.append(s)
    for p in live_slim:
        for g in p.get('log', []):
            opp_ids_needed.add(g['o'])
    snapshots.append({
        'date': 'LIVE',
        'live': True,
        'tournament_name': live.get('tournament_name', ''),
        'tournament_id': live.get('tournament_id'),
        'ec_games_played': live.get('ec_games_played', 0),
        'ec_rounds': live.get('ec_rounds', 0),
        'ref_date': live.get('ref_date', ''),
        'baseline_date': live.get('baseline_date', ''),
        'total_games': 0,
        'total_rated': 0,
        'total_active': live.get('total_active', 0),
        'players': live_slim,
    })
    # Extended baseline (raw lookup from live.json)
    live_baseline = {int(k): v for k, v in live.get('baseline_lookup', {}).items()}
    live_meta = live

# Third name fallback: names carried inside the snapshots themselves. This is
# the ONLY source for FTD-only players with synthetic negative IDs (they exist
# in no roster file: not in joueurs.txt, not in any .ELO).
snap_names = {}
for s in snapshots:
    for p in s['players']:
        _sn = (p.get('sn') or '').strip()
        if p['id'] not in snap_names and _sn not in ('', '?'):
            snap_names[p['id']] = (_sn, (p.get('fn') or '').strip(), (p.get('c') or '').strip())

# Build name lookup keyed by player ID, only for opponents referenced in logs.
# Priority: joueurs.txt (augmented with ELO rosters) → snapshot players → '?'.
name_lookup = {}
for pid in opp_ids_needed:
    jp = joueurs.get(pid, {})
    fn = (jp.get('firstname') or '').strip()
    sn = (jp.get('surname') or '').strip()
    cc = (jp.get('country') or '').strip()
    if not (sn and cc):
        snap = snap_names.get(pid)
        if snap:
            sn = sn or snap[0]
            fn = fn or snap[1]
            cc = cc or snap[2]
    if not fn: fn = '?'
    if not sn: sn = '?'
    if not cc: cc = '???'
    # Prettify surname casing: keep ALL-CAPS as-is, else title-case
    sn_display = sn if sn == sn.upper() else sn.title()
    name_lookup[pid] = {'n': f'{fn} {sn_display}', 'c': cc}

# Build per-player rating history: id -> [r0, r1, ..., r_{n-1}] (None when not in that snapshot)
history = {}
labels = []
for i, s in enumerate(snapshots):
    labels.append('LIVE' if s.get('live') else s['date'])
    for p in s['players']:
        pid = p['id']
        if pid not in history:
            history[pid] = [None] * len(snapshots)
        history[pid][i] = p['r']

# Load YEARLY snapshots (year-end 2010..2025 + current 2026-05-18) — same shape
# as monthly snapshots, but each player's log is PRE-AGGREGATED by tournament:
# the hover only needs net delta + W/D/L per tournament, not every game.
def slim_yearly(p):
    out = {
        'id': p['id'],
        'r': round(p['rating'], 1),
        'fn': p['firstname'],
        'sn': p['surname'].title(),
        'c': p['country'],
        'g': p['games_played'],
        'pr': 1 if p['provisional'] else 0,
        'l': p['last_played'],
    }
    # Aggregate the per-game log by tournament
    log = p.get('log', [])
    if log:
        by_t = {}
        for g in log:
            t = g['t']
            if t not in by_t:
                by_t[t] = {'t': t, 'd': g['d'], 'w': 0, 'l': 0, 'dr_': 0, 'dr': 0.0}
            by_t[t]['dr'] += g['dr']
            s = g['s']
            if s == 1: by_t[t]['w'] += 1
            elif s == 0: by_t[t]['l'] += 1
            else: by_t[t]['dr_'] += 1
        # round net rating delta + sort by date desc
        rows = list(by_t.values())
        for r in rows: r['dr'] = round(r['dr'], 1)
        rows.sort(key=lambda x: x['d'], reverse=True)
        out['tl'] = rows  # 'tl' = tournament log
    return out

snapshots_yearly = []
for d in DATES_YEARLY:
    fname = f'world_fide_v2_shift1800_yearly_{d.replace("-", "")}.json'
    with open(os.path.join(BASE, fname), encoding='utf-8') as f:
        data = json.load(f)
    slim_players = [slim_yearly(p) for p in data['players']]
    snapshots_yearly.append({
        'date': d,
        'total_games': data['total_games'],
        'total_rated': data['total_rated'],
        'total_active': data['total_active'],
        'players': slim_players,
    })
# Refresh name lookup to include any opponents only seen in yearly logs
for pid in opp_ids_needed:
    if pid in name_lookup: continue
    jp = joueurs.get(pid, {})
    name_lookup[pid] = {
        'n': f'{jp.get("firstname", "?")} {jp.get("surname", "?").title()}',
        'c': jp.get('country', '???'),
    }

history_yearly = {}
labels_yearly = []
for i, s in enumerate(snapshots_yearly):
    labels_yearly.append(s['date'])
    for p in s['players']:
        pid = p['id']
        if pid not in history_yearly:
            history_yearly[pid] = [None] * len(snapshots_yearly)
        history_yearly[pid][i] = p['r']

snapshots_json = json.dumps(snapshots, ensure_ascii=False, separators=(',', ':'))
snapshots_yearly_json = json.dumps(snapshots_yearly, ensure_ascii=False, separators=(',', ':'))
country_map_json = json.dumps(COUNTRY_TO_ISO2)
continent_map_json = json.dumps(COUNTRY_TO_CONTINENT)
continent_names_json = json.dumps(CONTINENT_NAMES)
name_lookup_json = json.dumps(name_lookup, ensure_ascii=False, separators=(',', ':'))
live_baseline_json = json.dumps(live_baseline if live_baseline else {}, separators=(',', ':'))
history_json = json.dumps(history, separators=(',', ':'))
history_yearly_json = json.dumps(history_yearly, separators=(',', ':'))
labels_json = json.dumps(labels)
labels_yearly_json = json.dumps(labels_yearly)
has_live = 'true' if live_meta else 'false'

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="300">
<title>World Othello Rating</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       margin: 0; padding: 20px; background: #f5f7fa; color: #2d3748; }}
.container {{ max-width: 1400px; margin: 0 auto; padding-bottom: 360px; }}
h1 {{ margin: 0 0 8px; font-size: 26px; color: #1a202c; }}
.subtitle {{ color: #718096; margin-bottom: 20px; font-size: 14px; }}
.stats {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px;
    margin-bottom: 20px; padding: 14px; background: white;
    border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}}
.stat .label {{ font-size: 11px; color: #718096; text-transform: uppercase; letter-spacing: 0.05em; }}
.stat .value {{ font-size: 22px; font-weight: 700; color: #1a202c; }}
.filters {{ display: flex; gap: 12px; margin-bottom: 12px; align-items: center; flex-wrap: wrap; }}
.filters input, .filters select {{
    padding: 7px 11px; border: 1px solid #cbd5e0; border-radius: 6px; font-size: 14px;
}}
.filters input.search {{ flex: 1; max-width: 280px; }}
.filters label {{ display: flex; gap: 4px; align-items: center; font-size: 13px; color: #4a5568; cursor: pointer; }}
#date-select {{ font-weight: 700; background: #2d3748; color: white; border-color: #2d3748; }}
table {{ width: 100%; border-collapse: collapse; background: white;
         box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-radius: 8px; overflow: hidden; font-size: 14px; }}
th, td {{ padding: 8px 12px; border-bottom: 1px solid #e2e8f0; }}
th {{ background: #2d3748; color: white; font-size: 12px; font-weight: 600; text-align: left;
      cursor: pointer; user-select: none; }}
th:hover {{ background: #4a5568; }}
th.sorted {{ background: #4299e1; }}
tbody tr:hover {{ background: #f7fafc; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
td.rating {{ text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; }}
.flag {{ width: 16px; vertical-align: middle; border: 1px solid rgba(0,0,0,0.1); border-radius: 1px; }}
.cc {{ font-family: monospace; font-size: 11px; color: #718096; margin-left: 4px; }}
.prov {{ display: inline-block; margin-left: 6px; padding: 1px 6px; background: #fed7d7; color: #9b2c2c;
         border: 1px solid #fc8181; border-radius: 8px; font-size: 9px; font-weight: 700; text-transform: uppercase; }}
.visible-count {{ color: #a0aec0; font-size: 12px; }}
.diff-up {{ color: #2f855a; font-weight: 600; }}
.diff-down {{ color: #c53030; font-weight: 600; }}
.diff-flat {{ color: #cbd5e0; }}
.diff-new {{ color: #3182ce; font-weight: 700; font-size: 11px; }}
.diff-cell {{ position: relative; cursor: help; }}
.diff-cell:hover .tip {{ display: block; }}
.tip {{
    display: none; position: absolute; left: 0; top: 100%; z-index: 10;
    background: #1a202c; color: #e2e8f0; padding: 10px 12px; border-radius: 6px;
    font-size: 12px; min-width: 360px; max-width: 480px; white-space: normal;
    box-shadow: 0 4px 14px rgba(0,0,0,0.25); text-align: left;
}}
.tip.flip-up {{ top: auto; bottom: 100%; }}
.tip h4 {{ margin: 0 0 6px; font-size: 12px; color: #fbbf24; font-weight: 700; }}
.tip .t-row {{ margin: 6px 0; padding-bottom: 4px; border-bottom: 1px solid #2d3748; }}
.tip .t-row:last-child {{ border-bottom: none; }}
.tip .t-header {{ display: flex; justify-content: space-between; align-items: baseline; }}
.tip .t-name {{ font-weight: 600; color: white; }}
.tip .t-date {{ color: #a0aec0; font-size: 11px; }}
.tip .t-net {{ font-weight: 700; }}
.tip .t-games {{ margin-top: 2px; color: #cbd5e0; font-size: 11px; }}
.tip .g-up {{ color: #68d391; }}
.tip .g-down {{ color: #fc8181; }}
.tip .g-flat {{ color: #a0aec0; }}
.live-badge {{ display: inline-block; background: #e53e3e; color: white; padding: 2px 8px;
               border-radius: 4px; font-size: 12px; font-weight: 700; vertical-align: middle;
               margin-right: 8px; animation: pulse 2s infinite; }}
@keyframes pulse {{ 0%,100% {{opacity:1;}} 50% {{opacity:0.65;}} }}
#tournament-filter-wrap {{ display: none; position: relative; }}
body.live #tournament-filter-wrap {{ display: inline-block; }}
#tournament-filter-btn {{
    padding: 7px 11px; border: 1px solid #cbd5e0; border-radius: 6px; font-size: 14px;
    background: white; cursor: pointer; min-width: 180px; text-align: left;
}}
#tournament-filter-btn:after {{ content: ' ▾'; color: #718096; font-size: 10px; }}
#tournament-filter-panel {{
    display: none; position: absolute; top: 100%; left: 0; z-index: 50;
    background: white; border: 1px solid #cbd5e0; border-radius: 6px;
    box-shadow: 0 4px 14px rgba(0,0,0,0.12); padding: 8px 12px; min-width: 200px;
    margin-top: 4px;
}}
#tournament-filter-panel.open {{ display: block; }}
#tournament-filter-panel label {{ display: flex; padding: 4px 0; font-size: 13px;
                                  align-items: center; gap: 6px; cursor: pointer; }}
.t-col {{ display: none; }}
body.live .t-col {{ display: table-cell; }}
.t-badge {{ display: inline-block; padding: 1px 6px; margin-right: 4px;
            background: #2b6cb0; color: white; border-radius: 4px;
            font-size: 10px; font-weight: 700; letter-spacing: 0.02em; }}
.name-cell {{ position: relative; cursor: pointer; }}
.name-cell:hover .chart {{ display: block; }}
.chart {{
    display: none; position: absolute; left: 0; top: 100%; z-index: 20;
    background: #1a202c; color: #e2e8f0; padding: 12px 14px 8px; border-radius: 6px;
    box-shadow: 0 4px 14px rgba(0,0,0,0.25); min-width: 460px;
}}
.chart.flip-up {{ top: auto; bottom: 100%; }}
.chart h4 {{ margin: 0 0 6px; font-size: 12px; color: #fbbf24; font-weight: 700; }}
.chart .min-max {{ color: #a0aec0; font-size: 11px; margin-top: 4px; }}
.chart svg {{ display: block; }}
.chart .axis-text {{ fill: #a0aec0; font-size: 9px; }}
.chart .point {{ fill: #4299e1; }}
.chart .point-live {{ fill: #e53e3e; }}
.chart .line {{ fill: none; stroke: #4299e1; stroke-width: 1.5; }}
</style>
</head>
<body>
<div class="container">
<h1>World Othello FIDE-Elo Rating</h1>
<p class="subtitle">Active = game in the last 38 months.</p>

<div class="stats">
    <div class="stat"><div class="label">Reference date</div><div class="value" id="stat-date"></div></div>
    <div class="stat"><div class="label">Total games</div><div class="value" id="stat-games"></div></div>
    <div class="stat"><div class="label">Rated players</div><div class="value" id="stat-rated"></div></div>
    <div class="stat"><div class="label">Active</div><div class="value" id="stat-active"></div></div>
</div>

<div class="filters">
    <div id="view-toggle" style="display:inline-flex;border:1px solid #cbd5e0;border-radius:6px;overflow:hidden;font-size:13px;">
        <button type="button" data-mode="monthly" class="vt-btn active" style="padding:7px 11px;border:0;background:#2d3748;color:white;cursor:pointer;">Monthly</button>
        <button type="button" data-mode="yearly"  class="vt-btn"        style="padding:7px 11px;border:0;background:white;color:#2d3748;cursor:pointer;">Yearly</button>
    </div>
    <select id="date-select"></select>
    <input type="text" class="search" id="search" placeholder="Search player..." />
    <select id="continent-filter"><option value="">All continents</option></select>
    <select id="country-filter"><option value="">All countries</option></select>
    <div id="tournament-filter-wrap">
        <button type="button" id="tournament-filter-btn">Tournaments: All</button>
        <div id="tournament-filter-panel"></div>
    </div>
    <label><input type="checkbox" id="hide-prov" /> Hide provisional</label>
    <label title="Only players with games in this snapshot's month"><input type="checkbox" id="only-active" /> Active this month</label>
    <label title="Only players with a game in the 3 days up to the snapshot date"><input type="checkbox" id="only-active-week" /> Active now</label>
    <span class="visible-count" id="visible-count"></span>
</div>

<table id="ratings-table">
<thead><tr>
    <th data-col="rank">#</th>
    <th data-col="rating" class="sorted">Rating</th>
    <th data-col="drating">DRating</th>
    <th data-col="drank">DRank</th>
    <th data-col="country">Country</th>
    <th data-col="name">Player</th>
    <th data-col="tournament" class="t-col">Tournament</th>
    <th data-col="games">Games</th>
    <th data-col="last">Last played</th>
</tr></thead>
<tbody id="tbody"></tbody>
</table>

<p style="margin-top: 28px; padding: 14px 16px; background: #edf2f7; border-radius: 8px; color: #4a5568; font-size: 12px; line-height: 1.6;">
<strong style="color:#3182ce;">[v2 — strict FIDE bootstrap]</strong><br>
Strict-FIDE variant: rating is locked at performance-of-first-9-games during games 1-9 (no self-updates); K-factor kicks in from game 10. No double counting.
</p>

<script>
const SNAPSHOTS_MONTHLY = {snapshots_json};
const SNAPSHOTS_YEARLY  = {snapshots_yearly_json};
const HISTORY_MONTHLY   = {history_json};
const HISTORY_YEARLY    = {history_yearly_json};
const LABELS_MONTHLY    = {labels_json};
const LABELS_YEARLY     = {labels_yearly_json};
const ISO2 = {country_map_json};
const CONTINENT = {continent_map_json};
const CONTINENT_NAMES = {continent_names_json};
const NAMES = {name_lookup_json};
const LIVE_BASELINE = {live_baseline_json};

// View mode: 'monthly' (default) or 'yearly'. Pointer-style references that
// the rest of the code reads from; swapped by the toggle.
let viewMode = 'monthly';
let SNAPSHOTS = SNAPSHOTS_MONTHLY;
let HISTORY = HISTORY_MONTHLY;
let HISTORY_LABELS = LABELS_MONTHLY;

let snapIdx = SNAPSHOTS.length - 1;  // default to latest (LIVE if present)
let sortCol = 'rating', sortDesc = true;

const dateSelect = document.getElementById('date-select');
function repopulateDropdown() {{
    dateSelect.innerHTML = '';
    // newest first
    for (let i = SNAPSHOTS.length - 1; i >= 0; i--) {{
        const s = SNAPSHOTS[i];
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = s.live ? `LIVE — ${{s.tournament_name || 'Live'}}` : s.date;
        dateSelect.appendChild(opt);
    }}
    dateSelect.value = snapIdx;
}}
repopulateDropdown();
dateSelect.addEventListener('change', () => {{ snapIdx = +dateSelect.value; render(); }});

// View-mode toggle: swap SNAPSHOTS/HISTORY/HISTORY_LABELS references
document.querySelectorAll('#view-toggle .vt-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
        const mode = btn.dataset.mode;
        if (mode === viewMode) return;
        viewMode = mode;
        document.querySelectorAll('#view-toggle .vt-btn').forEach(b => {{
            const active = b.dataset.mode === mode;
            b.classList.toggle('active', active);
            b.style.background = active ? '#2d3748' : 'white';
            b.style.color = active ? 'white' : '#2d3748';
        }});
        if (mode === 'yearly') {{
            SNAPSHOTS = SNAPSHOTS_YEARLY;
            HISTORY = HISTORY_YEARLY;
            HISTORY_LABELS = LABELS_YEARLY;
        }} else {{
            SNAPSHOTS = SNAPSHOTS_MONTHLY;
            HISTORY = HISTORY_MONTHLY;
            HISTORY_LABELS = LABELS_MONTHLY;
        }}
        snapIdx = SNAPSHOTS.length - 1;
        repopulateDropdown();
        render();
    }});
}});

function flag(country) {{
    const iso = ISO2[country] || '';
    if (!iso) return '';
    return `<img class="flag" src="https://flagcdn.com/16x12/${{iso.toLowerCase()}}.png" alt="${{iso}}" />`;
}}

function buildPrevLookup() {{
    const snap = SNAPSHOTS[snapIdx];
    if (snap.live) {{
        // Extended baseline (includes inactive-but-rated players for returning EC participants)
        const lookup = {{}};
        Object.entries(LIVE_BASELINE).forEach(([id, v]) => {{
            lookup[id] = {{ rank: v[0], r: v[1] }};
        }});
        return lookup;
    }}
    if (snapIdx === 0) return null;
    const prev = SNAPSHOTS[snapIdx - 1];
    const lookup = {{}};
    prev.players.forEach((p, i) => {{ lookup[p.id] = {{ rank: i + 1, r: p.r }}; }});
    return lookup;
}}

function escapeHtml(s) {{
    return String(s).replace(/[&<>"']/g, c => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }})[c]);
}}

function buildChart(pid, fullName) {{
    const series = HISTORY[pid];
    if (!series) return '';
    const pts = [];
    series.forEach((r, i) => {{ if (r !== null && r !== undefined) pts.push([i, r]); }});
    if (pts.length < 2) return '';
    const W = 460, H = 130, padL = 38, padR = 12, padT = 22, padB = 22;
    const innerW = W - padL - padR, innerH = H - padT - padB;
    const minR = Math.min(...pts.map(p => p[1]));
    const maxR = Math.max(...pts.map(p => p[1]));
    const rRange = Math.max(maxR - minR, 1);
    const n = series.length;
    const xAt = i => padL + (n === 1 ? innerW / 2 : (i * innerW / (n - 1)));
    const yAt = r => padT + innerH - ((r - minR) / rRange) * innerH;
    const path = pts.map((p, i) => `${{i === 0 ? 'M' : 'L'}}${{xAt(p[0]).toFixed(1)}},${{yAt(p[1]).toFixed(1)}}`).join(' ');
    const dots = pts.map(p => {{
        const isLive = HISTORY_LABELS[p[0]] === 'LIVE';
        return `<circle class="${{isLive ? 'point-live' : 'point'}}" cx="${{xAt(p[0]).toFixed(1)}}" cy="${{yAt(p[1]).toFixed(1)}}" r="${{isLive ? 3 : 2}}"><title>${{HISTORY_LABELS[p[0]]}}: ${{p[1].toFixed(0)}}</title></circle>`;
    }}).join('');
    // X-axis: first and last labels
    const xLabels = `<text class="axis-text" x="${{padL}}" y="${{H - 6}}">${{HISTORY_LABELS[pts[0][0]]}}</text>` +
                    `<text class="axis-text" x="${{W - padR}}" y="${{H - 6}}" text-anchor="end">${{HISTORY_LABELS[pts[pts.length-1][0]]}}</text>`;
    // Y-axis: min, max
    const yLabels = `<text class="axis-text" x="${{padL - 4}}" y="${{padT + 4}}" text-anchor="end">${{maxR.toFixed(0)}}</text>` +
                    `<text class="axis-text" x="${{padL - 4}}" y="${{padT + innerH}}" text-anchor="end">${{minR.toFixed(0)}}</text>`;
    return `<div class="chart"><h4>${{escapeHtml(fullName)}} - rating evolution</h4>` +
           `<svg width="${{W}}" height="${{H}}" viewBox="0 0 ${{W}} ${{H}}">` +
           `<path class="line" d="${{path}}"/>${{dots}}${{xLabels}}${{yLabels}}` +
           `</svg>` +
           `<div class="min-max">${{pts.length}} of ${{n}} snapshots &middot; range ${{minR.toFixed(0)}}-${{maxR.toFixed(0)}} (${{(maxR-minR).toFixed(0)}} pts)</div>` +
           `</div>`;
}}

function prettyTournament(t) {{
    // Strip leading YYYYMMDD_ and replace underscores with spaces
    let name = t.replace(/^\\d{{8}}_/, '').replace(/_/g, ' ');
    return name || t;
}}

function buildTooltipYearly(tl) {{
    // Yearly: pre-aggregated per-tournament summary rows from the Python slim.
    if (!tl || tl.length === 0) return '';
    let parts = ['<div class="tip"><h4>Tournaments this year</h4>'];
    tl.forEach(r => {{
        const netCls = r.dr > 0.5 ? 'diff-up' : (r.dr < -0.5 ? 'diff-down' : 'diff-flat');
        const netStr = (r.dr > 0 ? '+' : '') + r.dr.toFixed(1);
        const wdlParts = [];
        if (r.w) wdlParts.push(`${{r.w}}W`);
        if (r.dr_) wdlParts.push(`${{r.dr_}}D`);
        if (r.l) wdlParts.push(`${{r.l}}L`);
        parts.push(`<div class="t-row"><div class="t-header"><span class="t-name">${{escapeHtml(prettyTournament(r.t))}}</span>`);
        parts.push(`<span class="t-date">${{r.d}} &middot; ${{wdlParts.join('/')}} &middot; <span class="t-net ${{netCls}}">${{netStr}}</span></span></div></div>`);
    }});
    parts.push('</div>');
    return parts.join('');
}}

function buildTooltip(log, provisional) {{
    if (!log || log.length === 0) return '';
    // Group by tournament
    const byT = {{}};
    log.forEach(g => {{
        const key = g.t;
        if (!byT[key]) byT[key] = {{ date: g.d, games: [] }};
        byT[key].games.push(g);
    }});
    // Sort tournaments by date desc
    const ts = Object.entries(byT).sort((a, b) => b[1].date.localeCompare(a[1].date));
    let header;
    if (provisional) header = 'Games this period (provisional — no rating impact)';
    else if (viewMode === 'yearly') header = 'Tournaments this year';
    else header = 'Games this period';
    let parts = [`<div class="tip"><h4>${{header}}</h4>`];
    ts.forEach(([tname, info]) => {{
        const w = info.games.filter(g => g.s === 1).length;
        const d_ = info.games.filter(g => g.s === 0.5).length;
        const l = info.games.filter(g => g.s === 0).length;
        const wdlParts = [];
        if (w) wdlParts.push(`${{w}}W`);
        if (d_) wdlParts.push(`${{d_}}D`);
        if (l) wdlParts.push(`${{l}}L`);
        const wdl = wdlParts.join('/');
        parts.push(`<div class="t-row">`);
        parts.push(`<div class="t-header"><span class="t-name">${{escapeHtml(prettyTournament(tname))}}</span>`);
        if (provisional) {{
            parts.push(`<span class="t-date">${{info.date}} &middot; ${{wdl}}</span></div>`);
        }} else {{
            const net = info.games.reduce((s, g) => s + g.dr, 0);
            const netCls = net > 0.5 ? 'diff-up' : (net < -0.5 ? 'diff-down' : 'diff-flat');
            const netStr = (net > 0 ? '+' : '') + net.toFixed(1);
            parts.push(`<span class="t-date">${{info.date}} &middot; ${{wdl}} &middot; <span class="t-net ${{netCls}}">${{netStr}}</span></span></div>`);
        }}
        // In yearly mode, omit the per-game breakdown — the diff window covers a full year
        // and listing every game would be unreadable.
        if (viewMode !== 'yearly') {{
            parts.push(`<div class="t-games">`);
            const lines = info.games.map(g => {{
                const opp = NAMES[g.o];
                const oppName = opp ? opp.n : `#${{g.o}}`;
                const oppCc = opp ? opp.c : '';
                const symbol = g.s === 1 ? 'W' : (g.s === 0 ? 'L' : 'D');
                if (provisional) {{
                    return `${{symbol}} vs ${{escapeHtml(oppName)}}${{oppCc ? ' [' + oppCc + ']' : ''}}`;
                }}
                const drCls = g.dr > 0.05 ? 'g-up' : (g.dr < -0.05 ? 'g-down' : 'g-flat');
                const drStr = (g.dr > 0 ? '+' : '') + g.dr.toFixed(1);
                return `${{symbol}} vs ${{escapeHtml(oppName)}}${{oppCc ? ' [' + oppCc + ']' : ''}} <span class="${{drCls}}">${{drStr}}</span>`;
            }});
            parts.push(lines.join('<br>'));
            parts.push(`</div>`);
        }}
        parts.push(`</div>`);
    }});
    parts.push('</div>');
    return parts.join('');
}}

function diffCells(pid, currR, currRank, prevLookup, log, tl) {{
    if (!prevLookup) return '<td class="num diff-flat">-</td><td class="num diff-flat">-</td>';
    const prev = prevLookup[pid];
    if (!prev) {{
        // New player: show games tooltip without rating-delta columns
        const tip = (log && log.length) ? buildTooltip(log, true) : '';
        if (tip) {{
            return `<td class="num diff-cell diff-new">NEW${{tip}}</td><td class="num diff-new">NEW</td>`;
        }}
        return '<td class="num diff-new">NEW</td><td class="num diff-new">NEW</td>';
    }}
    const dr = currR - prev.r;
    const rCls = dr > 0.5 ? 'diff-up' : (dr < -0.5 ? 'diff-down' : 'diff-flat');
    const rStr = Math.abs(dr) >= 0.5 ? (dr > 0 ? '+' : '') + dr.toFixed(1) : '0';
    let tooltip = '';
    if (viewMode === 'yearly' && tl && tl.length) tooltip = buildTooltipYearly(tl);
    else if (log && log.length) tooltip = buildTooltip(log);
    const rCell = tooltip
        ? `<td class="num diff-cell ${{rCls}}">${{rStr}}${{tooltip}}</td>`
        : `<td class="num ${{rCls}}">${{rStr}}</td>`;
    let kCell;
    if (prev.rank === null || prev.rank === undefined) {{
        kCell = `<td class="num diff-new" title="Returning player">RET</td>`;
    }} else {{
        const dk = prev.rank - currRank;
        const kCls = dk > 0 ? 'diff-up' : (dk < 0 ? 'diff-down' : 'diff-flat');
        const kStr = dk !== 0 ? (dk > 0 ? '+' : '') + dk : '0';
        kCell = `<td class="num ${{kCls}}">${{kStr}}</td>`;
    }}
    return `${{rCell}}${{kCell}}`;
}}

function render() {{
    const snap = SNAPSHOTS[snapIdx];
    document.body.classList.toggle('live', !!snap.live);
    if (snap.live) {{
        document.getElementById('stat-date').innerHTML = '<span class="live-badge">LIVE</span>' + (snap.ref_date || '');
        document.getElementById('stat-games').textContent = (snap.ec_games_played || 0).toLocaleString();
        document.getElementById('stat-rated').textContent = (snap.ec_rounds || 0).toLocaleString();
        document.getElementById('stat-active').textContent = snap.total_active.toLocaleString();
        document.querySelector('.stats .stat:nth-child(2) .label').textContent = 'Live games applied';
        document.querySelector('.stats .stat:nth-child(3) .label').textContent = 'Rounds';
        // Populate tournament filter panel from this snapshot's players
        const tCounts = {{}};
        snap.players.forEach(p => (p.tournaments || []).forEach(t => {{
            tCounts[t] = (tCounts[t] || 0) + 1;
        }}));
        const panel = document.getElementById('tournament-filter-panel');
        if (!panel.dataset.populated) {{
            panel.innerHTML = Object.entries(tCounts).sort()
                .map(([t, n]) =>
                    `<label><input type="checkbox" class="tf-check" value="${{escapeHtml(t)}}" /> ${{escapeHtml(t)}} (${{n}})</label>`
                ).join('');
            panel.querySelectorAll('.tf-check').forEach(cb => cb.addEventListener('change', render));
            panel.dataset.populated = '1';
        }}
    }} else {{
        document.getElementById('stat-date').textContent = snap.date;
        document.getElementById('stat-games').textContent = snap.total_games.toLocaleString();
        document.getElementById('stat-rated').textContent = snap.total_rated.toLocaleString();
        document.getElementById('stat-active').textContent = snap.total_active.toLocaleString();
        document.querySelector('.stats .stat:nth-child(2) .label').textContent = 'Total games';
        document.querySelector('.stats .stat:nth-child(3) .label').textContent = 'Rated players';
    }}

    // Continent and country filter — country list reflects current continent
    const cof = document.getElementById('continent-filter');
    const cf = document.getElementById('country-filter');
    const continentSel = cof.value;
    const currentCountrySel = cf.value;

    // Refresh continent dropdown once (idempotent)
    if (!cof.dataset.populated) {{
        const allConts = {{}};
        snap.players.forEach(p => {{
            const k = CONTINENT[p.c];
            if (k) allConts[k] = (allConts[k] || 0) + 1;
        }});
        Object.entries(allConts).sort((a, b) => b[1] - a[1]).forEach(([k, n]) => {{
            const opt = document.createElement('option');
            opt.value = k; opt.textContent = `${{CONTINENT_NAMES[k]}} (${{n}})`;
            cof.appendChild(opt);
        }});
        cof.dataset.populated = '1';
    }}

    // Country dropdown filtered by selected continent
    const counts = {{}};
    snap.players.forEach(p => {{
        if (continentSel && CONTINENT[p.c] !== continentSel) return;
        counts[p.c] = (counts[p.c] || 0) + 1;
    }});
    cf.innerHTML = '<option value="">All countries</option>';
    Object.entries(counts).sort((a, b) => b[1] - a[1]).forEach(([c, n]) => {{
        const opt = document.createElement('option');
        opt.value = c; opt.textContent = `${{c}} (${{n}})`;
        cf.appendChild(opt);
    }});
    cf.value = (continentSel && CONTINENT[currentCountrySel] !== continentSel) ? '' : currentCountrySel;

    const prevLookup = buildPrevLookup();

    // Sort
    const players = snap.players.slice();
    players.forEach((p, i) => p._origRank = i + 1);
    players.sort((a, b) => {{
        let va, vb;
        if (sortCol === 'name') {{
            va = (a.fn + ' ' + a.sn).toLowerCase();
            vb = (b.fn + ' ' + b.sn).toLowerCase();
            return sortDesc ? vb.localeCompare(va) : va.localeCompare(vb);
        }}
        if (sortCol === 'country') {{
            return sortDesc ? b.c.localeCompare(a.c) : a.c.localeCompare(b.c);
        }}
        if (sortCol === 'last') {{
            return sortDesc ? b.l.localeCompare(a.l) : a.l.localeCompare(b.l);
        }}
        if (sortCol === 'rating') {{ va = a.r; vb = b.r; }}
        else if (sortCol === 'games') {{ va = a.g; vb = b.g; }}
        else if (sortCol === 'rank') {{ va = a._origRank; vb = b._origRank; }}
        else if (sortCol === 'drating') {{
            const pa = prevLookup && prevLookup[a.id]; const pb = prevLookup && prevLookup[b.id];
            va = pa ? a.r - pa.r : (prevLookup ? Infinity : 0);
            vb = pb ? b.r - pb.r : (prevLookup ? Infinity : 0);
        }} else if (sortCol === 'drank') {{
            const pa = prevLookup && prevLookup[a.id]; const pb = prevLookup && prevLookup[b.id];
            va = pa ? pa.rank - a._origRank : (prevLookup ? Infinity : 0);
            vb = pb ? pb.rank - b._origRank : (prevLookup ? Infinity : 0);
        }}
        return sortDesc ? (vb - va) : (va - vb);
    }});

    document.querySelectorAll('#ratings-table th').forEach(th => {{
        th.classList.toggle('sorted', th.dataset.col === sortCol);
    }});

    // Render rows
    const q = document.getElementById('search').value.toLowerCase();
    const country = cf.value;
    const hideProv = document.getElementById('hide-prov').checked;
    const onlyActive = document.getElementById('only-active').checked;
    const onlyActiveWeek = document.getElementById('only-active-week').checked;
    // For 'Active now': any player whose last_played is within 3 days of the
    // snapshot reference date. For LIVE snapshots snap.date is the literal
    // string 'LIVE', so we use snap.ref_date when available.
    let weekCutoff = null;
    if (onlyActiveWeek) {{
        const refDate = (snap.ref_date && snap.ref_date.length >= 10)
            ? snap.ref_date.slice(0, 10)
            : (snap.date && /^\d{{4}}-\d{{2}}-\d{{2}}/.test(snap.date) ? snap.date : null);
        if (refDate) {{
            const d = new Date(refDate + 'T00:00:00Z');
            d.setUTCDate(d.getUTCDate() - 3);
            weekCutoff = d.toISOString().slice(0, 10);
        }}
    }}
    // Tournament filter: collect checked tournament shortnames (only in LIVE)
    const tFilter = snap.live
        ? Array.from(document.querySelectorAll('.tf-check:checked')).map(c => c.value)
        : [];
    // Update button label
    const tBtn = document.getElementById('tournament-filter-btn');
    if (snap.live) {{
        tBtn.textContent = `Tournaments: ${{tFilter.length === 0 ? 'All' : tFilter.join(', ')}}`;
    }}
    const continentVal = cof.value;

    const rows = [];
    let visible = 0;
    players.forEach(p => {{
        const fullName = p.fn + ' ' + p.sn;
        if (q && !fullName.toLowerCase().includes(q)) return;
        if (continentVal && CONTINENT[p.c] !== continentVal) return;
        if (country && p.c !== country) return;
        if (hideProv && p.pr) return;
        // Participants of a currently-tracked live tournament are 'active'
        // by definition — even before their first game result lands (their
        // last_played / log only update once a game finishes).
        const isLiveParticipant = !!(p.tournaments && p.tournaments.length);
        if (onlyActive && !isLiveParticipant) {{
            // 'Active this month' = the player has at least one game in the
            // current snapshot's log (monthly) or tournament log (yearly).
            const hasLog = (p.log && p.log.length) || (p.tl && p.tl.length);
            if (!hasLog) return;
        }}
        if (onlyActiveWeek && !isLiveParticipant) {{
            // 'Active now' = last_played within 3 days of snap.ref_date/date
            if (!p.l || !weekCutoff || p.l < weekCutoff) return;
        }}
        if (tFilter.length > 0) {{
            const playerTs = p.tournaments || [];
            if (!playerTs.some(t => tFilter.includes(t))) return;
        }}
        visible++;
        const prov = p.pr ? '<span class="prov">prov</span>' : '';
        const diff = diffCells(p.id, p.r, p._origRank, prevLookup, p.log, p.tl);
        const tBadges = (p.tournaments || []).map(t => `<span class="t-badge">${{escapeHtml(t)}}</span>`).join('');
        rows.push(
            `<tr><td>${{visible}}</td>` +
            `<td class="rating">${{p.r.toFixed(0)}}</td>` +
            diff +
            `<td>${{flag(p.c)}} <span class="cc">${{p.c}}</span></td>` +
            `<td class="name-cell">${{fullName}} ${{prov}}${{buildChart(p.id, fullName)}}</td>` +
            `<td class="t-col">${{tBadges}}</td>` +
            `<td class="num">${{p.g}}</td>` +
            `<td class="num">${{p.l}}</td></tr>`
        );
    }});
    document.getElementById('tbody').innerHTML = rows.join('');
    document.getElementById('visible-count').textContent = visible.toLocaleString() + ' visible';
}}

document.querySelectorAll('#ratings-table th[data-col]').forEach(th => {{
    th.addEventListener('click', () => {{
        if (sortCol === th.dataset.col) sortDesc = !sortDesc;
        else {{
            sortCol = th.dataset.col;
            sortDesc = !(sortCol === 'name' || sortCol === 'country' || sortCol === 'rank');
        }}
        render();
    }});
}});
document.getElementById('search').addEventListener('input', render);
document.getElementById('country-filter').addEventListener('change', render);
document.getElementById('continent-filter').addEventListener('change', render);
document.getElementById('hide-prov').addEventListener('change', render);
document.getElementById('only-active').addEventListener('change', render);
document.getElementById('only-active-week').addEventListener('change', render);
// Auto-flip tooltips upward when the row sits near the bottom of the viewport.
// Re-evaluate on each mouseenter. Uses a conservative worst-case popup height
// (320px) so a row near the bottom flips up reliably even if the live measurement
// would happen to under-report the popup height for short-list tooltips.
document.addEventListener('mouseover', (e) => {{
    const cell = e.target.closest && e.target.closest('.diff-cell, .name-cell');
    if (!cell) return;
    const popup = cell.querySelector('.tip, .chart');
    if (!popup) return;
    const cellRect = cell.getBoundingClientRect();
    popup.classList.remove('flip-up');
    // Use the larger of: 320px safety margin OR actual measured height.
    const prev = {{ display: popup.style.display, visibility: popup.style.visibility }};
    popup.style.visibility = 'hidden';
    popup.style.display = 'block';
    const measured = popup.offsetHeight;
    popup.style.display = prev.display;
    popup.style.visibility = prev.visibility;
    const popupHeight = Math.max(measured, 320);
    const viewportH = window.innerHeight;
    const fitsBelow = (cellRect.bottom + popupHeight + 8) <= viewportH;
    const roomAbove = cellRect.top >= popupHeight + 8;
    if (!fitsBelow && roomAbove) {{
        popup.classList.add('flip-up');
    }}
}}, true);

// Tournament filter dropdown toggle
const tBtn = document.getElementById('tournament-filter-btn');
const tPanel = document.getElementById('tournament-filter-panel');
tBtn.addEventListener('click', (e) => {{
    e.stopPropagation();
    tPanel.classList.toggle('open');
}});
document.addEventListener('click', (e) => {{
    if (!tPanel.contains(e.target) && e.target !== tBtn) tPanel.classList.remove('open');
}});

// Persist filter state across page reloads (the site republishes every few
// minutes during live events — a reload must not clear the user's filters).
const PERSISTED_FILTERS = ['search', 'continent-filter', 'country-filter',
                           'hide-prov', 'only-active', 'only-active-week'];
function saveFilters() {{
    try {{
        const st = {{}};
        PERSISTED_FILTERS.forEach(id => {{
            const el = document.getElementById(id);
            if (!el) return;
            st[id] = (el.type === 'checkbox') ? el.checked : el.value;
        }});
        localStorage.setItem('wor-filters', JSON.stringify(st));
    }} catch (e) {{ /* private browsing etc. */ }}
}}
function restoreFilters() {{
    try {{
        const st = JSON.parse(localStorage.getItem('wor-filters') || '{{}}');
        PERSISTED_FILTERS.forEach(id => {{
            if (!(id in st)) return;
            const el = document.getElementById(id);
            if (!el) return;
            if (el.type === 'checkbox') el.checked = !!st[id];
            else el.value = st[id];
        }});
    }} catch (e) {{}}
}}
PERSISTED_FILTERS.forEach(id => {{
    const el = document.getElementById(id);
    if (el) el.addEventListener(el.type === 'checkbox' || el.tagName === 'SELECT' ? 'change' : 'input', saveFilters);
}});
restoreFilters();
render();
// Second pass for the selects: their <option>s only exist after the first
// render, so re-apply persisted values now (continent first — the country
// dropdown's contents depend on it — then country, re-rendering as needed).
try {{
    const st = JSON.parse(localStorage.getItem('wor-filters') || '{{}}');
    const cofEl = document.getElementById('continent-filter');
    if (st['continent-filter'] && cofEl.value !== st['continent-filter']) {{
        cofEl.value = st['continent-filter'];
        if (cofEl.value === st['continent-filter']) render();
    }}
    const cfEl = document.getElementById('country-filter');
    if (st['country-filter'] && cfEl.value !== st['country-filter']) {{
        cfEl.value = st['country-filter'];
        if (cfEl.value === st['country-filter']) render();
    }}
}} catch (e) {{}}
</script>
</div>
</body>
</html>
"""

out_path = os.path.join(BASE, 'world_fide_shift1800.html')
# Also publish to pages/index.html (worldothellorating = main site, shift-1800 scale)
pages_path = os.path.join(BASE, 'pages', 'index.html')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)
if os.path.isdir(os.path.dirname(pages_path)):
    with open(pages_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'Generated {out_path} and {pages_path}  ({len(snapshots)} snapshots, {len(html)/1024:.0f} KB)')
else:
    print(f'Generated {out_path}  ({len(snapshots)} snapshots, {len(html)/1024:.0f} KB)')
