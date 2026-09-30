# False Lean reports: reproducibility code

Recompute decisions, proof outcomes, statistics and the summary figure from the included experiment records. The default workflow runs entirely offline after Python dependencies and Lean are installed. It uses no model API, credentials or paid completions.

## Quick start

Use Python **3.14** and Lean **4.15.0** for the tested environment. Python analysis dependencies are pinned in `code/requirements.txt`. Mathlib, a GPU and LaTeX are not required.

1. Clone the repository and enter its root directory:

   ```sh
   git clone https://github.com/yugeshsarikonda/mathai-false-lean-reports.git
   cd mathai-false-lean-reports
   ```
2. Install Lean using the [official installation instructions](https://lean-lang.org/install/). With the `elan` toolchain manager installed, run:

   ```sh
   elan toolchain install leanprover/lean4:v4.15.0
   lean --version
   ```

   The included `lean-toolchain` selects version 4.15.0 in this repository.
3. Create a Python environment and install the pinned dependencies:

   ```sh
   python3.14 -m venv .venv
   .venv/bin/python -m pip install -r code/requirements.txt
   ```

4. Verify the downloaded snapshot, then reproduce the results:

   ```sh
   .venv/bin/python code/verify_results.py --integrity
   .venv/bin/python code/reproduce.py
   ```

If Lean is installed outside your PATH, pass its executable:

```sh
.venv/bin/python code/reproduce.py --lean /absolute/path/to/lean-4.15.0/bin/lean
```

On Windows, use `py -3.14 -m venv .venv` and `.venv\Scripts\python.exe` in place of `.venv/bin/python`; the Lean executable ends in `.exe`. The complete workflow was checked on macOS with Python 3.14.6 and Lean 4.15.0; Windows and Linux have not been tested in this repository preparation pass.

The run regenerates `data/rescored/`, `data/analysis/` and `figures/fig1_final.png`, then checks their results against the included reference counts. It leaves original inputs intact. The final-submission scorer uses six parallel Lean processes by default and a 30-second timeout per source. Use `--workers 2` to reduce its concurrency; the broader reference audit uses six workers.

## Expected results

| Dataset | Retained responses | Correct final outcomes | Truncated responses |
|---|---:|---:|---:|
| Claude | 554 | 425 | 9 |
| Other providers | 924 | 527 | 0 |
| Total | 1478 | 952 | 9 |

The final-submission scorer checks **499 distinct Lean sources**. The broader audit checks **637 sources**, including working references and explicit counterexamples for all 14 false variants. There should be **zero reference-label mismatches**. The workflow also validates 785 frozen prompt hashes and 924 provider-record prompt hashes.

`code/verify_results.py` checks record alignment, the saved scoring rule, cell totals, three Holm-adjusted comparison families, the outcome-change ledger and the preservation hashes for all 22 original data files. It requires only Python's standard library and can be used without Lean:

```sh
python3 code/verify_results.py
```

`--integrity` additionally checks every file listed in `SHA256SUMS.json`; unlisted local files, such as a virtual environment, are ignored. Use this option on a fresh checkout. After regeneration, the Lean version string, compiler diagnostics or image encoding can differ across platforms even when the numerical results agree. The normal checker tests results without requiring byte-identical regenerated files. The snapshot manifest is not updated automatically.

## Repository contents

| Location | Purpose |
|---|---|
| `code/reproduce.py` | Run all offline stages in order and stop if any fails |
| `code/score_followup.py` | Score both later datasets against the unchanged theorem statement |
| `code/analyze_results.py` | Recompute counts, descriptive intervals and paired statistical sensitivities |
| `code/audit_lean.py` | Check reference labels, counterexamples and alternative proof-extraction rules |
| `code/make_figure.py` | Recreate the three-panel plot from trial records |
| `code/verify_results.py`, `code/expected_results.json` | Check saved or regenerated results against reference values |
| `code/score_followup_legacy.py` | Historical scoring implementation, retained to explain legacy fields; not part of the default workflow |
| `code/run_claude_followup.py`, `code/run_other_providers.py` | Original collection code, retained to document how requests were made; see the limits below |
| `data/original/` | Original task bank, report strings, scored trials and historical summaries |
| `data/followup_claude/` | Frozen prompts, original raw responses and original Claude scores |
| `data/other_providers/` | Frozen prompts, original raw responses and original provider scores |
| `data/rescored/` | Current scores, earlier outcome fields, change ledger and scoring summary |
| `data/analysis/` | Cell counts, statistics, parser comparisons and Lean diagnostics |
| `data/original_file_sha256.json` | Preservation hashes of the original inputs |
| `figures/fig1_final.png` | Reproduced summary plot |

## Data and scoring conventions

A record is identified by **model plus trial ID**; trial IDs alone are not unique across deployments. Each `stimuli.json` or `batch2_stimuli.json` stores a system message and a `trials` list, including the prompt, condition, reference decision and prompt hash. Raw `.jsonl` files contain one JSON object per retained response. Historical scored CSVs stay unchanged; current scores are written separately to `data/rescored/`.

Reference decisions are `KEEP` for a working proof, `REVISE` for a true statement with an insufficient proof, and `REJECT_UNPROVABLE` for a false statement. Common condition names use `NT` or `notool` for no report, `TV` for a truthful report, `FV` for a fabricated report, `FS` for fabricated success and `FE` for fabricated error. `RFL`, `ASM`, `OMG` and `DEC` identify the displayed tactic or general/closed proof condition. The frozen prompt is the authoritative definition of a trial.

- **Initial decision:** the first explicit `DECISION:` match. `dec_correct` compares it with the reference.
- **Final outcome:** the last explicit decision and the first Lean block after it. A true statement needs a compiling proof of the unchanged full theorem; a false statement needs a final rejection. Missing decisions, missing proofs for true statements, truncations, timeouts, compilation errors and proofs using `sorry` fail.
- **Scoring history:** the current policy, `final_declared_v1`, was chosen after inspecting the responses. It changes 19 final outcomes in 12 cells relative to the historical scores: 18 gains and one loss. Initial decisions are unchanged. `changed_outcomes.csv` records each change.
- **Truncation:** scorer revision `adapter_truncation_fix_1` includes the nine empty Claude cap events whose stop reason appears in adapter error text. These remain failures in the denominator.

The proof extractor handles this corpus's theorem signatures. Its declaration guard is not a general sandbox for arbitrary Lean programs. Use it with the included data.

## Individual stages

For separate runs, set `LEAN` to the actual Lean 4.15.0 executable, or export the pinned `ELAN_TOOLCHAIN` when using elan's `lean` command:

```sh
export ELAN_TOOLCHAIN=leanprover/lean4:v4.15.0
.venv/bin/python code/score_followup.py
.venv/bin/python code/analyze_results.py
.venv/bin/python code/audit_lean.py
.venv/bin/python code/make_figure.py
.venv/bin/python code/verify_results.py
```

Analysis must run after scoring. `reproduce.py` sets the toolchain for all subprocesses, including checks performed in temporary directories.

## Reproduction limits and original collectors

The included records support offline reproduction of the saved results. Original raw completions from the earliest experiment were not retained, and the Claude collection script depends on an unavailable external `host.llm` adapter. Hosted model labels and defaults can also change. Exact replay of every historical request is therefore not supported.

The original collectors are not invoked by `reproduce.py`. `run_claude_followup.py` defines a function that requires the external adapter; it is not a standalone collection command. `run_other_providers.py` expects a deployment name, optionally a worker count, a `stimuli.json` in the current directory, and the `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_V1_BASE` environment variables. It makes paid network requests and appends `gpt_raw_<deployment>.jsonl` to that directory. If adapting it for a new experiment, use a separate `runs/` directory and preserve the frozen inputs. New model samples are not expected to match the retained outcomes exactly.

## License

Research data, figures and research documentation are licensed under **CC BY 4.0** (`LICENSE`). Code and its usage documentation are licensed under **MIT** (`code/LICENSE`). The grants cover author controlled rights only; see `LICENSE-NOTE.md` and `THIRD_PARTY_NOTICES.md` for scope. Retain attribution to Yugesh Sarikonda when reusing licensed research materials.
