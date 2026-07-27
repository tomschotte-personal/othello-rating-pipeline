"""Anchor-shift-1800 pipeline: generates yearly snapshots (year-end 2010-2025 +
2026-05-31) with year-spanning per-player logs.
"""
import os, sys, io, time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(BASE))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import fide_rating, world_fide
fide_rating.INITIAL_RATING = 1800
world_fide.INITIAL_RATING = 1800
world_fide.PRIOR_RATING = 1800

from bel_rating import parse_joueurs
from world_fide import (
    collect_all_games_global_chrono, compute_for_date,
    pass1_seed_ratings, bootstrap_initial_ratings, get_program_ids,
)

YEARLY_DATES = [datetime(y, 12, 31) for y in range(2010, 2026)] + [datetime(2026, 7, 31)]

print(f'INITIAL_RATING={world_fide.INITIAL_RATING} PRIOR_RATING={world_fide.PRIOR_RATING}')
joueurs = parse_joueurs()
program_ids = get_program_ids(joueurs)
games = collect_all_games_global_chrono(exclude_pids=program_ids)
pass1_seed_ratings(games)
master_initial = bootstrap_initial_ratings(games)
print(f'Master bootstrap: {len(master_initial)} players')

for i, ref in enumerate(YEARLY_DATES):
    fname = f'world_fide_v2_shift1800_yearly_{ref.strftime("%Y%m%d")}.json'
    out = os.path.join(BASE, fname)
    prev = YEARLY_DATES[i-1] if i > 0 else None
    print(f'\n=== {ref.date()} -> {fname}  (log from {prev.date() if prev else "(none)"}) ===')
    compute_for_date(joueurs, games, ref, out, strict_fide=True,
                     log_from_date=prev, master_initial=master_initial)
