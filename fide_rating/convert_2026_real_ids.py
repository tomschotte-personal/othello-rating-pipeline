"""Re-convert all 2026 othello.gr.jp tournaments with the fixed parser and
assign REAL WOF ids from the block Lazard allocated (170121+) to players not
in the canonical roster. Overwrites the existing .ELO files in wof_results/2026.

The 19th Ouza-sen is NOT touched (it comes from the official JOA crosstable).

Outputs:
  wof_results/2026/<same filenames>.ELO      (regenerated, artifact-free)
  OneDrive .../Japan/20260722_NewPlayers2026.xlsx   (id registry, translated)
"""
import os, sys, io, re
from collections import defaultdict, Counter
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_otg_tournament import fetch_article_text, parse_tournament, plausible_abbr
sys.stdout.reconfigure(encoding='utf-8')

OUT_DIR = 'C:/Claude/o_dan/wof_results/2026'
REF = 'C:/Users/schotte/OneDrive - TomTom/Documents/Othello/Japan/20260608_JapanesePlayers_translated.xlsx'
XLSX_OUT = 'C:/Users/schotte/OneDrive - TomTom/Documents/Othello/Japan/20260722_NewPlayers2026.xlsx'
ID_START = 17121    # WOF block for 2026 newcomers (Lazard: 17000-17120 = backfill, 17121+ = 2026)

TARGETS = [
    (67928, '2026-05-23', '27_Fukuroi_open'),
    (67932, '2026-05-23', '179_Shinagawa_seaside_open'),
    (67935, '2026-05-24', '106_Sapporo_open'),
    (67939, '2026-05-24', '145_Sendai_open'),
    (68028, '2026-05-31', '99_Tatebayashi_open'),
    (68196, '2026-06-07', '16_Mito_open'),
    (68202, '2026-06-07', '15_Kanagawa_cup'),
    (68252, '2026-06-13', '241_Nagareyama_open'),
    (68255, '2026-06-13', '16_Fukushima_challenge_cup'),
    (68323, '2026-06-13', '180_Shinagawa_seaside_open'),
    (68283, '2026-06-14', '146_Sendai_open'),
    (68303, '2026-06-14', '50_Higashi_Hiroshima_open'),
    (68391, '2026-06-21', '2026_Niigata_houou'),
    (68462, '2026-06-28', '107_Sapporo_open'),
    (68467, '2026-06-28', '2026_Kyoto_king'),
    (68543, '2026-06-28', '6_Shinagawa_first_step'),
    (68553, '2026-06-28', '297_Kawagoe_ranking_games'),
    (68571, '2026-07-05', '134_Kanagawa_open'),
    (68573, '2026-07-05', '134_Kanagawa_open_general'),
    # 19 Apr - 17 May gap (official JOA->WOF delivery stopped 2026-04-12)
    (66843, '2026-04-19', '144_Sendai_open'),
    (66853, '2026-04-19', '67_Nagoya_open'),
    (66860, '2026-04-19', '67_Nagoya_open_kyu'),
    (66871, '2026-04-19', '239_Nagareyama_open'),
    (67152, '2026-04-25', '135_Nagareyama_B'),
    (67163, '2026-04-25', '7_Osaka_endurance_1', ('＜第一部＞', '＜第二部＞')),
    (67163, '2026-04-25', '7_Osaka_endurance_2', ('＜第二部＞', None)),
    (67182, '2026-04-25', '32_Shinagawa_super_league'),
    (67189, '2026-04-26', '105_Sapporo_open'),
    (67201, '2026-04-26', '2026_Master_open'),
    (67204, '2026-04-26', '296_Kawagoe_ranking_games'),
    (67366, '2026-04-29', '3_Koyama_open'),
    (67494, '2026-05-03', '17_Hyogo_Toryumon'),
    (67497, '2026-05-03', '17_Hyogo_super_league'),
    (67516, '2026-05-03', '126_Q_league'),
    (67525, '2026-05-04', '7_Iwata_endurance_morning', ('午前の部', '午後の部')),
    (67525, '2026-05-04', '7_Iwata_endurance_afternoon', ('午後の部', None)),
    (67533, '2026-05-04', '1_Kyoto_Kiyomizu_challenge_cup'),
    (67536, '2026-05-04', '36_Kyoto_open'),
    (67551, '2026-05-05', '240_Nagareyama_open'),
    (67565, '2026-05-05', '11_Shinagawa_trio', ('【１番手成績】', None)),
    (67731, '2026-05-06', '16_Tokyo_open'),
    (67663, '2026-05-09', '60_Niigata_challenge_cup'),
    (67700, '2026-05-10', '49_Higashi_Hiroshima_open'),
    (67813, '2026-05-17', '136_Nagareyama_B'),
    (67827, '2026-05-17', '2026_Kawagoe_kisei', ('棋聖戦（', '女王戦（')),
    (67827, '2026-05-17', '2026_Kawagoe_joou', ('女王戦（', '予選（')),
    (67827, '2026-05-17', '2026_Kawagoe_kisei_prelim', ('予選（', None)),
    # 18-20 July weekend. Article 68820 carries TWO sections: the open and the
    # 1st Tokai Junior (which doubles as Fukuroi Open B-class) - split them.
    (68820, '2026-07-18', '28_Fukuroi_open', (None, '第１回東海ジュニアオセロ大会（兼ふくろいオープンＢ級）')),
    (68820, '2026-07-18', '1_Tokai_junior_Fukuroi_B', ('第１回東海ジュニアオセロ大会（兼ふくろいオープンＢ級）', None)),
    (68848, '2026-07-18', '181_Shinagawa_seaside_open'),
    (68868, '2026-07-19', '147_Sendai_open'),
    (68874, '2026-07-19', '51_Higashi_Hiroshima_open'),
    (68893, '2026-07-19', '8_Toyama_open'),
    (68900, '2026-07-19', '8_Toyama_open_B'),
    (68902, '2026-07-19', '2_Nagareyama_Kawagoe_team'),
    (68930, '2026-07-20', '137_Nagareyama_B'),
    (68934, '2026-07-20', '100_Tatebayashi_open'),
]

