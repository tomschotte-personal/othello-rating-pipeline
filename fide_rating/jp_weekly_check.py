"""Weekly check for new Japanese (JOA) tournament results.

Scans the first listing pages of othello.gr.jp/competition_result, compares
them against the article ids already handled (.jp_seen.json at repo root),
and for every NEW rated article fetches and test-parses it. The result is a
markdown report (jp_weekly_report.md) that the workflow turns into a GitHub
issue; nothing is converted or rated here.

Why detection only: mapping kanji names to WOF ids needs Lazard's roster,
which must not be published in this public repo, and romanizing new players'
names (ambiguous readings, variant kanji, same-person merges) needs judgment.
The conversion itself is done in a session with Japan/convert_2026_real_ids.py
using the TARGETS lines this report proposes.

Usage: python jp_weekly_check.py [--pages N] [--seed]
  --seed  mark everything currently listed as handled (first run only).
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, BASE)
from parse_otg_tournament import parse_tournament  # noqa: E402 (rewraps stdout)

SEEN_PATH = os.path.join(ROOT, '.jp_seen.json')
REPORT_PATH = os.path.join(ROOT, 'jp_weekly_report.md')
LISTING = 'https://www.othello.gr.jp/competition_result/'
NON_RATED_MARKERS = ('レーティング非参入', 'レーティング対象外', 'レート不算入')
CARD_RE = re.compile(
    r'href="https://www\.othello\.gr\.jp/competition_result/(\d+)".*?'
    r'開催日：(\d{4})年(\d{2})月(\d{2})日\(.\)\s*(?:<[^>]+>\s*)*([^<]+)', re.S)


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    return urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'replace')


def listing(pages):
    out = {}
    for pn in range(1, pages + 1):
        html = get(LISTING + (f'page/{pn}' if pn > 1 else ''))
        for aid, y, mo, d, title in CARD_RE.findall(html):
            out.setdefault(int(aid), (f'{y}-{mo}-{d}', title.strip()))
    return out


def fetch_text(aid):
    # The parser expects rendered page text (crosstable column layout).
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page()
        page.goto(f'{LISTING}{aid}', wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(3000)
        text = page.inner_text('body')
        b.close()
    return text


def check(aid):
    """Test-parse an article; return (summary dict, list of warnings)."""
    warn = []
    try:
        text = fetch_text(aid)
    except Exception as e:
        return None, [f'fetch failed: {str(e)[:80]}']
    marker = next((m for m in NON_RATED_MARKERS if m in text), None)
    if marker:
        return {'nonrated': marker}, []
    try:
        _date, entries, amap, games = parse_tournament(text)
    except Exception as e:
        return None, [f'parse failed: {str(e)[:80]} - may need a section split or is a pair/team format']
    if not games:
        return None, ['no games parsed - pair/team format, or a layout the parser does not know']
    names = set(amap.values())
    unresolved = sorted({g[2] for g in games if g[2] not in names})
    if unresolved:
        warn.append(f'{len(unresolved)} opponent token(s) not resolved to a player: '
                    + ', '.join(unresolved[:8]))
    latin = sorted(n for n in names if re.search(r'[A-Za-z]', n))
    if latin:
        warn.append('latin-script names (foreign visitor? map to existing WOF id): '
                    + ', '.join(latin))
    per = {}
    for g in games:
        per[g[1]] = per.get(g[1], 0) + 1
    lone = sorted(n for n, k in per.items() if k == 1)
    if lone:
        warn.append('players with a single game (check for parse artifacts): '
                    + ', '.join(lone[:8]))
    return {'players': len(names), 'games': len(games) // 2 or len(games)}, warn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pages', type=int, default=4)
    ap.add_argument('--seed', action='store_true')
    args = ap.parse_args()

    try:
        seen = json.load(open(SEEN_PATH, encoding='utf-8'))
    except (OSError, ValueError):
        seen = {}
    items = listing(args.pages)
    new = {aid: v for aid, v in items.items() if str(aid) not in seen}

    if args.seed:
        for aid, (date, title) in items.items():
            seen.setdefault(str(aid), {'date': date, 'title': title, 'status': 'seed'})
        json.dump(seen, open(SEEN_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'seeded {len(items)} listing entries')
        return

    rated, skipped = [], []
    for aid in sorted(new, key=lambda a: (new[a][0], a)):
        date, title = new[aid]
        marker = next((m for m in NON_RATED_MARKERS if m in title), None)
        if marker:
            skipped.append((aid, date, title, marker))
            seen[str(aid)] = {'date': date, 'title': title, 'status': 'nonrated'}
            continue
        summary, warn = check(aid)
        if summary and summary.get('nonrated'):
            skipped.append((aid, date, title, summary['nonrated']))
            seen[str(aid)] = {'date': date, 'title': title, 'status': 'nonrated'}
            continue
        rated.append((aid, date, title, summary, warn))
        seen[str(aid)] = {'date': date, 'title': title, 'status': 'reported'}

    lines = []
    if rated:
        lines.append(f'## {len(rated)} new rated JOA article(s)\n')
        lines.append('| Article | Date | Title | Players | Games |')
        lines.append('|---|---|---|---|---|')
        for aid, date, title, s, _w in rated:
            pl = s['players'] if s else '?'
            gm = s['games'] if s else '?'
            lines.append(f'| [{aid}]({LISTING}{aid}) | {date} | {title} | {pl} | {gm} |')
        warns = [(aid, w) for aid, _d, _t, _s, ws in rated for w in ws]
        if warns:
            lines.append('\n### Needs a look before converting\n')
            for aid, w in warns:
                lines.append(f'- **{aid}**: {w}')
        lines.append('\n### TARGETS lines for `Japan/convert_2026_real_ids.py`\n')
        lines.append('Fill in the tournament name (pattern: `<edition>_<Place>_open`):\n')
        lines.append('```python')
        for aid, date, title, _s, _w in rated:
            lines.append(f"    ({aid}, '{date}', 'TODO'),  # {title}")
        lines.append('```')
        lines.append('\nThen convert, romanize the new players and validate in a session.')
    if skipped:
        lines.append(f'\n<details><summary>{len(skipped)} non-rated article(s) skipped</summary>\n')
        for aid, date, title, m in skipped:
            lines.append(f'- {aid} {date} {title} ({m})')
        lines.append('\n</details>')

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n' if lines else '')
    json.dump(seen, open(SEEN_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'RATED {len(rated)} SKIPPED {len(skipped)}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
