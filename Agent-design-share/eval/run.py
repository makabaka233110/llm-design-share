"""Experiment runner for proposal §4. Each subcommand reads JSONL from --data and writes to --out.

  retrieval   BM25 / dense / hybrid / priority-weighted: Recall@3, nDCG@3, latency, per domain
  evaluator   evidence vs no-evidence evaluation on strong/flawed answers + blinded rating sheet
  hints       generic vs preference-conditioned hints on later questions + blinded rating sheet
  history     current-answer-only vs history-aware evaluation of the last attempt
  scenarios   two scenario variants per held-out question + automatic checks + rating sheet
  asr         SenseVoice on recordings vs manual transcripts: CER + summary-faithfulness rating sheet
  cards       generated flashcards (default 20) + evidence-support / concept-coverage rating sheet
  stats       inter-rater agreement, model-vs-human score error, per-domain means and
              paired bootstrap CI (concept-family level) from a rated sheet

Every LLM experiment also writes usage.json (calls, failures, tokens, latency, cost).

Data files and fields are described in eval/README.md. Uses its own data dir, so test
answers, labels and generated evaluations never enter the app's reference index.
"""

import argparse
import asyncio
import csv
import json
import math
import re
import subprocess
import os
import random
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SEED = 7503
USER = "eval"


def jl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def boot_app(fresh: bool = True):
    """Import the app against an isolated data dir (and load .env for LLM settings)."""
    if "app.db" in sys.modules and fresh:  # db.DATA_DIR is fixed at import time
        raise RuntimeError("app was imported before boot_app(); the run would use the project's data dir")
    if fresh:
        os.environ["MIANBI_DATA"] = tempfile.mkdtemp(prefix="mianbi-eval-")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from app import db
    db.init()


async def load_passages(data: Path) -> dict[int, str]:
    """Index passages.jsonl as docs. Returns doc_id -> passage id."""
    from app import db, retrieval
    mapping = {}
    for p in jl(data / "passages.jsonl"):
        did = db.insert("docs", user_id=USER, title=p.get("title", p["id"]), topic=p.get("topic", ""),
                        source=p.get("source", ""), priority=p.get("priority", retrieval.P_DEFAULT),
                        reviewed=int(p.get("reviewed", True)), updated_at=db.now())
        await retrieval.write_doc(did, p.get("title", p["id"]), p["text"])
        mapping[did] = p["id"]
    return mapping


def split(rows: list[dict], name: str | None) -> list[dict]:
    picked = [r for r in rows if not name or r.get("split") == name]
    if rows and not picked:
        sys.exit(f"no rows with split={name!r}; omit --split or add the field")
    return picked


# ── retrieval ───────────────────────────────────────────────────────────

def ndcg(ranked: list[str], relevant: set[str], k: int) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, p in enumerate(ranked[:k]) if p in relevant)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return dcg / ideal if ideal else 0.0


async def cmd_retrieval(a):
    boot_app()
    from app import retrieval
    pid = await load_passages(a.data)
    queries = split(jl(a.data / "queries.jsonl"), a.split)
    rows, per = [], defaultdict(lambda: defaultdict(list))
    for mode in retrieval.MODES:
        for q in queries:
            t0 = time.perf_counter()
            hits = await retrieval.retrieve(USER, q["question"], a.k * 4, mode)  # chunks -> unique passages
            ms = (time.perf_counter() - t0) * 1000
            ranked = list(dict.fromkeys(pid[h["doc_id"]] for h in hits))[:a.k]
            rel = set(q["relevant"])
            r = {"mode": mode, "query": q["id"], "domain": q.get("domain", ""), "ms": ms,
                 "recall": len(rel & set(ranked)) / len(rel), "ndcg": ndcg(ranked, rel, a.k), "ranked": ranked}
            rows.append(r)
            for key in ("all", r["domain"]):
                for m in ("recall", "ndcg", "ms"):
                    per[(mode, key)][m].append(r[m])
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "retrieval_runs.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    print(f"{'mode':<9} {'domain':<12} {'n':>3} {'Recall@'+str(a.k):>9} {'nDCG@'+str(a.k):>8} {'ms':>7}")
    for (mode, dom), m in sorted(per.items()):
        n = len(m["recall"])
        print(f"{mode:<9} {dom:<12} {n:>3} {sum(m['recall'])/n:>9.3f} {sum(m['ndcg'])/n:>8.3f} {sum(m['ms'])/n:>7.1f}")


