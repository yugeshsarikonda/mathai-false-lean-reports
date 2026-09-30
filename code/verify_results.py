#!/usr/bin/env python3
"""Check the release snapshot without network access or dependencies.

This checks raw-record alignment, scoring rules, saved statistics and original data
preservation, without compiling Lean or rerunning statistical inference.
Run after extraction. --integrity verifies each file listed in SHA256SUMS.json.
Unlisted local files such as virtual environments are not part of that integrity check.
"""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT
EXPECTED = json.loads((ROOT / 'code/expected_results.json').read_text())
DECISION = re.compile(r'DECISION:\s*(KEEP|REVISE|REJECT_UNPROVABLE)', re.I)


def require(condition, description):
    if not condition:
        raise ValueError(description)


def read_csv(path):
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def truth(value):
    return str(value).lower() == 'true'


def key(row):
    return row['model'], row['trial_id']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(integrity=False):
    checks = []
    all_rows = []
    changed = []
    totals = {}
    legacy_paths = [('claude', 'followup_claude', 'batch2_stimuli.json', 'batch2_scored.csv'),
                    ('other_providers', 'other_providers', 'stimuli.json', 'scored.csv')]
    prompt_hashes = 0
    provider_record_hashes = 0
    for dataset, folder, stimuli_name, scores_name in legacy_paths:
        directory = PAPER / 'data' / folder
        frozen = json.loads((directory / stimuli_name).read_text())['trials']
        trials = {row['trial_id']: row for row in frozen}
        require(len(trials) == len(frozen) == EXPECTED['frozen_prompts'][dataset], 'Frozen trial IDs/count: ' + dataset)
        for trial in frozen:
            require(hashlib.sha256(trial['prompt'].encode()).hexdigest()[:16] == trial['prompt_sha'], 'Frozen prompt hash: ' + trial['trial_id'])
        prompt_hashes += len(frozen)
        raw = {}
        for path in sorted(directory.glob('*raw*.jsonl')):
            for line in path.read_text().splitlines():
                item = json.loads(line)
                item_key = item.get('model_requested', item.get('deployment')), item['trial_id']
                require(item_key not in raw, 'Duplicate raw key: ' + repr(item_key))
                raw[item_key] = item
        legacy = {key(row): row for row in read_csv(directory / scores_name)}
        rows = read_csv(PAPER / 'data/rescored' / (dataset + '.csv'))
        current = {key(row): row for row in rows}
        require(len(current) == len(rows) == len(raw) == EXPECTED['raw_records'][dataset], 'Record count: ' + dataset)
        require(set(current) == set(raw) == set(legacy), 'Raw/legacy/current record alignment: ' + dataset)
        for row in rows:
            r = raw[key(row)]
            old = legacy[key(row)]
            trial = trials[row['trial_id']]
            text = r.get('text') or ''
            require(text == row['text'] == old['text'], 'Response text changed: ' + repr(key(row)))
            if dataset == 'other_providers':
                require(r.get('prompt_sha') == trial['prompt_sha'], 'Provider prompt hash: ' + repr(key(row)))
                provider_record_hashes += 1
            elif r.get('prompt_sha'):
                require(r['prompt_sha'] == trial['prompt_sha'], 'Claude prompt hash: ' + repr(key(row)))
            matches = list(DECISION.finditer(text))
            first = matches[0].group(1).upper() if matches else ''
            last = matches[-1].group(1).upper() if matches else ''
            require(first == old['dec'] == row['dec'], 'Initial decision changed: ' + repr(key(row)))
            require(last == row['last_dec'], 'Final decision parse: ' + repr(key(row)))
            require(truth(row['dec_correct']) == truth(old['dec_correct']) == (first == trial['correct']), 'Initial accuracy: ' + repr(key(row)))
            require(row['reference'] == trial['correct'], 'Reference label: ' + repr(key(row)))
            truncated = (r.get('stop_reason') in ('max_tokens', 'length')
                         or 'max_tokens' in str(r.get('error') or '')
                         or (r.get('incomplete_details') or {}).get('reason') == 'max_output_tokens')
            require(truth(row['truncated']) == truncated, 'Truncation flag: ' + repr(key(row)))
            if 'truncated' in old:
                require(truth(old['truncated']) == truncated, 'Historical truncation flag: ' + repr(key(row)))
            require(truth(row['legacy_outcome_correct']) == truth(old['outcome_correct']), 'Legacy outcome copy: ' + repr(key(row)))
            outcome = last == 'REJECT_UNPROVABLE' if trial['correct'] == 'REJECT_UNPROVABLE' else row['final_proof_status'] == 'proved'
            require(truth(row['outcome_correct']) == bool(outcome and last and not truncated), 'Final outcome rule: ' + repr(key(row)))
            require(row['scoring_policy'] == 'final_declared_v1', 'Scoring policy identifier')
            if truth(row['outcome_correct']) != truth(old['outcome_correct']):
                changed.append({field: row[field] for field in ['model', 'trial_id', 'cell', 'legacy_outcome_correct', 'outcome_correct', 'dec', 'last_dec']})
        outcome_count = sum(truth(row['outcome_correct']) for row in rows)
        truncated_count = sum(truth(row['truncated']) for row in rows)
        require(outcome_count == EXPECTED['final_outcomes'][dataset], 'Final outcome total: ' + dataset)
        require(truncated_count == EXPECTED['truncated'][dataset], 'Truncation total: ' + dataset)
        totals[dataset] = {'records': len(rows), 'final_correct': outcome_count, 'truncated': truncated_count}
        all_rows.extend(rows)
    checks.append('All 1478 raw/current/legacy records, decisions, prompt identities and truncation flags agree.')

    saved_changes = read_csv(PAPER / 'data/rescored/changed_outcomes.csv')
    require(sorted(changed, key=key) == sorted(saved_changes, key=key), 'Exact outcome change ledger')
    require(len(changed) == EXPECTED['changed_outcomes'], 'Changed outcome count')
    require(len({(row['model'], row['cell']) for row in changed}) == EXPECTED['changed_cells'], 'Changed cell count')
    require(sum(truth(row['outcome_correct']) for row in changed) == EXPECTED['gains'], 'Outcome gains')
    require(sum(not truth(row['outcome_correct']) for row in changed) == EXPECTED['losses'], 'Outcome losses')
    checks.append('All 19 outcome changes match the ledger: 18 gains, one loss, 12 cells.')

    audit = {key(row): row for row in read_csv(PAPER / 'data/analysis/lean_outcome_audit.csv')}
    require(len(audit) == len(all_rows), 'Saved Lean outcome record count')
    for row in all_rows:
        require(truth(row['outcome_correct']) == truth(audit[key(row)]['final_declared_outcome']), 'Saved Lean audit agreement: ' + repr(key(row)))
    reference_checks = read_csv(PAPER / 'data/analysis/lean_reference_checks.csv')
    require(reference_checks and all(truth(row['matches_compile_reference']) for row in reference_checks), 'Saved reference-label check results')
    checks.append('Current outcomes agree with the saved Lean audit; saved reference checks report no mismatch. Lean was not rerun by this checker.')

    grouped = defaultdict(list)
    for row in all_rows:
        grouped[row['model'], row['cell']].append(row)
    counts = {(row['model'], row['cell']): row for row in read_csv(PAPER / 'data/analysis/all_cell_counts.csv')}
    require(set(counts) == set(grouped), 'Analysis cell identities')
    for cell_key, rows in grouped.items():
        row = counts[cell_key]
        actual = (sum(truth(x['dec_correct']) for x in rows), len(rows), sum(truth(x['outcome_correct']) for x in rows))
        saved = (int(row['decision_correct']), int(row['n']), int(row['outcome_correct']))
        require(actual == saved, 'Analysis aggregate: ' + repr(cell_key))
    for cell, expected in EXPECTED['sonnet_cap1400_truncation'].items():
        rows = grouped['claude-sonnet-5', cell]
        require([sum(truth(row['truncated']) for row in rows), len(rows)] == expected, 'Sonnet cap comparison: ' + cell)
    opus_haiku = {'claude-opus-4-5-20251101', 'claude-haiku-4-5-20251001'}
    for expected_name, cells in [('opushaiku_general_outcomes', ['OMG_notool', 'OMG_FE']), ('opushaiku_decide_outcomes', ['DEC_notool', 'DEC_FE'])]:
        for tag, cell in zip(['no_report', 'fabricated_error'], cells):
            rows = [row for row in all_rows if row['model'] in opus_haiku and row['cell'] == cell]
            require([sum(truth(row['outcome_correct']) for row in rows), len(rows)] == EXPECTED[expected_name][tag], expected_name + ': ' + tag)
    checks.append('All cell aggregates and specified Opus/Haiku and Sonnet comparisons agree.')

    analysis = json.loads((PAPER / 'data/analysis/audit_results.json').read_text())['followup']
    for family in ['holm_fisher', 'holm_paired_mcnemar', 'holm_item_signflip']:
        require(set(analysis[family]) == set(EXPECTED[family]), 'Five-comparison family identities: ' + family)
        for comparison, expected in EXPECTED[family].items():
            require(math.isclose(analysis[family][comparison], expected, rel_tol=1e-12, abs_tol=1e-15), family + ': ' + comparison)
    summary = json.loads((PAPER / 'data/rescored/scoring_summary.json').read_text())
    require(summary['scorer_revision'] == 'adapter_truncation_fix_1', 'Scorer revision')
    require(summary['truncated_by_dataset'] == EXPECTED['truncated'], 'Scoring summary truncation counts')
    require(summary['unique_submitted_proof_checks'] == 499, 'Saved unique proof check count')
    checks.append('All three saved Holm families match the baseline; numerical inference was not rerun by this checker.')

    original_hashes = json.loads((PAPER / 'data/original_file_sha256.json').read_text())
    require(len(original_hashes) == 22, 'Original data file count')
    for relative, expected in original_hashes.items():
        require(sha(PAPER / relative) == expected, 'Original data preservation: ' + relative)
    checks.append('All 22 original data files match their preservation hashes.')

    manifest_count = None
    if integrity:
        manifest = json.loads((ROOT / 'SHA256SUMS.json').read_text())
        for relative, expected in manifest.items():
            path = ROOT / relative
            require(path.resolve().is_relative_to(ROOT.resolve()), 'Manifest path escapes release')
            require(sha(path) == expected, 'Snapshot integrity: ' + relative)
        manifest_count = len(manifest)
        checks.append('Every file listed in the snapshot manifest matches its recorded hash.')
    return {'status': 'passed', 'checker_scope': 'Offline record consistency; no fresh Lean compilation, statistical inference or model calls.',
            'datasets': totals, 'frozen_prompt_hashes_checked': prompt_hashes,
            'provider_record_hashes_checked': provider_record_hashes, 'outcome_changes': len(changed), 'original_data_files_unchanged': len(original_hashes),
            'manifest_files_checked': manifest_count, 'checks': checks}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--integrity', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.integrity), indent=2))
    except (ValueError, KeyError, IndexError, OSError, AttributeError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, indent=2))
        sys.exit(1)
