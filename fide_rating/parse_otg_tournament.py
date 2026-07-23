"""Parse an othello.gr.jp tournament article into a WOF-style CSV
(date, round, player1, player2, result, disc_diff).

Input: article URL (e.g., https://www.othello.gr.jp/competition_result/55048)
Output: CSV file in the same format the Japanese federation sends to WOF.

The article structure (round-robin example):
   N. 滝沢 雅樹 滝雅  ○+61 ×-10 ○+30 ○+50 ○+50 ○+ 6  5勝 1敗 0分 ...
      新潟      八段  藍原  神田  梅沢  松沢  本田  田井          +187
Where:
  - "滝沢 雅樹" = full name, "滝雅" = abbreviation, "八段" = rank
  - ○+61 = win by 61, ×-10 = loss by 10, △+0 = draw
  - The line below lists opponent abbreviations in round order
"""
import re, sys, io, argparse, csv
from datetime import datetime
from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Result tokens: win/loss/draw glyph followed by ±NN or a plain disc count.
# CRITICAL: articles use BOTH ○ (U+25CB) and 〇 (U+3007) for wins — visually
# identical, different codepoints. Some use ✕ or ● for losses.
WIN_CHARS = set('○〇◯')
LOSS_CHARS = set('×✕●')
DRAW_CHARS = set('△')
GAME_RE = re.compile(r'([○〇◯×✕●△])\s*([+-]?\s*\d+)')

# A plausible opponent abbreviation contains Japanese (or latin, for foreign
# players) and is not a bare number/score/total. Prevents rating columns like
# "270/162" or "+187" from being parsed as player names.
_JPLAT = re.compile(r'[一-鿿ぁ-ヿーA-Za-z]')
def plausible_abbr(t):
    if t == '不戦':
        return True
    if re.fullmatch(r'[+\-±\d/.,]+', t):
        return False
    if re.fullmatch(r'\d+石', t):        # disc-count totals like "188石"
        return False
    return bool(_JPLAT.search(t))


def fetch_article_text(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(800)
        text = page.inner_text('body')
        browser.close()
    return text


def parse_tournament(text):
    """Yield rounds for an article. Returns (date, players, abbr_to_full, games)
    where games is a list of (round, p1_full, p2_full, result_int, disc_diff_int).
    """
    # Find date: "2005/06/12" or "2005年06月12日"
    date_iso = None
    m = re.search(r'(\d{4})[年/](\d{1,2})[月/](\d{1,2})', text)
    if m:
        date_iso = f'{int(m.group(1)):04d}/{int(m.group(2)):02d}/{int(m.group(3)):02d}'

    lines = [l.rstrip() for l in text.splitlines()]

    # A standings entry occupies 2 lines:
    #   "  1. NAME ABBR  ○+61 ×-10 ...  W勝 L敗 D分 ..."
    #   "     REGION  RANK  opp_abbr opp_abbr opp_abbr ..."
    # Player line regex
    PLAYER_LINE_RE = re.compile(r'^\s*(\d+)\.\s*(\S+(?:\s+\S+)*?)\s+(\S+?)\s+((?:[○〇◯×✕●△]\s*[+-]?\s*\d+\s*)+)')

    entries = []  # list of (rank_int, full_name, abbr, scores_list, opp_abbrs_list)
    i = 0
    while i < len(lines):
        line = lines[i]
        m = PLAYER_LINE_RE.match(line)
        if not m:
            i += 1; continue
        rank = int(m.group(1))
        full_name = m.group(2).strip()
        abbr = m.group(3).strip()
        scores_text = m.group(4)
        # Parse score tokens
        scores = [(ch, int(d.replace(' ', ''))) for ch, d in GAME_RE.findall(scores_text)]
        # Next non-empty line should be the opponent abbreviations line
        j = i + 1
        opp_abbrs = []
        while j < len(lines):
            nx = lines[j].strip()
            if not nx: j += 1; continue
            # Opponent line: optional region + optional rank + space-separated abbrs
            # Heuristic: split by whitespace, drop the first 1-2 tokens (region/rank), rest are opp abbreviations
            tokens = nx.split()
            # Drop trailing total like "+187" if present
            while tokens and re.match(r'^[+\-±][\s]*\d+$', tokens[-1]):
                tokens.pop()
            # Keep only plausible abbreviations (drops rating/score columns
            # like "270/162"), then take the LAST N where N == len(scores) —
            # leading region/rank tokens fall away as before.
            cand = [t for t in tokens if plausible_abbr(t)]
            if len(cand) >= len(scores):
                opp_abbrs = cand[-len(scores):]
            elif len(tokens) >= len(scores):
                opp_abbrs = tokens[-len(scores):]
            break
        if not opp_abbrs:
            i += 1; continue
        entries.append((rank, full_name, abbr, scores, opp_abbrs))
        i = j + 1 if j else i + 1

    # Build abbr → full_name map (from this tournament's standings)
    abbr_to_full = {}
    for rank, full_name, abbr, _, _ in entries:
        abbr_to_full[abbr] = full_name

    # Convert to games: for each entry, generate (round, p1, p2, result, disc_diff)
    # Skip byes (opponent abbrev == "不戦") — those are forfeits, not real games.
    games = []
    for _, full_name, _, scores, opp_abbrs in entries:
        for r, ((ch, disc), opp_abbr) in enumerate(zip(scores, opp_abbrs), 1):
            if opp_abbr == '不戦':
                continue
            # Final guard: never emit a game against a token that cannot be a
            # player name (numeric/symbol artifacts from misaligned columns).
            if not plausible_abbr(opp_abbr):
                continue
            opp_full = abbr_to_full.get(opp_abbr, opp_abbr)
            if ch in WIN_CHARS:
                res = 1
            elif ch in LOSS_CHARS:
                res = -1
            else:
                res = 0
            games.append((r, full_name, opp_full, res, disc))

    return date_iso, entries, abbr_to_full, games


def write_csv(games, date_iso, out_path):
    with open(out_path, 'w', encoding='shift_jis', newline='') as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        for r, p1, p2, res, disc in games:
            w.writerow([date_iso, r, p1, p2, res, disc])
    print(f'Wrote {out_path}: {len(games)} game-rows')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('url')
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--cache', help='Save raw article text to this file')
    args = ap.parse_args()

    print(f'Fetching {args.url}...')
    text = fetch_article_text(args.url)
    if args.cache:
        with open(args.cache, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'  cached -> {args.cache}')

    date_iso, entries, abbr_map, games = parse_tournament(text)
    print(f'\nDate: {date_iso}')
    print(f'Players: {len(entries)}')
    for rank, fn, ab, scs, opps in entries:
        print(f'  #{rank} {fn} ({ab})  results={len(scs)}  opponents={opps}')
    print(f'\nAbbreviation map:')
    for ab, fn in abbr_map.items():
        print(f'  {ab} -> {fn}')
    print(f'\nGames: {len(games)} rows  (should be 2 * games_played, e.g., 12 players * 6 = 72)')
    if games:
        print('First 5 rows:')
        for g in games[:5]:
            print(f'  {g}')

    write_csv(games, date_iso, args.out)