# ── shared helpers for LLM experiments ──────────────────────────────────

def add_question(q: dict, **extra) -> dict:
    from app import db
    qid = db.insert("questions", user_id=USER, text=q["question"], concept=q.get("concept", ""),
                    kind=q.get("kind", "knowledge"), origin="eval", **extra)
    return db.row("SELECT * FROM questions WHERE id=?", qid)


def blind_sheet(path: Path, items: list[dict], fields: list[str], rating_cols: list[str]):
    """Shuffle items, hide the condition, write the key separately."""
    rnd = random.Random(SEED)
    items = items[:]
    rnd.shuffle(items)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item", *fields, *(f"{c}_r1" for c in rating_cols), *(f"{c}_r2" for c in rating_cols)])
        for i, it in enumerate(items):
            w.writerow([i, *(it[k] for k in fields), *[""] * 2 * len(rating_cols)])
    key = [{"item": i, "condition": it["condition"], "family": it["family"], "domain": it.get("domain", ""),
            "case": it["case"], **it.get("key", {})} for i, it in enumerate(items)]
    path.with_suffix(".key.jsonl").write_text("\n".join(json.dumps(k, ensure_ascii=False) for k in key))


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def usage(out: Path):
    """Operational cost of the run (proposal §4): from the isolated run's llm_log."""
    from app import db, llm
    rs = db.rows("""SELECT task, COUNT(*) calls, SUM(ok=0) failures, SUM(tokens_in) tokens_in,
                      SUM(tokens_out) tokens_out, AVG(ms) avg_ms FROM llm_log GROUP BY task ORDER BY task""")
    for r in rs:
        r["cost_usd"] = llm.cost(r["tokens_in"], r["tokens_out"])
    tot = {k: sum(r[k] or 0 for r in rs) for k in ("calls", "failures", "tokens_in", "tokens_out", "cost_usd")}
    (out / "usage.json").write_text(json.dumps({"model": llm.MODEL, "tasks": rs, "total": tot}, ensure_ascii=False, indent=1))
    if tot["calls"]:
        print(f"usage: {tot['calls']} calls, failure rate {tot['failures'] / tot['calls']:.2%}, "
              f"tokens {tot['tokens_in']}/{tot['tokens_out']}, cost ${tot['cost_usd']:.4f} "
              f"(set LLM_PRICE_IN/OUT for cost)")


def balanced_subset(cases: list[dict], n: int) -> list[dict]:
    """Pre-specified blind subset: round-robin over (domain, answer_type) cells, shuffled with the fixed seed.
    Depends only on case metadata, never on model outputs."""
    cells = defaultdict(list)
    for c in sorted(cases, key=lambda c: c["id"]):
        cells[(c.get("domain", ""), c["answer_type"])].append(c)
    rnd = random.Random(SEED)
    for v in cells.values():
        rnd.shuffle(v)
    picked, order = [], sorted(cells)
    while len(picked) < n and any(cells.values()):
        for k in order:
            if cells[k] and len(picked) < n:
                picked.append(cells[k].pop())
    return picked


# ── evaluator: evidence vs none ─────────────────────────────────────────

