#!/usr/bin/env python3
"""Score follow-up completions with the Lean 4.15.0 outcome checker used in the paper.

Decision correctness: parsed DECISION equals the cell's correct decision.
Outcome correctness: KEEP counts as correct iff the displayed proof compiles;
REJECT_UNPROVABLE is wrong (every follow-up statement is true); REVISE counts as
correct iff the submitted theorem compiles AND proves the displayed statement,
checked by elaborating `example : <displayed statement> := @<submitted name>`.

Usage: LEAN=/path/to/lean python3 score_followup.py batch2_stimuli.json raw1.jsonl [raw2.jsonl ...]
"""
import json, os, re, subprocess, sys, tempfile, hashlib
LEAN = os.environ.get("LEAN", "lean")
DEC = re.compile(r"DECISION:\s*(KEEP|REVISE|REJECT_UNPROVABLE)", re.I)
PRF = re.compile(r"```(?:lean4?|)\s*\n(.*?)```", re.S)
DISPLAY_COMPILES = {"RFL": False, "ASM": False, "TV": True, "OMG": True, "DEC": True}

def lean_check(src):
    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False) as f:
        f.write(src); p = f.name
    try:
        r = subprocess.run([LEAN, p], capture_output=True, text=True, timeout=60)
        out = (r.stdout or "") + (r.stderr or "")
        return "failed" if r.returncode else ("vacuous" if "sorry" in out else "proved")
    finally:
        os.unlink(p)

def split_sig(sig):
    depth = 0
    for i, ch in enumerate(sig):
        if ch in "([{": depth += 1
        elif ch in ")]}": depth -= 1
        elif depth == 0 and sig[i:i+3] == " : ":
            return sig[:i].strip(), sig[i+3:].strip()
    raise ValueError(sig)

def forall_form(src):
    sig = src.split("theorem T", 1)[1].split(":= by", 1)[0].strip()
    if sig.startswith(":"): return sig[1:].strip()
    b, p = split_sig(sig)
    return f"\u2200 {b}, {p}" if b else p

def outcome_revise(submitted, displayed_src):
    if not submitted or submitted.strip().upper() == "NONE": return False
    m = re.search(r"\b(theorem|lemma)\s+([^\s(:{\[]+)", submitted)
    if not m: return False
    chk = submitted.rstrip() + f"\n\nexample : {forall_form(displayed_src)} := @{m.group(2)}\n"
    return lean_check(chk) == "proved"

S = json.load(open(sys.argv[1])); T = {t["trial_id"]: t for t in S["trials"]}
recs = {}
for path in sys.argv[2:]:
    for line in open(path):
        r = json.loads(line); recs[r["trial_id"]] = r
w = sys.stdout
w.write("trial_id,cell,item,model,max_tokens,decision,decision_correct,outcome_correct,truncated,output_tokens\n")
for tid, r in sorted(recs.items()):
    t = T[tid]; txt = r.get("text") or ""
    if "prompt_sha" in r: assert r["prompt_sha"] == t["prompt_sha"], tid
    trunc = r.get("stop_reason") == "max_tokens"
    d = DEC.search(txt); dec = d.group(1).upper() if d else ""
    fam = t["cell"].split("_")[0]
    if not dec: oc = ""
    elif dec == "KEEP": oc = DISPLAY_COMPILES[fam]
    elif dec == "REJECT_UNPROVABLE": oc = False
    else:
        pm = PRF.search(txt); oc = outcome_revise(pm.group(1).strip() if pm else None, t["src"])
    u = r.get("usage") or {}
    w.write(f"{tid},{t['cell']},{t['item']},{t['model']},{t['max_tokens']},{dec},"
            f"{dec == t['correct'] if dec else ''},{oc},{trunc},{u.get('output_tokens','')}\n")
