"""How should learner feedback become a ranking signal? Offline comparison on eval/data (the app is unchanged).

  python eval/feedback_variants.py ROUNDS TAU [revisit]

Variants (all rerank the same 40 hybrid candidates with final = base x (1 + 0.1 x priority)):
  formula(1)              proposal: one global priority per passage, +0.5 useful / -1 not useful
  negative-only           only "not useful" counts, globally (a wrong passage is wrong for every question)
  similar-questions       each feedback counts in proportion to how similar its question is to the current one
  neg-global+pos-similar  "not useful" global, "useful" only for similar questions
Feedback is simulated with the quality policy on dev questions (new-question setting), or on dev + test questions
before scoring test questions again (revisit setting, e.g. answering the same question a second time).
TAU is the similarity floor (bge-m3 cosine), fixed a priori at 0.6, not tuned on test.
"""
import asyncio, os, random, sys, tempfile
from pathlib import Path
os.environ["MIANBI_DATA"] = tempfile.mkdtemp(); ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, ROOT); sys.path.insert(0, ROOT + "/eval")
import run; run.boot_app(False)
from app import retrieval
K, ROUNDS, TAU = 3, int(sys.argv[1]), float(sys.argv[2])
REVISIT = len(sys.argv) > 3 and sys.argv[3] == "revisit"
async def main():
    pid = await run.load_passages(run.Path(ROOT + "/eval/data"))
    Q = run.jl(run.Path(ROOT + "/eval/data/queries.jsonl"))
    dev, test = [q for q in Q if q["split"] == "dev"], [q for q in Q if q["split"] == "test"]
    emb = retrieval.mem()._embedder
    vec = dict(zip([q["id"] for q in Q], await emb.embed([q["question"] for q in Q])))
    async def pool(q):  # hybrid candidates, unique passages with base score
        hits = await retrieval.retrieve(run.USER, q["question"], 40, "hybrid")
        out = {}
        for h in hits:
            out.setdefault(pid[h["doc_id"]], h["base_score"])
        return out
    def rank(cands, prio):
        return sorted(cands, key=lambda p: -cands[p] * (1 + 0.1 * prio.get(p, 2)))[:K]
    # dev feedback replay (quality policy), learner sees formula-(1) ranking, events recorded per (query, passage)
    events, glob = [], {}
    for _ in range(ROUNDS):
        for q in (dev + test if REVISIT else dev):  # revisit: the learner already saw each test question once
            for p in rank(await pool(q), glob):
                if p in q["relevant"] or p in q.get("weak", []):
                    d = 0.5 if p in q["relevant"] else -1.0
                    events.append((q["id"], p, d)); glob[p] = min(5, max(0, glob.get(p, 2) + d))
    cos = lambda a, b: sum(x * y for x, y in zip(a, b))
    def variant(name, q):
        if name == "hybrid": return {}
        if name == "formula(1)": return glob
        pr = {}
        for qid, p, d in events:
            if name == "negative-only" and d < 0: w = 1
            elif name == "similar-questions": w = max(0.0, (cos(vec[q["id"]], vec[qid]) - TAU) / (1 - TAU))
            elif name == "neg-global+pos-similar": w = 1 if d < 0 else max(0.0, (cos(vec[q["id"]], vec[qid]) - TAU) / (1 - TAU))
            else: w = 0
            pr[p] = pr.get(p, 2) + d * w
        return {p: min(5, max(0, v)) for p, v in pr.items()}
    names = ["hybrid", "formula(1)", "negative-only", "similar-questions", "neg-global+pos-similar"]
    res = {n: [] for n in names}
    for q in test:
        cands = await pool(q)
        for n in names:
            r = rank(cands, variant(n, q)); rel = set(q["relevant"])
            res[n].append((len(rel & set(r)) / len(rel), run.ndcg(r, rel, K), len(set(q.get("weak", [])) & set(r)) / K))
    base = res["hybrid"]
    print(f"{'REVISIT' if REVISIT else 'NEW QUESTIONS'}: rounds={ROUNDS} tau={TAU} events={len(events)}")
    for n in names:
        m = [sum(x[i] for x in res[n]) / len(test) for i in range(3)]
        d = [res[n][j][1] - base[j][1] for j in range(len(test))]
        rnd = random.Random(0); bs = sorted(sum(rnd.choice(d) for _ in d) / len(d) for _ in range(5000))
        print(f"  {n:<24} Recall {m[0]:.3f}  nDCG {m[1]:.3f}  weak {m[2]:.3f}   dNDCG {sum(d)/len(d):+.3f} [{bs[125]:+.3f},{bs[4874]:+.3f}]")
asyncio.run(main())
