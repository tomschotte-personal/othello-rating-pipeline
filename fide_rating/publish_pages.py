"""The ONLY sanctioned way to publish the rating page from this machine.

Enforces the single-writer discipline that repeated weekend incidents came
from violating by hand:
  1. REFUSES to publish while a live tracking window is armed (.ftd_auto or
     FTD_IDS present in the pipeline repo) unless --force is given — during a
     window, GitHub Actions owns pages/index.html.
  2. Always: fetch + hard-reset pages to origin/main (index.html is a derived
     artifact; there is never anything local worth merging), THEN regenerate,
     THEN commit + push. No stash, no rebase, no conflict markers. Ever.

Usage: python publish_pages.py "commit message" [--force]
"""
import os, sys, subprocess, io

BASE = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(BASE, 'pages')
PIPELINE = os.path.join(os.path.dirname(BASE), 'pipeline_repo')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def run(cmd, cwd, check=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=True)
    if check and r.returncode != 0:
        sys.exit(f'FAILED: {cmd}\n{r.stdout}\n{r.stderr}')
    return r.stdout.strip()


def live_window_armed():
    reasons = []
    run('git fetch -q origin', PIPELINE, check=False)
    auto = run('git show origin/main:.ftd_auto 2>/dev/null || true', PIPELINE, check=False)
    if auto.strip():
        reasons.append(f'.ftd_auto armed: {auto.strip()}')
    ids = run('gh variable get FTD_IDS -R tomschotte-personal/othello-rating-pipeline 2>/dev/null || true',
              PIPELINE, check=False)
    if ids.strip():
        reasons.append(f'FTD_IDS variable set: {ids.strip()}')
    return reasons


def main():
    args = [a for a in sys.argv[1:] if a != '--force']
    force = '--force' in sys.argv
    msg = args[0] if args else 'Update rating page'

    reasons = live_window_armed()
    if reasons and not force:
        print('REFUSING to publish: a live tracking window is armed and')
        print('GitHub Actions owns pages/index.html right now:')
        for r in reasons:
            print('  -', r)
        print('Re-run with --force ONLY if you know the Actions runs are dead.')
        sys.exit(2)

    print('Syncing pages to origin (hard reset, derived content only)...')
    run('git fetch origin', PAGES)
    run('git reset --hard origin/main', PAGES)

    # CI finalizes commit .ELO files ONLY into the pipeline repo. A local
    # publish regenerates index.html from LOCAL data, so without this sync it
    # silently reverts every event CI tracked since the last manual sync
    # (2026-10-04: Australian Nationals + HK Championship vanished under a
    # champions-page publish). Always pull CI results in first.
    import glob as _glob, shutil as _shutil
    print('Syncing CI results from pipeline repo...')
    run('git pull -q origin main', PIPELINE, check=False)
    synced = 0
    for yr_dir in _glob.glob(os.path.join(PIPELINE, 'wof_results', '*')):
        loc_dir = os.path.join(os.path.dirname(BASE), 'wof_results',
                               os.path.basename(yr_dir))
        if not os.path.isdir(loc_dir):
            continue
        for f in os.listdir(yr_dir):
            if f.upper().endswith('.ELO') and not os.path.exists(os.path.join(loc_dir, f)):
                _shutil.copy2(os.path.join(yr_dir, f), os.path.join(loc_dir, f))
                print('  synced from CI:', f)
                synced += 1
    if synced:
        print(f'  {synced} new file(s) - recomputing live overlay...')
        run(f'python "{os.path.join(BASE, "shift1800_live.py")}"', BASE)

    print('Regenerating page...')
    run(f'python "{os.path.join(BASE, "shift1800_html.py")}"', BASE)
    # Static extra pages kept next to this script; copied in AFTER the hard
    # reset so they survive it. Canonical source: fide_rating/champions.html
    # (regenerated from NC.xlsx by the National Champions rebuild flow).
    import shutil
    for extra in ['champions.html']:
        src = os.path.join(BASE, extra)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(PAGES, extra))
    status = run('git status --porcelain index.html champions.html', PAGES, check=False)
    if not status:
        print('No content change - nothing to publish.')
        return
    run('git add index.html', PAGES)
    if os.path.exists(os.path.join(PAGES, 'champions.html')):
        run('git add champions.html', PAGES)
    run(f'git commit -m "{msg}"', PAGES)
    run('git push origin main', PAGES)
    print('Published.')


if __name__ == '__main__':
    main()
