"""Promote GM-1000 candidate ONLY after independent matched-setting chess tests."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.promotion import write_approved

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--study-report', type=Path, required=True)
    p.add_argument('--baseline-results', type=Path, required=True)
    p.add_argument('--candidate-results', type=Path, required=True)
    p.add_argument('--approved', type=Path, default=Path('data/approved_model.json'))
    args = p.parse_args()
    print(write_approved(args.candidate, args.study_report, args.baseline_results,
                         args.candidate_results, args.approved))