# === canonical kanji -> WOF map (same conventions as add_recent_otg) ===
df = pd.read_excel(REF, header=None).iloc[:, :4]
df.columns = ['kanji', 'wof_id', 'sn', 'fn']
kanji_map = {}
sur_map = defaultdict(Counter)
giv_map = defaultdict(Counter)
for _, row in df.iterrows():
    k = str(row['kanji']).strip()
    sn = str(row['sn']).strip()
    fnm = str(row['fn']).strip()
    if not k or sn.lower() in ('nan', 'name', ''):
        continue
    try:
        wid = int(row['wof_id'])
    except (ValueError, TypeError):
        continue
    if wid > 0:
        kanji_map.setdefault(k, (wid, sn.upper(), fnm.lower()))
    parts = re.split(r'[\s　]+', k)
    if len(parts) == 2 and fnm.lower() != 'nan':
        sur_map[parts[0]][sn.upper()] += 1
        giv_map[parts[1]][fnm.lower()] += 1
kanji_map['洪家威'] = (420062, 'HUNG', 'jia wei')
kanji_map['何秋'] = (60247, 'HO', 'yin chau')
kanji_map['ローズ ブライアン'] = (177, 'ROSE', 'brian')
kanji_map['アンソニー'] = (250005, 'GOH', 'jun jie anthony')
# Same-person variants found via romanization collision check (2026-07-23):
kanji_map['井上 航汰'] = (16506, 'INOUE', 'kota')      # roster spells 井上航太
kanji_map['鹿島 虹花'] = (16061, 'KASHIMA', 'nijika')  # roster spells 鹿嶋虹花
kanji_map['ゴー アンソニー'] = (250005, 'GOH', 'jun jie anthony')  # katakana full form
kanji_map['Anthony'] = (250005, 'GOH', 'jun jie anthony')          # bare form (Tatebayashi)

