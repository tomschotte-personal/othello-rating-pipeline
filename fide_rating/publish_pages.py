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
    print('Regenerating page...')
    run(f'python "{os.path.join(BASE, "shift1800_html.py")}"', BASE)
    status = run('git status --porcelain index.html', PAGES, check=False)
    if not status:
        print('No content change - nothing to publish.')
        return
    run('git add index.html', PAGES)
    run(f'git commit -m "{msg}"', PAGES)
    run('git push origin main', PAGES)
    print('Published.')


if __name__ == '__main__':
    main()
