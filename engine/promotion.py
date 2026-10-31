"""Conservative, opt-in deployment gate for an independently tested candidate.

The offline GM move-imitation metric is insufficient: a candidate is approved
only if it is also meaningfully superior in independent, identical-configuration
Stockfish matches with at least 100 completed games per variant.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .search import LEARNABLE_FEATURES


def check_strength_gate(study_report: dict, baseline: dict, candidate: dict,
                        *, minimum_games: int = 100) -> dict:
    reason = []
    if not study_report.get('offline_validation_gate', {}).get('passes'):
        reason.append('GM-position validation did not improve enough')
    if minimum_games < 100:
        raise ValueError('At least 100 complete games per model are required')
    for name, data in (('baseline', baseline), ('candidate', candidate)):
        total = data.get('completed_games', 0)
        if total < minimum_games or data.get('errors', 0) or data.get('incomplete', 0):
            reason.append(f'{name} must have >= {minimum_games} completed and zero errors/incomplete')
        if data.get('wins', 0) + data.get('draws', 0) + data.get('losses', 0) != total:
            reason.append(f'{name} has inconsistent game totals')
    bc, cc = baseline.get('config', {}), candidate.get('config', {})
    for k in ('stockfish_skill', 'seconds_per_move', 'own_book', 'max_plies'):
        if bc.get(k) != cc.get(k):
            reason.append(f'Mismatched benchmark control: {k}')
    if baseline.get('opponent') != candidate.get('opponent'):
        reason.append('Opponent changed between benchmarks')
    def scored(data):
        n = data.get('completed_games', 0)
        if not n:
            return 0.0, float('inf')
        wins, draws, losses = (data.get(x, 0) for x in ('wins', 'draws', 'losses'))
        p = (wins + 0.5 * draws) / n
        variance = (wins * (1-p)**2 + draws*(.5-p)**2 + losses*p**2)/n
        return p, variance/n
    p0, v0 = scored(baseline)
    p1, v1 = scored(candidate)
    difference = p1 - p0
    # Conservative unpaired 99% normal margin; cannot replace a properly
    # designed repeated opening-pair experiment, which should be preferred.
    margin = 2.576 * math.sqrt(v0 + v1)
    if difference <= max(.03, margin):
        reason.append('Insufficient demonstrated score improvement at 99% conservative margin')
    return {'promote': not reason, 'reasons': reason,
            'baseline_score_pct': round(p0*100, 2),
            'candidate_score_pct': round(p1*100, 2),
            'difference_percentage_points': round(difference*100, 2),
            'uncertainty_margin_percentage_points': round(margin*100, 2),
            'minimum_games_per_variant': minimum_games}


def write_approved(candidate_path: Path, report_path: Path, baseline_path: Path,
                   candidate_benchmark_path: Path, approved_path: Path) -> dict:
    state = json.loads(candidate_path.read_text(encoding='utf-8'))
    report = json.loads(report_path.read_text(encoding='utf-8'))
    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    candidate = json.loads(candidate_benchmark_path.read_text(encoding='utf-8'))
    outcome = check_strength_gate(report, baseline, candidate)
    if not outcome['promote']:
        raise ValueError('Candidate rejected: ' + '; '.join(outcome['reasons']))
    if state.get('schema') != 1 or set(state.get('weights', {})) != set(LEARNABLE_FEATURES):
        raise ValueError('Candidate has invalid model schema/features')
    if any(not math.isfinite(float(w)) or not (.7 <= float(w) <= 1.3)
           for w in state['weights'].values()):
        raise ValueError('Candidate has invalid evaluation multipliers')
    if approved_path.exists():
        raise FileExistsError('Will not overwrite an existing approved model without an explicit version step')
    approved_path.parent.mkdir(parents=True, exist_ok=True)
    approved_path.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    return outcome