VARIANTS = {'髙':'高','澤':'沢','邊':'辺','邉':'辺','齋':'斎','齊':'斉','﨑':'崎','條':'条','嶋':'島'}
def clean_name(s):
    s = re.sub(r'[\s　]+', ' ', s.strip())
    tokens = s.split(' ')
    if len(tokens) >= 3:
        s = ' '.join(tokens[:2])
    return s.strip()
def normalize(s):
    s = clean_name(s)
    s = ''.join(VARIANTS.get(c, c) for c in s)
    return s.replace(' ', '').strip()
norm_map = {normalize(k): v for k, v in kanji_map.items()}
def lookup(p):
    return kanji_map.get(p) or norm_map.get(normalize(p))

def guess_translation(kanji):
    parts = re.split(r'[\s　]+', kanji)
    if len(parts) != 2:
        return ('', '', 'unsplittable')
    s, g = parts
    sur = sur_map[s].most_common(1)[0][0] if sur_map.get(s) else ''
    giv = giv_map[g].most_common(1)[0][0] if giv_map.get(g) else ''
    ev = []
    ev.append(f'surname list({sum(sur_map[s].values())})' if sur else 'surname ??')
    ev.append(f'given list({sum(giv_map[g].values())})' if giv else 'given ??')
    return (sur, giv, ', '.join(ev))

NON_RATED_MARKERS = ('レーティング非参入', 'レーティング対象外', 'レート不算入')

PREFECTURES = set('北海道 青森 岩手 宮城 秋田 山形 福島 茨城 栃木 群馬 埼玉 千葉 東京 神奈川 '
                  '新潟 富山 石川 福井 山梨 長野 岐阜 静岡 愛知 三重 滋賀 京都 大阪 兵庫 奈良 '
                  '和歌山 鳥取 島根 岡山 広島 山口 徳島 香川 愛媛 高知 福岡 佐賀 長崎 熊本 '
                  '大分 宮崎 鹿児島 沖縄'.split())

def real_player(s):
    s = s.strip()
    if not s or len(s) > 30:
        return False
    if not plausible_abbr(s):
        return False
    if re.search(r'初出場|初参加|回目|不戦|前回|小学|権利|\?', s):
        return False
    if re.fullmatch(r'\d+石|[０-９0-9]+級|[一二三四五六七八九十]*段', s):
        return False
    if s in PREFECTURES:
        return False
    # concatenated-surname artifacts from misaligned columns (e.g. 長谷武斎藤):
    # a multi-char surname immediately followed by more kanji without a space
    if ' ' not in s and re.match(r'^(長谷武|長谷川|瀬々倉|伊勢田|小木曽)[一-鿿]', s):
        return False
    return bool(re.search(r'[一-鿿ぁ-ヿ]', s)) or bool(re.fullmatch(r'[A-Za-z_ ]{4,}', s))

# id registry for newcomers; ids+translations are PINNED to an existing
# registry workbook so re-runs never renumber or lose hand-corrections.
assigned = {}      # normalize(kanji) -> (wof_id, SURNAME, firstname)
reg_info = {}      # normalize -> dict for the workbook
pinned = {}
next_id = ID_START
if os.path.exists(XLSX_OUT):
    _wb = pd.read_excel(XLSX_OUT)
    for _, r in _wb.iterrows():
        sn = str(r['SURNAME']).strip(); fnm = str(r['firstname']).strip()
        pinned[normalize(str(r['kanji']))] = (
            int(r['wof_id']),
            '' if sn in ('', 'nan') else sn,
            '' if fnm in ('', 'nan') else fnm,
            str(r['kanji']).strip())
    if pinned:
        next_id = max(v[0] for v in pinned.values()) + 1
    print(f'Registry pinned: {len(pinned)} players, next id {next_id}')