async def cmd_evaluator(a):
    boot_app()
    from app import agent
    await load_passages(a.data)
    cases = split(jl(a.data / "cases.jsonl"), a.split)
    subset_file = a.out / "evaluator_subset.txt"
    if a.subset_file:
        blind = set(Path(a.subset_file).read_text().split())
    else:
        blind = {c["id"] for c in balanced_subset(cases, a.subset)}
    a.out.mkdir(parents=True, exist_ok=True)
    subset_file.write_text("\n".join(sorted(blind)))
    out, items = [], []
    for c in cases:
        for cond in a.conditions.split(","):
            q = add_question(c)
            att = agent.record_attempt(USER, q["id"], c["answer"], "eval")
            ev = await agent.evaluate(USER, q, att, kind=q["kind"], evidence_mode=cond, history_aware=False)
            avg = mean(list(ev["scores"].values())) if ev["scores"] else None
            out.append({"case": c["id"], "family": c["family"], "domain": c.get("domain", ""),
                        "answer_type": c["answer_type"], "condition": cond, "status": ev["status"], "avg": avg,
                        "scores": ev["scores"], "feedback": ev["feedback"], "evidence": ev["evidence"]})
            fb = ev["feedback"]
            text = "\n".join([f"状态：{ev['status']}", f"分数：{ev['scores']}",
                              *("遗漏：" + p["text"] for p in fb.get("omissions", [])),
                              *("误解：" + p["text"] for p in fb.get("misconceptions", [])),
                              *("建议：" + r for r in fb.get("revisions", []))])
            if c["id"] in blind:
                items.append({"case": c["id"], "family": c["family"], "domain": c.get("domain", ""), "condition": cond,
                              "question": c["question"], "answer": c["answer"], "feedback": text,
                              "evidence": "\n".join(f"[{e['eid']}] {e['snippet']}" for e in ev["evidence"]),
                              "key": {"answer_type": c["answer_type"], "model_score": avg, "status": ev["status"]}})
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "evaluator_runs.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out))
    blind_sheet(a.out / "evaluator_rating.csv", items, ["question", "answer", "feedback", "evidence"],
                ["correctness", "usefulness", "citation_support", "human_score"])
    print(f"blind subset: {len(blind)} cases x {len(a.conditions.split(','))} conditions -> {len(items)} sheet rows "
          f"({subset_file})")
    print(f"{'condition':<9} {'domain':<12} {'n':>3} {'valid':>6} {'uncert':>6} {'strong':>7} {'flawed':>7} {'sep':>6}")
    for cond in a.conditions.split(","):
        for dom in ["all", *sorted({r["domain"] for r in out})]:
            rs = [r for r in out if r["condition"] == cond and dom in ("all", r["domain"])]
            ok = [r for r in rs if r["status"] == "ok"]
            strong = mean([r["avg"] for r in ok if r["answer_type"] == "strong"])
            flawed = mean([r["avg"] for r in ok if r["answer_type"] != "strong"])
            print(f"{cond:<9} {dom:<12} {len(rs):>3} {len(ok)/len(rs):>6.2f} {sum(r['status']=='uncertain' for r in rs):>6} "
                  f"{strong:>7.2f} {flawed:>7.2f} {strong-flawed:>6.2f}")
    usage(a.out)


# ── hints: generic vs preference-conditioned ────────────────────────────

async def cmd_hints(a):
    boot_app()
    from app import agent, db, retrieval
    await load_passages(a.data)
    items = []
    for s in jl(a.data / "hint_sequences.jsonl"):
        db.delete_user(USER + "-h")
        user = USER + "-h"
        # history (strictly earlier in time than the later tasks)
        for h in s["history"]:
            q = add_question(h)
            db.run("UPDATE questions SET user_id=? WHERE id=?", user, q["id"])
            hid = db.insert("hints", user_id=user, question_id=q["id"], text=h["hint"], pref_version=0)
            db.update("hints", hid, rating=h["rating"], comment=h.get("comment", ""), feedback_at=db.now())
        if s["history"]:
            agent.update_prefs(user)
        for t in s["later"]:
            q = add_question(t)
            db.run("UPDATE questions SET user_id=? WHERE id=?", user, q["id"])
            passages = await retrieval.evidence(USER, f"{q['text']} {q['concept']}")
            for cond, pers in (("generic", False), ("personalized", True)):
                h = agent.hint(user, q, pers, passages)
                items.append({"case": f"{s['id']}:{t['id']}", "family": t.get("family", s["id"]),
                              "domain": t.get("domain", ""), "condition": cond, "question": t["question"],
                              "target_preference": s.get("target_preference", ""), "hint": h["text"]})
    a.out.mkdir(parents=True, exist_ok=True)
    blind_sheet(a.out / "hints_rating.csv", items, ["question", "target_preference", "hint"],
                ["fits_preference", "too_direct", "too_vague", "useful", "factually_correct"])
    print(f"{len(items)} hints written to {a.out/'hints_rating.csv'}")
    usage(a.out)


# ── history-aware vs current-only ───────────────────────────────────────

