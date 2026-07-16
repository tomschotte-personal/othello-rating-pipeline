"""Derive 19th Ouza-sen games from the annotated Facebook standings screenshot
(page 2/3, blue dot = loss), cross-validated against LiveOthello broadcasts.

Confidence classes:
  A = cross-validated (game appears in two visible rows with complementary dots,
      or comes from Kurita/Urano's fully-determined rows, or LiveOthello)
  B = single-source (one visible row, dot-count matches the player's loss count)
Excluded: ambiguous 高橋 cells (Takahashi Akihiro 髙橋 vs Takahashi Satomi 高橋
indistinguishable at screenshot resolution), unknown abbreviations (荷方, 陽太,
康介, 鷲見, 梅沢, 奥平, 村上), and the 佐伯/山本悠太/大髙/大志-R5-6 rows where
dot placement could not be read reliably.
"""
import sys, io, os, unicodedata
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd

# abbrev -> full kanji (from the 80-player roster)
ABBR = {
    '栗田':'栗田誠矢','浦野':'浦野健人','木村':'木村航洋','長尾':'長尾広人','佐谷':'佐谷哲',
    '高梨':'高梨悠介','塚本':'塚本和磨','清水':'清水直希','久松':'久松美佑','研駿':'伊藤研駿',
    '中島':'中島哲也','原田':'原田祥多','忍':'伊藤忍','中野':'中野讓','中村':'中村倫太朗',
    '大清':'大清水崇典','清信':'清信健太','佐治':'佐治亨哉','小倉':'小倉竜太郎','中森':'中森弘樹',
    '純哉':'伊藤純哉','橋本':'橋本優太','凛駆':'土金凛駆','阿部':'阿部由羅','大志':'土金大志',
    '倉橋':'倉橋哲史','祐太':'鈴木祐太','岡田':'岡田大知','池田':'池田遼介','佐野':'佐野薫',
    '麻生':'麻生大祐','吉野':'吉野透','富田':'富田陽','冨田':'富田陽','藤松':'藤松航平',
    '小松':'小松奏晴','後藤':'後藤宏','藍原':'藍原重朗','山川':'山川高志','宮川':'宮川敬吾',
    '藤本':'藤本健太','石川':'石川輝','梅田':'梅田優和','宮崎':'宮崎裕司','宮﨑':'宮崎裕司',
    '三屋':'三屋伸明','大森':'大森敬太','結城':'結城皓征','瀧澤':'瀧澤信行','滝沢':'瀧澤信行',
    '野田':'野田侑那','常盤':'常盤柊音','松本':'松本昂大','菊池':'菊池晴天','長谷':'長谷川武',
    '松田':'松田唯吹','谷原':'谷原暖','本庄':'本庄良尭','明正':'明正悠太','小野':'小野泰河',
    '奥田':'奥田強','悠太':'山本悠太','佐伯':'佐伯翼',
    '荷方':'荷方幸博','康介':'佐々木康介','鷲見':'鷲見拳','梅沢':'梅沢佳紀',
    '奥平':'奥平晶大','村上':'村上健',
}