def id_for_new(kanji, date_iso, tname):
    global next_id
    n = normalize(kanji)
    if n not in assigned:
        if n in pinned:
            wid, sur, giv, _ = pinned[n]
            ev = 'pinned from registry'
        else:
            sur, giv, ev = guess_translation(kanji)
            wid = next_id
            next_id += 1
        assigned[n] = (wid, sur or kanji, giv)
        reg_info[n] = {'kanji': kanji, 'wof_id': wid, 'SURNAME': sur,
                       'firstname': giv, 'evidence': ev, 'games': 0,
                       'tournaments': set(), 'first': date_iso, 'last': date_iso}
    e = reg_info[n]
    e['tournaments'].add(tname)
    e['last'] = max(e['last'], date_iso)
    return assigned[n]

# article-text cache: refetching 19 Playwright pages per run is the slow part
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_otg_cache')
os.makedirs(CACHE_DIR, exist_ok=True)
def get_article(article_id, url):
    p = os.path.join(CACHE_DIR, f'{article_id}.txt')
    if os.path.exists(p):
        return open(p, encoding='utf-8').read()
    t = fetch_article_text(url)
    if '404 error' not in t:
        with open(p, 'w', encoding='utf-8') as f:
            f.write(t)
    return t

total_games = 0
skipped = []
for entry in TARGETS:
    article_id, date_iso, tname = entry[:3]
    section = entry[3] if len(entry) > 3 else None
    url = f'https://www.othello.gr.jp/competition_result/{article_id}'
    print(f'\n=== {article_id} — {tname} ({date_iso}) ===', flush=True)
    try:
        text = get_article(article_id, url)
    except Exception as e:
        print(f'  FETCH FAILED: {e}')
        skipped.append((tname, f'fetch: {e}'))
        continue
    if section:
        s_mark, e_mark = section
        i0 = text.find(s_mark) if s_mark else 0
        i1 = text.find(e_mark) if e_mark else len(text)
        text = text[max(i0, 0):(i1 if i1 >= 0 else len(text))]
        print(f'  section slice: {len(text)} chars')
    marker = next((m for m in NON_RATED_MARKERS if m in text), None)
    if marker:
        print(f'  SKIPPED: non-rated ({marker})')
        skipped.append((tname, marker))
        continue
    try:
        _d, entries, _a, games = parse_tournament(text)
    except Exception as e:
        print(f'  PARSE FAILED: {e}')
        skipped.append((tname, f'parse: {e}'))
        continue
    if not games:
        print('  no games parsed')
        skipped.append((tname, 'no games'))
        continue

    # Disc-token semantics vary per article: "○+61" style = signed margin,
    # "〇63" style = the row player's own disc count (no negatives anywhere).
    # Normalize everything to p1's disc count before deduping.
    mode = 'margin' if any(d < 0 for _, _, _, _, d in games) else 'count'
    def to_p1d(res, d):
        # NOTE: a genuine 32-32 WIN exists in no-draw events (e.g. Ouza rules):
        # keep it as (32)>(32) — the result comes from the ○/×/△ column, never
        # from the disc counts.
        p1d = 32 + (d + (d % 2)) // 2 if mode == 'margin' else d
        return max(0, min(64, p1d))

    # dedupe double perspectives
    seen = {}
    for rnd, p1, p2, res, disc in games:
        p1, p2 = clean_name(p1), clean_name(p2)
        if not real_player(p1) or not real_player(p2):
            continue
        a, b = sorted([p1, p2])
        key = (rnd, a, b)
        if key in seen:
            continue
        p1d = to_p1d(res, disc)
        if (p1, p2) == (a, b):
            seen[key] = (p1, p2, res, p1d)
        else:
            seen[key] = (a, b, -res if res != 0 else 0, 64 - p1d)
    # Drop duplicate-perspective games: single-token unresolved "opponents"
    # (abbreviations like 藤 for an already-listed player) that collide with a
    # properly-named same-round game of the same partner.
    def _bare_unresolved(p):
        return ' ' not in p and not lookup(p)
    by_rp = defaultdict(list)
    for key, (p1, p2, res, p1d) in seen.items():
        by_rp[(key[0], p1)].append(key)
        by_rp[(key[0], p2)].append(key)
    drop = set()
    for (rnd, pl), keys in by_rp.items():
        if len(keys) < 2 or _bare_unresolved(pl):
            continue
        bare = [k for k in keys
                if any(_bare_unresolved(x) for x in (seen[k][0], seen[k][1]))]
        if bare and len(keys) - len(bare) == 1:
            drop.update(bare)
    for k in sorted(drop):
        print(f'  dedup: dropped duplicate-perspective game R{k[0]} {k[1]} vs {k[2]}')
    seen = {k: v for k, v in seen.items() if k not in drop}

    games = [(r, p1, p2, res, p1d) for (r, _, _), (p1, p2, res, p1d) in seen.items()]
    print(f'  disc mode: {mode}')

    points = defaultdict(float); disc_total = defaultdict(int)
    for rnd, p1, p2, res, p1d in games:
        if res == 1: points[p1] += 1.0
        elif res == -1: points[p2] += 1.0
        else: points[p1] += 0.5; points[p2] += 0.5
        disc_total[p1] += p1d
        disc_total[p2] += 64 - p1d

    all_players = sorted(set(p for _, p, _, _, _ in games) | set(p for _, _, p, _, _ in games))
    sorted_players = sorted(all_players, key=lambda p: (-points[p], -disc_total[p], p))

    ids = {}; names = {}
    n_new = 0
    for p in sorted_players:
        e = lookup(p)
        if e:
            ids[p], names[p] = e[0], (e[1], e[2])
        else:
            wid, sn, fnm = id_for_new(p, date_iso, tname)
            ids[p], names[p] = wid, (sn, fnm)
            reg_info[normalize(p)]['games'] += sum(1 for _, a, b, _, _ in games if p in (a, b))
            n_new += 1

    date_dmy = f'{date_iso[8:10]}/{date_iso[5:7]}/{date_iso[:4]}'
    out_path = os.path.join(OUT_DIR, f'{date_iso.replace("-","")}_{tname}.ELO')
    lines = [
        f'%%Tournament: {tname}',
        '%%Country: Japan',
        f'%%Date: {date_dmy}',
        '%%Sender: WOF rating committee (othello.gr.jp scrape; ids 17121+ = WOF block for new JP players)',
        '',
    ]
    for p in sorted_players:
        sn, fnm = names[p]
        lines.append(f'%_% {ids[p]:>6}, {sn}, {fnm}, JPN, {points[p]:.1f}, {disc_total[p]}')
    by_round = defaultdict(list)
    for rnd, p1, p2, res, p1d in games:
        p2d = 64 - p1d
        if res == 1: by_round[rnd].append((p1, p2, p1d, p2d, '>'))
        elif res == -1: by_round[rnd].append((p2, p1, p2d, p1d, '>'))
        else: by_round[rnd].append((p1, p2, p1d, p2d, '='))
    for rnd in sorted(by_round):
        lines.append('')
        lines.append(f'%Round {rnd}')
        for w, l, wd, ld, op in by_round[rnd]:
            lines.append(f' {ids[w]:>6} ({wd:02d}){op}({ld:02d})  {ids[l]:>6} ')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    total_games += len(games)
    print(f'  -> {os.path.basename(out_path)}: {len(sorted_players)}pl, {len(games)}g, {n_new} first-time-new')

print(f'\n=== DONE: {total_games} games, {len(assigned)} new players (ids {ID_START}-{next_id-1}) ===')
for tname, why in skipped:
    print(f'  SKIPPED {tname}: {why}')

rows = []
for n, e in sorted(reg_info.items(), key=lambda kv: kv[1]['wof_id']):
    rows.append({'kanji': e['kanji'], 'wof_id': e['wof_id'], 'SURNAME': e['SURNAME'],
                 'firstname': e['firstname'], 'evidence': e['evidence'],
                 'games': e['games'], 'n_tournaments': len(e['tournaments']),
                 'first_seen': e['first'], 'last_seen': e['last'],
                 'tournaments': '; '.join(sorted(e['tournaments'])[:4])})
pd.DataFrame(rows).to_excel(XLSX_OUT, index=False)
print(f'Registry: {XLSX_OUT} ({len(rows)} players)')
