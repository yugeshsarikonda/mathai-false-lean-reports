#!/usr/bin/env python3
"""Offline scoring of the supplied frozen corpus with Lean 4.15.0.

Initial decision: first explicit DECISION match (historical definition).
Final outcome: first Lean block after the last explicit DECISION match must prove
exactly the displayed true statement; a false statement requires a final rejection.
No decision, absent proof, truncation, timeout, compilation error or sorry fails.
This is a corpus-specific extractor, not a general parser for arbitrary Lean files.
No model or network calls are made. Original scored CSVs are never overwritten.
"""
import argparse, concurrent.futures, csv, hashlib, json, os, pathlib, re, subprocess, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
DEC = re.compile(r'DECISION:\s*(KEEP|REVISE|REJECT_UNPROVABLE)', re.I)
PRF = re.compile(r'```(?:lean4?|)\s*\n(.*?)```', re.S)

def forall_form(src):
    sig = src.split('theorem T', 1)[1].split(':= by', 1)[0].strip()
    if sig.startswith(':'): return sig[1:].strip()
    depth = 0
    for i, ch in enumerate(sig):
        if ch in '([{': depth += 1
        elif ch in ')]}': depth -= 1
        elif depth == 0 and sig[i:i+3] == ' : ':
            return f'∀ {sig[:i].strip()}, {sig[i+3:].strip()}'
    raise ValueError('Unrecognized displayed theorem signature')

def theorem_check(proof, displayed):
    m = re.search(r'\b(theorem|lemma)\s+([^\s(:{\[]+)', proof or '')
    if not m: return None
    return proof.rstrip() + f'\n\nexample : {forall_form(displayed)} := @{m.group(2)}\n'

def lean_check(src, lean):
    # Conservative corpus guard: generated Lean can execute code while elaborating.
    if re.search(r'\b(axiom|unsafe|run_cmd|run_tac)\b|#eval', src):
        return 'blocked'
    with tempfile.TemporaryDirectory(prefix='mathai_score_') as td:
        path = pathlib.Path(td) / 'submission.lean'; path.write_text(src)
        try:
            r = subprocess.run([lean, str(path)], cwd=td, capture_output=True, text=True, timeout=30)
            output = (r.stdout or '') + (r.stderr or '')
            return 'failed' if r.returncode else 'vacuous' if 'sorry' in output else 'proved'
        except subprocess.TimeoutExpired: return 'timeout'

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--lean', default=os.environ.get('LEAN', 'lean'))
    ap.add_argument('--workers', type=int, default=6)
    args = ap.parse_args()
    version = subprocess.check_output([args.lean, '--version'], text=True).strip()
    if 'version 4.15.0' not in version: raise SystemExit('Use Lean 4.15.0: ' + version)
    datasets = [('claude', 'followup_claude', 'batch2_stimuli.json', 'batch2_scored.csv'),
                ('other_providers', 'other_providers', 'stimuli.json', 'scored.csv')]
    records, jobs, checks = [], set(), {}
    for label, folder, stimulus_file, legacy_file in datasets:
        directory = ROOT / 'data' / folder
        stimuli = json.loads((directory / stimulus_file).read_text())
        trials = {t['trial_id']: t for t in stimuli['trials']}
        for t in trials.values():
            assert hashlib.sha256(t['prompt'].encode()).hexdigest()[:16] == t['prompt_sha']
        legacy = list(csv.DictReader((directory / legacy_file).open()))
        raw = {}
        for path in sorted(directory.glob('*raw*.jsonl')):
            for line in path.read_text().splitlines():
                r = json.loads(line)
                key = (r.get('model_requested', r.get('deployment')), r['trial_id'])
                if key in raw: raise ValueError(f'Duplicate model/trial: {key}')
                raw[key] = r
        assert len(raw) == len(legacy)
        for old in legacy:
            r = raw[(old['model'], old['trial_id'])]; t = trials[old['trial_id']]
            assert not r.get('prompt_sha') or r['prompt_sha'] == t['prompt_sha']
            txt = r.get('text') or ''; assert txt == old['text']
            matches = list(DEC.finditer(txt)); first = matches[0].group(1).upper() if matches else ''
            last = matches[-1].group(1).upper() if matches else ''
            assert first == old['dec']
            displayed = PRF.search(t['prompt']).group(1)
            proof = PRF.search(txt[matches[-1].end():]) if matches else None
            check = theorem_check(proof.group(1).strip(), displayed) if proof else None
            if check: jobs.add(check)
            # The supplied Claude adapter records empty cap events in its error text,
            # with a null top-level stop_reason. Recover that recorded stop reason.
            truncated = (r.get('stop_reason') in ('max_tokens', 'length')
                         or 'max_tokens' in str(r.get('error') or '')
                         or (r.get('incomplete_details') or {}).get('reason') == 'max_output_tokens')
            if 'truncated' in old:
                assert truncated == (old['truncated'].lower() == 'true'), (old['model'], old['trial_id'], 'truncation mismatch')
            row = dict(old, legacy_outcome_correct=str(old['outcome_correct'].lower() == 'true'), last_dec=last,
                       last_dec_correct=str(last == t['correct']), decision_matches=len(matches),
                       conflicting_decisions=str(len({m.group(1).upper() for m in matches}) > 1),
                       proof_blocks=len(PRF.findall(txt)), reference=t['correct'],
                       scoring_policy='final_declared_v1', truncated=str(truncated))
            records.append((label, row, check, truncated))
        checks[label] = {'raw_records':len(raw), 'frozen_prompt_hashes':len(trials)}
    ordered = sorted(jobs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        cache = dict(zip(ordered, pool.map(lambda s: lean_check(s, args.lean), ordered)))
    dest = ROOT / 'data' / 'rescored'; dest.mkdir(parents=True, exist_ok=True)
    changes = []
    for label, *_ in datasets:
        rows = []
        for source, row, check, truncated in records:
            if source != label: continue
            status = cache.get(check, 'missing')
            outcome = (row['last_dec'] == 'REJECT_UNPROVABLE') if row['reference'] == 'REJECT_UNPROVABLE' else status == 'proved'
            row.update(outcome_correct=str(bool(outcome and row['last_dec'] and not truncated)), final_proof_status=status)
            if row['outcome_correct'].lower() != row['legacy_outcome_correct'].lower():
                changes.append({k:row[k] for k in ['model','trial_id','cell','legacy_outcome_correct','outcome_correct','dec','last_dec']})
            rows.append(row)
        with (dest / f'{label}.csv').open('w') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    with (dest / 'changed_outcomes.csv').open('w') as f:
        w = csv.DictWriter(f, fieldnames=list(changes[0])); w.writeheader(); w.writerows(changes)
    summary = dict(lean_version=version, unique_submitted_proof_checks=len(jobs), datasets=checks,
                   changed_outcomes=len(changes), policy='final_declared_v1',
                   scorer_revision='adapter_truncation_fix_1',
                   truncated_by_dataset={label:sum(int(t) for source, _, _, t in records if source==label) for label, *_ in datasets})
    (dest / 'scoring_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))

if __name__ == '__main__': main()