# (round, winner_abbr, loser_abbr, confidence)
GAMES = [
    # Kurita (champion, all wins) — class A
    (1,'栗田','久松','A'), (2,'栗田','倉橋','A'), (3,'栗田','祐太','A'),
    (4,'栗田','研駿','A'), (5,'栗田','中島','A'), (7,'栗田','浦野','A'),
    # Urano (won all Swiss) — class A
    (1,'浦野','岡田','A'), (2,'浦野','大清','A'), (3,'浦野','池田','A'),
    (4,'浦野','佐野','A'), (5,'浦野','中野','A'),
    # LiveOthello broadcasts — class A
    (5,'塚本','原田','A'), (6,'佐谷','久松','A'), (6,'長尾','中島','A'), (6,'高梨','研駿','A'),
    # 5-win rows (one dot each), cross-validated where pair visible
    (1,'木村','麻生','B'), (2,'木村','吉野','B'), (3,'木村','佐治','A'),
    (4,'原田','木村','A'), (5,'木村','富田','B'), (6,'木村','忍','A'),
    (2,'長尾','荷方','B'), (3,'長尾','藤松','B'), (4,'長尾','小松','B'), (5,'長尾','後藤','B'),
    (1,'大清','長尾','A'),
    (1,'佐谷','藍原','B'), (2,'山川','佐谷','B'), (3,'佐谷','阿部','A'), (4,'佐谷','佐治','A'), (5,'佐谷','大清','A'),
    (1,'高梨','清信','A'), (3,'高梨','後藤','B'), (4,'大志','高梨','A'), (5,'高梨','山川','B'),
    (1,'小松','塚本','B'), (2,'塚本','麻生','B'), (3,'塚本','宮川','B'), (4,'塚本','池田','B'), (6,'塚本','中村','A'),
    (1,'清水','藤本','B'), (2,'清水','石川','B'), (3,'梅田','清水','B'), (5,'清水','宮崎','B'), (6,'清水','中野','A'),
    # 4-win rows
    (2,'久松','橋本','A'), (3,'久松','大森','B'), (4,'久松','結城','B'),
    (2,'研駿','三屋','B'), (3,'研駿','小倉','A'), (5,'研駿','中森','A'),
    (1,'中島','奥田','B'), (2,'中島','純哉','A'), (3,'中島','大森','B'), (4,'中島','梅田','B'),
    (2,'原田','瀧澤','B'), (3,'原田','山川','B'), (6,'阿部','原田','A'),
    (1,'忍','野田','B'), (2,'忍','常盤','B'), (3,'中村','忍','A'), (4,'忍','純哉','A'), (5,'忍','小倉','A'),
    (1,'中野','鷲見','B'), (2,'中野','藤松','B'), (3,'中野','小松','B'), (4,'中野','後藤','B'),
    (1,'中村','宮崎','B'), (2,'中村','中森','A'), (5,'中村','藤本','B'),
    (3,'大清','藍原','B'), (4,'大清','清信','A'), (6,'大清','松本','B'),
    (2,'清信','凛駆','A'), (5,'清信','菊池','B'), (6,'清信','小松','B'),
    (1,'佐治','長谷','B'), (2,'佐治','滝沢','B'), (5,'佐治','宮川','B'), (6,'佐治','常盤','B'),
    (1,'小倉','松田','B'), (2,'小倉','陽太skip','X'), (4,'小倉','佐伯','A'), (6,'小倉','滝沢','B'),
    (1,'中森','谷原','B'), (3,'中森','松田','B'), (4,'中森','三屋','B'), (6,'中森','奥平','B'),
    (1,'純哉','梅沢','B'), (3,'純哉','康介','B'), (5,'純哉','石川','B'), (6,'冨田','純哉','B'),
    (1,'悠太','橋本','A'), (3,'橋本','本庄','B'), (4,'橋本','松田','B'), (5,'橋本','結城','B'), (6,'橋本','宮崎','B'),
    (1,'凛駆','山川','B'), (3,'凛駆','小野','B'), (4,'凛駆','岡田','B'), (5,'凛駆','池田','B'), (6,'梅田','凛駆','B'),
    (1,'藤松','阿部','B'), (2,'阿部','村上','B'), (4,'阿部','長谷','B'), (5,'阿部','瀧澤','B'),
    (1,'大志','吉野','B'), (2,'大志','菊池','B'), (3,'大志','滝沢','B'), (5,'佐野','大志','B'),
]

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
df = pd.read_excel(r'C:/Users/schotte/OneDrive - TomTom/Documents/Othello/Japan/20260608_JapanesePlayers_translated.xlsx', header=None).iloc[:, :4]
df.columns = ['kanji','wof_id','sn','fn']
VAR = {'髙':'高','澤':'沢','﨑':'崎','齋':'斎','齊':'斉','讓':'譲'}
def norm(k):
    k = unicodedata.normalize('NFC', str(k)).replace('　','').replace(' ','')
    return ''.join(VAR.get(c,c) for c in k)
kmap = {}
for _, r in df.iterrows():
    try: wid = int(r['wof_id'])
    except: continue
    if wid > 0:
        kmap.setdefault(norm(r['kanji']), (wid, str(r['sn']).upper(), str(r['fn'])))

resolved = []
skipped = []
for rnd, w_ab, l_ab, conf in GAMES:
    if conf == 'X':
        skipped.append((rnd, w_ab, l_ab)); continue
    w = kmap.get(norm(ABBR.get(w_ab, w_ab)))
    l = kmap.get(norm(ABBR.get(l_ab, l_ab)))
    if not w or not l:
        skipped.append((rnd, w_ab, l_ab)); continue
    resolved.append((rnd, w, l, conf))

print(f'Resolved games: {len(resolved)}  (A={sum(1 for g in resolved if g[3]=="A")}, B={sum(1 for g in resolved if g[3]=="B")})')
print(f'Skipped/unresolvable: {len(skipped)}')
for s in skipped: print('  skip:', s)

# Build roster with points from these games
from collections import defaultdict
pts = defaultdict(float); games_ct = defaultdict(int); info = {}
for rnd, w, l, conf in resolved:
    pts[w[0]] += 1
    games_ct[w[0]] += 1; games_ct[l[0]] += 1
    info[w[0]] = w; info[l[0]] = l

lines = [
    '%%Tournament: 19_Ouza_sen (partial, from standings sheet)',
    '%%Country: Japan',
    '%%Date: 12/07/2026',
    '%%Sender: WOF rating committee (derived from JOA standings sheet p2/3 + LiveOthello; PARTIAL - top-24 records)',
    '',
    '%        id, lastname, firstname, country, score, disc-count',
    '',
]
for pid in sorted(info, key=lambda p: -pts[p]):
    w = info[pid]
    lines.append(f'%_% {pid:>6}, {w[1]}, {w[2]}, JPN, {pts[pid]:.1f}, 0')
lines.append('')
by_round = defaultdict(list)
for rnd, w, l, conf in resolved:
    by_round[rnd].append((w[0], l[0]))
for rnd in sorted(by_round):
    lines.append(f'%Round: {rnd}')
    lines.append('')
    for w, l in by_round[rnd]:
        lines.append(f' {w:>6} (33)>(31) {l:>6}  B')
    lines.append('')
out = os.path.join(ROOT, 'wof_results', '2026', '20260712_19_Ouza_sen.ELO')
open(out, 'w', encoding='utf-8').write('\n'.join(lines))
print(f'Wrote {out}: {len(info)} players, {len(resolved)} games')