async def cmd_history(a):
    boot_app()
    from app import agent
    await load_passages(a.data)
    out, items = [], []
    for h in jl(a.data / "histories.jsonl"):
        for cond, aware in (("current_only", False), ("history_aware", True)):
            q = add_question(h)
            for i, ans in enumerate(h["attempts"]):
                att = agent.record_attempt(USER, q["id"], ans, "eval")
                last = i == len(h["attempts"]) - 1
                ev = await agent.evaluate(USER, q, att, kind=q["kind"], history_aware=aware and last)
            out.append({"case": h["id"], "family": h.get("family", h["id"]), "condition": cond,
                        "label": h["label"], "recurring": ev["feedback"].get("recurring", []),
                        "resolved": ev["feedback"].get("resolved", []),
                        "misconceptions": [p["text"] for p in ev["feedback"].get("misconceptions", [])],
                        "expected_recurring": h.get("recurring", []), "status": ev["status"]})
            fb = ev["feedback"]
            items.append({"case": h["id"], "family": h.get("family", h["id"]), "domain": h.get("domain", ""),
                          "condition": cond, "question": h["question"],
                          "attempts": "\n".join(f"第{i + 1}次：{x}" for i, x in enumerate(h["attempts"])),
                          "feedback": "\n".join([*("反复出现：" + x for x in fb.get("recurring", [])),
                                                  *("已改正：" + x for x in fb.get("resolved", [])),
                                                  *("误解：" + p["text"] for p in fb.get("misconceptions", [])),
                                                  *("建议：" + x for x in fb.get("revisions", []))]),
                          "key": {"label": h["label"]}})
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "history_runs.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out))
    blind_sheet(a.out / "history_rating.csv", items, ["question", "attempts", "feedback"],
                ["recurring_identified", "false_recurring", "suggestion_relevance"])
    print("Annotate history_runs.jsonl against labels (persistent / partial / corrected); automatic view:")
    for cond in ("current_only", "history_aware"):
        rs = [r for r in out if r["condition"] == cond]
        flagged = lambda r: bool(r["recurring"]) or (cond == "current_only" and bool(r["misconceptions"]))  # noqa
        det = mean([flagged(r) for r in rs if r["label"] == "persistent"])
        false = mean([flagged(r) for r in rs if r["label"] == "corrected"])
        print(f"{cond:<14} recurring-error flagged (persistent)={det:.2f}  false flags (corrected)={false:.2f}")
    usage(a.out)


# ── scenarios ───────────────────────────────────────────────────────────

async def cmd_scenarios(a):
    boot_app()
    from app import agent, llm, retrieval
    await load_passages(a.data)
    items, stats = [], defaultdict(int)
    for q0 in split(jl(a.data / "cases.jsonl"), a.split):
        if q0["answer_type"] != "strong":
            continue
        parent = add_question(q0)
        passages = await retrieval.evidence(USER, f"{parent['text']} {parent['concept']}")
        for v in range(2):
            try:
                res = await agent.scenario(USER, parent, "相当", [], passages)
                from app import db
                child = db.row("SELECT * FROM questions WHERE id=?", res["question_id"])
                stats["passed_checks"] += 1
                items.append({"case": f"{q0['id']}#{v}", "family": q0["family"], "domain": q0.get("domain", ""),
                              "condition": "scenario", "parent": parent["text"], "scenario": child["text"],
                              "context": child["context"], "eval_points": "；".join(child["eval_points"])})
            except llm.LLMError:
                stats["failed_checks"] += 1
    a.out.mkdir(parents=True, exist_ok=True)
    blind_sheet(a.out / "scenarios_rating.csv", items, ["parent", "scenario", "context", "eval_points"],
                ["concept_alignment", "answerability", "contextual_change", "difficulty", "reference_support"])
    print(dict(stats))
    usage(a.out)


# ── speech: transcription error + summary faithfulness ──────────────────

def _chars(t: str) -> str:
    return re.sub(r"[\W_]+", "", t).lower()  # drop punctuation/whitespace, compare characters


def cer(ref: str, hyp: str) -> float:
    """Character error rate = Levenshtein(ref, hyp) / len(ref) (Chinese is scored per character)."""
    r, h = _chars(ref), _chars(hyp)
    prev = list(range(len(h) + 1))
    for i, x in enumerate(r, 1):
        cur = [i]
        for j, y in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1] / max(len(r), 1)


