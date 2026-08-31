"""Anchor-shift-1800 pipeline: generates monthly snapshots with
INITIAL_RATING=PRIOR_RATING=1800. Output files have a 'shift1800' suffix so
they don't conflict with the official pipeline.
"""
import os, sys, io, time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(BASE))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Patch BEFORE importing anything that uses these constants in module-level state
import fide_rating, world_fide
fide_rating.INITIAL_RATING = 1800
world_fide.INITIAL_RATING = 1800
world_fide.PRIOR_RATING = 1800

from bel_rating import parse_joueurs
from world_fide import (
    collect_all_games_global_chrono, compute_for_date,
    pass1_seed_ratings, bootstrap_initial_ratings, get_program_ids,
)

DATES = [
    datetime(2010, 12, 31), datetime(2011, 12, 31), datetime(2012, 12, 31),
    datetime(2013, 12, 31), datetime(2014, 12, 31), datetime(2015, 12, 31),
    datetime(2016, 12, 31), datetime(2017, 12, 31), datetime(2018, 12, 31),
    datetime(2019, 12, 31), datetime(2020, 12, 31), datetime(2021, 12, 31),
    datetime(2022, 12, 31), datetime(2023, 12, 31),
    datetime(2024, 1, 31), datetime(2024, 2, 29), datetime(2024, 3, 31),
    datetime(2024, 4, 30), datetime(2024, 5, 31), datetime(2024, 6, 30),
    datetime(2024, 7, 31), datetime(2024, 8, 31), datetime(2024, 9, 30),
    datetime(2024, 10, 31), datetime(2024, 11, 30), datetime(2024, 12, 31),
    datetime(2025, 1, 31), datetime(2025, 2, 28), datetime(2025, 3, 31),
    datetime(2025, 4, 30), datetime(2025, 5, 31), datetime(2025, 6, 30),
    datetime(2025, 7, 31), datetime(2025, 8, 31), datetime(2025, 9, 30),
    datetime(2025, 10, 31), datetime(2025, 11, 30), datetime(2025, 12, 31),
    datetime(2026, 1, 31), datetime(2026, 2, 28), datetime(2026, 3, 31),
    datetime(2026, 4, 30), datetime(2026, 5, 31), datetime(2026, 6, 30),
    datetime(2026, 7, 31), datetime(2026, 8, 31),
]

print(f'INITIAL_RATING={world_fide.INITIAL_RATING} PRIOR_RATING={world_fide.PRIOR_RATING}')
print('Loading joueurs and games once...')
joueurs = parse_joueurs()
program_ids = get_program_ids(joueurs)
t0 = time.time()
games = collect_all_games_global_chrono(exclude_pids=program_ids)
print(f'  Loaded {len(games)} games in {time.time()-t0:.1f}s')

print('Computing master bootstrap from full game history...')
pass1_seed_ratings(games)
master_initial = bootstrap_initial_ratings(games)
print(f'  Master bootstrap: {len(master_initial)} players')

for i, ref in enumerate(DATES):
    fname = f'world_fide_v2_shift1800_{ref.strftime("%Y%m%d")}.json'
    out = os.path.join(BASE, fname)
    prev = DATES[i-1] if i > 0 else None
    print(f'\n=== {ref.date()} -> {fname} ===')
    compute_for_date(joueurs, games, ref, out, strict_fide=True,
                     log_from_date=prev, master_initial=master_initial)
