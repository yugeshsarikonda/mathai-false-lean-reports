
import json, os, datetime
def run(stim_path, shard, out_path, chunk=24):
    S = json.load(open(stim_path))
    mine = [t for t in S["trials"] if t["shard"] == shard]
    def load_done():
        d = {}
        if os.path.exists(out_path):
            for line in open(out_path):
                r = json.loads(line); d[r["trial_id"]] = r
        return d
    def is_trunc(r):
        return r.get("stop_reason") == "max_tokens" or "max_tokens" in str(r.get("error") or "")
    def call(batch, attempt):
        reqs = [{"prompt": t["prompt"], "system": S["system"], "model": t["model"],
                 "max_tokens": t["max_tokens"]} for t in batch]
        sent = datetime.datetime.now(datetime.timezone.utc).isoformat()
        out = host.llm(reqs, max_concurrency=8)
        with open(out_path, "a") as f:
            for t, r in zip(batch, out):
                f.write(json.dumps({"trial_id": t["trial_id"], "attempt": attempt, "sent_utc": sent,
                    "model_requested": t["model"], "model_returned": r.get("model"),
                    "stop_reason": r.get("stop_reason"), "usage": r.get("usage"),
                    "text": r.get("text"), "error": r.get("error")}) + "\n")
    done = load_done()
    todo = [t for t in mine if t["trial_id"] not in done]
    for i in range(0, len(todo), chunk):
        call(todo[i:i+chunk], 1)
        print(f"{shard}: {min(i+chunk, len(todo))}/{len(todo)}", flush=True)
    done = load_done()
    retry = [t for t in mine if done[t["trial_id"]].get("error") and not is_trunc(done[t["trial_id"]])
             and done[t["trial_id"]]["attempt"] == 1]
    if retry:
        call(retry, 2)
    done = load_done()
    recs = [done[t["trial_id"]] for t in mine]
    summary = {"shard": shard, "n_trials": len(mine), "n_records": len(recs),
               "n_api_error_final": sum(1 for r in recs if r.get("error") and not is_trunc(r)),
               "n_truncated": sum(1 for r in recs if is_trunc(r)),
               "n_retried": len(retry)}
    print(summary)
    return summary