async def cmd_asr(a):
    boot_app()
    from app import agent, llm
    recs = split(jl(a.data / "recordings.jsonl"), a.split)
    # same worker process the app uses (SenseVoice cannot share a process with onnxruntime + Milvus)
    w = subprocess.Popen([sys.executable, "-m", "app.asr_worker"], cwd=ROOT, text=True,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    w.stdout.readline()
    out, items = [], []
    for r in recs:
        t0 = time.perf_counter()
        w.stdin.write(str((a.data / r["audio"]).resolve()) + "\n")
        w.stdin.flush()
        hyp = json.loads(w.stdout.readline()).get("text", "")
        row = {"id": r["id"], "domain": r.get("domain", ""), "reference": r["transcript"], "asr": hyp,
               "cer": cer(r["transcript"], hyp), "asr_s": time.perf_counter() - t0}
        try:
            s = agent.reflect(USER, hyp, r.get("kind", "knowledge"))
            row.update(status="ok", summary=s.summary, key_points=s.key_points, weaknesses=s.weaknesses)
            items.append({"case": r["id"], "family": r["id"], "domain": row["domain"], "condition": "asr",
                          "reference_transcript": r["transcript"], "summary": s.summary,
                          "key_points": "；".join(s.key_points), "weaknesses": "；".join(s.weaknesses),
                          "key": {"cer": round(row["cer"], 4)}})
        except llm.LLMError as e:
            row.update(status="unavailable", error=str(e))
        out.append(row)
    w.stdin.close()
    w.wait()
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "asr_runs.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out))
    blind_sheet(a.out / "asr_rating.csv", items, ["reference_transcript", "summary", "key_points", "weaknesses"],
                ["faithful", "unsupported_claims", "missed_points", "weakness_supported"])
    for dom in ["all", *sorted({r["domain"] for r in out})]:
        rs = [r for r in out if dom in ("all", r["domain"])]
        print(f"{dom:<12} n={len(rs):>2}  CER={mean([r['cer'] for r in rs]):.3f}  "
              f"max={max(r['cer'] for r in rs):.3f}  asr {mean([r['asr_s'] for r in rs]):.1f}s/clip")
    usage(a.out)


# ── flashcards: evidence support + concept coverage ─────────────────────

async def cmd_cards(a):
    boot_app()
    from app import agent, llm, retrieval
    await load_passages(a.data)
    topics = list(dict.fromkeys(c["concept"] for c in split(jl(a.data / "cases.jsonl"), a.split) if c.get("concept")))
    rnd = random.Random(SEED)
    rnd.shuffle(topics)
    cards, items = [], []
    for t in topics:
        if len(cards) >= a.n:
            break
        passages = await retrieval.evidence(USER, t)
        try:
            for c in agent.gen_cards(USER, t, min(2, a.n - len(cards)), passages):
                c.update(topic=t, evidence="\n".join(f"[{p['eid']}] {p['content'][:300]}" for p in passages
                                                    if p["doc_id"] in c["sources"]))
                cards.append(c)
        except llm.LLMError:
            pass
    for i, c in enumerate(cards):
        items.append({"case": f"card{i}", "family": c["topic"], "condition": "generated", "topic": c["topic"],
                      "question": c["question"], "answer": c["answer"], "evidence": c["evidence"] or "（无引用）",
                      "key": {"n_sources": len(c["sources"])}})
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "cards_runs.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cards))
    blind_sheet(a.out / "cards_rating.csv", items, ["topic", "question", "answer", "evidence"],
                ["evidence_support", "concept_coverage", "factually_correct"])
    print(f"{len(cards)} cards from {len({c['topic'] for c in cards})} topics; "
          f"with >=1 cited reviewed source: {mean([bool(c['sources']) for c in cards]):.2f}")
    usage(a.out)


# ── stats ───────────────────────────────────────────────────────────────

def kappa(r1: list, r2: list) -> float:
    pairs = [(x, y) for x, y in zip(r1, r2) if x != "" and y != ""]
    if not pairs:
        return float("nan")
    cats = sorted({c for p in pairs for c in p})
    po = sum(x == y for x, y in pairs) / len(pairs)
    pe = sum((sum(x == c for x, _ in pairs) / len(pairs)) * (sum(y == c for _, y in pairs) / len(pairs)) for c in cats)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def cmd_stats(a):
    rows = list(csv.DictReader(open(a.sheet, encoding="utf-8")))
    key = {k["item"]: k for k in jl(Path(a.sheet).with_suffix(".key.jsonl"))}
    cols = sorted({c[:-3] for c in rows[0] if c.endswith("_r1")})
    print("pre-adjudication agreement (Cohen's kappa):")
    for c in cols:
        print(f"  {c:<20} {kappa([r[c + '_r1'] for r in rows], [r[c + '_r2'] for r in rows]):.2f}")
    def rated(r, col):
        vals = [float(r[f"{col}_{x}"]) for x in ("r1", "r2") if r.get(f"{col}_{x}", "") != ""]
        return sum(vals) / len(vals) if vals else None

    if "human_score" in cols:  # model rubric average vs mean human score (evaluator sheet)
        pairs = defaultdict(list)
        for r in rows:
            k, hs = key[int(r["item"])], rated(r, "human_score")
            if hs is not None and k.get("model_score") is not None:
                for g in ("all", k["condition"]):
                    pairs[g].append((k["model_score"], hs))
        for g, ps in sorted(pairs.items()):
            mae = mean([abs(m - h) for m, h in ps])
            bias = mean([m - h for m, h in ps])
            print(f"model vs human score [{g}]: MAE={mae:.2f}  bias(model-human)={bias:+.2f}  n={len(ps)}")
    if a.metric:
        by = defaultdict(list)
        for r in rows:
            k, v = key[int(r["item"])], rated(r, a.metric)
            if v is not None:
                for dom in {"all", k.get("domain") or "all"}:
                    by[(k["condition"], dom)].append(v)
        print(f"{a.metric} mean by condition / domain:")
        for (cond, dom), vs in sorted(by.items()):
            print(f"  {cond:<14} {dom:<12} {mean(vs):.2f}  n={len(vs)}")
    if not (a.metric and a.a and a.b):
        return
    # mean of the two raters per item, averaged per concept family and condition
    fam = defaultdict(lambda: defaultdict(list))
    for r in rows:
        k = key[int(r["item"])]
        vals = [float(r[f"{a.metric}_{x}"]) for x in ("r1", "r2") if r[f"{a.metric}_{x}"] != ""]
        if vals:
            fam[k["family"]][k["condition"]].append(sum(vals) / len(vals))
    diffs = [mean(v[a.b]) - mean(v[a.a]) for v in fam.values() if v[a.a] and v[a.b]]
    rnd = random.Random(SEED)
    boots = sorted(mean([rnd.choice(diffs) for _ in diffs]) for _ in range(a.n_boot))
    lo, hi = boots[int(0.025 * a.n_boot)], boots[int(0.975 * a.n_boot) - 1]
    print(f"{a.metric}: {a.b} - {a.a} = {mean(diffs):.3f}  95% CI [{lo:.3f}, {hi:.3f}]  ({len(diffs)} families)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("retrieval", "evaluator", "hints", "history", "scenarios", "asr", "cards"):
        s = sub.add_parser(name)
        s.add_argument("--data", type=Path, default=ROOT / "eval" / "sample")
        s.add_argument("--out", type=Path, default=ROOT / "eval" / "results")
        s.add_argument("--split", default=None, help="dev | test (default: all rows)")
        s.add_argument("--k", type=int, default=3)
        s.add_argument("--conditions", default="weighted,none", help="evaluator: evidence modes to compare")
        s.add_argument("--subset", type=int, default=40, help="evaluator: size of the balanced blind subset")
        s.add_argument("--subset-file", help="evaluator: fixed list of case ids for the blind subset")
        s.add_argument("--n", type=int, default=20, help="cards: number of cards to generate")
    s = sub.add_parser("stats")
    s.add_argument("sheet")
    s.add_argument("--metric")
    s.add_argument("--a", help="baseline condition")
    s.add_argument("--b", help="treatment condition")
    s.add_argument("--n-boot", type=int, default=10000)
    a = p.parse_args()
    if a.cmd == "stats":
        return cmd_stats(a)
    asyncio.run(globals()[f"cmd_{a.cmd}"](a))


if __name__ == "__main__":
    main()
