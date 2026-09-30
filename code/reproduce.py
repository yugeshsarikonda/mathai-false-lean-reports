#!/usr/bin/env python3
"""Reproduce saved outcomes, statistics, reference checks and figure without model calls."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lean', default=os.environ.get('LEAN', 'lean'),
                        help='Lean 4.15.0 executable (default: LEAN environment variable or lean)')
    parser.add_argument('--workers', type=int, default=6,
                        help='Concurrent final-submission checks (default: 6; broader audit uses 6)')
    args = parser.parse_args()
    if args.workers < 1:
        parser.error('--workers must be positive')
    lean = os.path.expanduser(args.lean)
    if os.path.dirname(lean):
        lean = str(Path(lean).resolve())
    env = os.environ.copy()
    env['LEAN'] = lean
    # Keep elan on the pinned version even when a scorer checks files in a temporary directory.
    env['ELAN_TOOLCHAIN'] = 'leanprover/lean4:v4.15.0'
    steps = [
        ('Score final submissions', 'score_followup.py', ['--lean', lean, '--workers', str(args.workers)]),
        ('Recompute statistics', 'analyze_results.py', []),
        ('Check reference proofs and alternate scoring', 'audit_lean.py', []),
        ('Regenerate the figure', 'make_figure.py', []),
        ('Verify the regenerated results', 'verify_results.py', []),
    ]
    try:
        for i, (label, script, options) in enumerate(steps, 1):
            print(f'[{i}/{len(steps)}] {label}', flush=True)
            subprocess.run([sys.executable, str(ROOT / 'code' / script), *options],
                           cwd=ROOT, env=env, check=True)
    except FileNotFoundError as error:
        parser.exit(1, f'Executable not found: {error}\n')
    except subprocess.CalledProcessError as error:
        parser.exit(error.returncode, 'Reproduction stopped because a step failed. See the output above.\n')
    print('Reproduction complete: data/rescored/, data/analysis/ and figures/fig1_final.png.')


if __name__ == '__main__':
    main()
