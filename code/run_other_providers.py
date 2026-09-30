#!/usr/bin/env python3
"""Run the frozen 231-trial stimuli on an Azure OpenAI deployment through the Responses API.
Connection change vs run_gpt.py: the Responses API (POST <v1>/responses, body {model, input, max_output_tokens})
replaces chat/completions because gpt-5-pro is served only there; gpt-4o uses the same API for consistency.
Prompts, system message, cap (16000) and default sampling are unchanged. The key is read from the environment."""
import json, sys, time, datetime, hashlib, urllib.request, urllib.error, concurrent.futures as cf, os
DEP = sys.argv[1]; WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 8
KEY = os.environ["AZURE_OPENAI_API_KEY"]
# e.g. https://<resource>.openai.azure.com/openai/v1 ; GPT-5 Pro may need https://<resource>.services.ai.azure.com/openai/v1
BASE = os.environ["AZURE_OPENAI_V1_BASE"].rstrip("/")
URL = BASE + "/responses"
S = json.load(open("stimuli.json")); OUT = f"gpt_raw_{DEP}.jsonl"
for t in S["trials"]:
    assert hashlib.sha256(t["prompt"].encode()).hexdigest()[:16] == t["prompt_sha"]
def text_of(r):
    return "".join(c.get("text", "") for it in (r.get("output") or []) if it.get("type") == "message"
                   for c in (it.get("content") or []) if c.get("type") in ("output_text", "text"))
def one(t):
    body = {"model": DEP, "input": [{"role": "system", "content": S["system"]},
                                    {"role": "user", "content": t["prompt"]}], "max_output_tokens": 16000}
    last = None
    for attempt in range(1, 7):
        sent = datetime.datetime.now(datetime.timezone.utc).isoformat(); t0 = time.time()
        try:
            req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "api-key": KEY})
            with urllib.request.urlopen(req, timeout=1800) as resp:
                r = json.loads(resp.read().decode())
            return {"trial_id": t["trial_id"], "prompt_sha": t["prompt_sha"], "deployment": DEP,
                    "api": "responses (Azure OpenAI v1)", "sent_utc": sent, "latency_s": round(time.time() - t0, 1),
                    "attempt": attempt, "response_id": r.get("id"), "model_returned": r.get("model"),
                    "status": r.get("status"), "incomplete_details": r.get("incomplete_details"),
                    "usage": r.get("usage"), "text": text_of(r), "error": None}
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode(errors='replace')[:400]}"
            if e.code in (408, 429, 500, 502, 503, 504): time.sleep(min(90, 10 * 2 ** (attempt - 1))); continue
            break
        except Exception as e:
            last = f"{type(e).__name__}: {e}"; time.sleep(min(90, 10 * 2 ** (attempt - 1)))
    return {"trial_id": t["trial_id"], "prompt_sha": t["prompt_sha"], "deployment": DEP, "error": last, "text": None}
done = set()
if os.path.exists(OUT):
    for line in open(OUT):
        r = json.loads(line)
        if not r.get("error"): done.add(r["trial_id"])
todo = [t for t in S["trials"] if t["trial_id"] not in done]
print(f"{DEP}: to run {len(todo)}, already done {len(done)}", flush=True)
with open(OUT, "a") as f, cf.ThreadPoolExecutor(WORKERS) as ex:
    for k, rec in enumerate(ex.map(one, todo), 1):
        f.write(json.dumps(rec) + "\n"); f.flush()
        if rec.get("error"): print("ERROR", rec["trial_id"], rec["error"][:200], flush=True)
        if k % 20 == 0 or k == len(todo): print(f"{DEP} {k}/{len(todo)}", flush=True)
ok = sum(1 for line in open(OUT) if not json.loads(line).get("error"))
print(f"{DEP} finished: {ok} successful records", flush=True)
