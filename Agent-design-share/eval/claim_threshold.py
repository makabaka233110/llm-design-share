"""Choose the relevance floor for claim-check passages (ITERATION_LOG.md: irrelevant passages attached to claims).

For every sentence of every answer, the evaluator gets the most similar of its top 3 passages. Without a floor a
sentence with no matching material still gets *some* passage (a SWOT answer was "checked" against TIME_WAIT).
Label: the passage is relevant if it is labelled relevant (or weak, i.e. on-topic) for the case's question.
The same is measured for the question-level top 3. Each floor is chosen on dev and reported on test
(claims: highest precision with recall >= 0.9; question evidence: recall >= 0.95, losing evidence is costlier):

  python eval/claim_threshold.py
"""
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ["MIANBI_DATA"] = tempfile.mkdtemp()
ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, ROOT)
sys.path.insert(0, ROOT + "/eval")
import run  # noqa: E402

run.boot_app(False)
from app import retrieval  # noqa: E402


async def main():
    data = Path(ROOT) / "eval/data"
    pid = await run.load_passages(data)
    queries = {q["family"] if "family" in q else q["id"]: q for q in run.jl(data / "queries.jsonl")}
    rows = {"dev": [], "test": []}
    qrows = {"dev": [], "test": []}  # question-level evidence: top 3 for question + concept
    for q in queries.values():
        on_topic = set(q["relevant"]) | set(q.get("weak", []))
        text = f"{q['question']} {q.get('concept', '')}"
        for h in await retrieval.retrieve(run.USER, text, 3, "hybrid", reviewed_only=True):
            qrows[q["split"]].append((await retrieval.similarity(text, h["content"]), pid[h["doc_id"]] in on_topic))
    for c in run.jl(data / "cases.jsonl"):
        q = queries[c["family"]]
        on_topic = set(q["relevant"]) | set(q.get("weak", []))
        for claim in retrieval.claims(c["answer"]):
            if len(re.findall(r"\w", claim)) < retrieval.MIN_CLAIM_CHARS:
                continue
            hits = await retrieval.retrieve(run.USER, claim, retrieval.CLAIM_CANDIDATES, "hybrid", reviewed_only=True)
            sim, h = max([(await retrieval.similarity(claim, h["content"]), h) for h in hits], key=lambda x: x[0])
            rows[c["split"]].append((sim, pid[h["doc_id"]] in on_topic))

    def at(rs, t):
        kept = [r for r in rs if r[0] >= t]
        tp = sum(ok for _, ok in kept)
        return (tp / len(kept) if kept else 1.0, tp / max(1, sum(ok for _, ok in rs)), len(kept) / len(rs))

    for name, table in (("claim -> passage", rows), ("question -> top 3", qrows)):
        print(f"== {name}")
        for split, rs in table.items():
            print(f"{split}: {len(rs)} pairs, on-topic without a floor {sum(ok for _, ok in rs) / len(rs):.2f}")
        print("floor  precision(dev) recall(dev) kept(dev) | precision(test) recall(test) kept(test)")
        for t in [x / 100 for x in range(30, 76, 5)]:
            d, s_ = at(table["dev"], t), at(table["test"], t)
            print(f"{t:.2f}   {d[0]:.2f}  {d[1]:.2f}  {d[2]:.2f} | {s_[0]:.2f}  {s_[1]:.2f}  {s_[2]:.2f}")


asyncio.run(main())
