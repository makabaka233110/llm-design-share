"""Reference store: Markdown docs indexed by Memsearch (bge-m3 ONNX + Milvus Lite).

One `retrieve()` serves the UI, the evaluator, hints, cards and the experiments.
Modes: bm25 | dense | hybrid (Memsearch RRF) | weighted (proposal eq. 1):
    final_score = hybrid_score * (1 + 0.1 * priority),  priority in [0, 5]
Priority is read from the `docs` table per source file, so every chunk of a doc
gets it (the old code parsed it from chunk text, which only the header chunk had).
"""

import asyncio
import re
from pathlib import Path

from app import db

WEIGHT = 0.1
P_MIN, P_MAX, P_DEFAULT = 0.0, 5.0, 2.0
FEEDBACK_DELTA = {True: 0.5, False: -1.0}
MODES = ("bm25", "dense", "hybrid", "weighted")
RRF_K = 60  # Memsearch's fixed RRF constant; hybrid scores are normalised by 2/(k+1)

_mem = None
_lock = asyncio.Lock()


def mem():
    global _mem
    if _mem is None:
        from memsearch import MemSearch
        _mem = MemSearch(paths=[str(db.KB_DIR)], embedding_provider="onnx",
                         milvus_uri=str(db.DATA_DIR / "milvus.db"), collection="mianbi")
        _create_collection(_mem.store, _mem._embedder.dimension)
    return _mem


def _create_collection(store, dim: int) -> None:
    """Memsearch's schema, but BM25 tokenises with jieba: the default `standard`
    analyzer does not segment Chinese, so Chinese queries got no BM25 matches at all."""
    from pymilvus import DataType, Function, FunctionType
    store._connect(create_local_storage=True)
    client = store._connected_client()
    if client.has_collection(store._collection):
        return
    s = client.create_schema(enable_dynamic_field=True)
    s.add_field("chunk_hash", DataType.VARCHAR, max_length=64, is_primary=True)
    s.add_field("embedding", DataType.FLOAT_VECTOR, dim=dim)
    s.add_field("content", DataType.VARCHAR, max_length=65535, enable_analyzer=True,
                analyzer_params={"tokenizer": "jieba"})
    s.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)
    for f in ("source", "heading"):
        s.add_field(f, DataType.VARCHAR, max_length=1024)
    for f in ("heading_level", "start_line", "end_line"):
        s.add_field(f, DataType.INT64)
    s.add_function(Function(name="bm25_fn", function_type=FunctionType.BM25,
                            input_field_names=["content"], output_field_names=["sparse_vector"]))
    idx = client.prepare_index_params()
    idx.add_index(field_name="embedding", index_type="FLAT", metric_type="COSINE")
    idx.add_index(field_name="sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
    client.create_collection(store._collection, schema=s, index_params=idx)
    store._ensure_collection(create_if_missing=False)


def doc_path(doc_id: int) -> Path:
    return (db.KB_DIR / f"{doc_id}.md").resolve()


# ── docs ────────────────────────────────────────────────────────────────

QUESTION_HINTS = ("什么", "为什么", "怎么", "如何", "区别", "原理", "流程", "场景", "优缺点",
                  "讲一下", "介绍一下", "说一下", "能不能", "是否", "吗", "呢")


def structure(text: str) -> str:
    """Turn un-headed interview notes into `## question` sections for finer chunks."""
    if re.search(r"^#{1,6}\s", text, re.M):
        return text
    out, hit = [], False
    for line in text.splitlines():
        q = re.sub(r"^\s*(?:[-*+]\s+|(?:\d+|[一二三四五六七八九十]+)[、.)．]\s*)", "", line)
        q = re.sub(r"^\s*(?:Q|q|问|问题|面试官)\s*[:：]\s*", "", q).strip()
        if q and len(q) <= 120 and (q.endswith(("?", "？")) or any(h in q for h in QUESTION_HINTS)):
            out += ["", f"## {q}", ""]
            hit = True
        else:
            out.append(line)
    return "\n".join(out).strip() if hit else text


def read_body(doc_id: int) -> str:
    p = doc_path(doc_id)
    return p.read_text(encoding="utf-8").split("\n", 2)[-1].lstrip("\n") if p.exists() else ""


async def write_doc(doc_id: int, title: str, body: str) -> None:
    p = doc_path(doc_id)
    p.write_text(f"# {title}\n\n{body.strip()}\n", encoding="utf-8")
    async with _lock:
        await mem().index_file(p)


async def remove_doc(doc_id: int) -> None:
    p = doc_path(doc_id)
    p.unlink(missing_ok=True)
    async with _lock:
        try:
            mem().store.delete_by_source(str(p))
        except Exception:
            pass


async def reindex() -> int:
    async with _lock:
        return await mem().index()


def apply_feedback(doc: dict, helpful: bool) -> float:
    p = min(P_MAX, max(P_MIN, doc["priority"] + FEEDBACK_DELTA[helpful]))
    db.update("docs", doc["id"], priority=p, updated_at=db.now())
    return p


# ── search ──────────────────────────────────────────────────────────────

def _search(mode: str, query: str, vec, limit: int, expr: str) -> list[dict]:
    from pymilvus import AnnSearchRequest, RRFRanker
    store = mem().store
    try:
        store._require_collection()
    except Exception:
        return []
    if store._collection_is_empty():
        return []
    client, coll, fields = store._connected_client(), store._collection, store._QUERY_FIELDS
    if mode == "bm25":
        res = client.search(coll, data=[query], anns_field="sparse_vector", limit=limit, filter=expr,
                            search_params={"metric_type": "BM25"}, output_fields=fields)
        # Milvus Lite reports BM25 as a negative distance (best first); the magnitude is the BM25 score.
        return [{**h["entity"], "score": abs(h["distance"])} for h in res[0]]
    if mode == "dense":
        res = client.search(coll, data=[vec], anns_field="embedding", limit=limit, filter=expr,
                            search_params={"metric_type": "COSINE"}, output_fields=fields)
        return [{**h["entity"], "score": h["distance"]} for h in res[0]]
    reqs = [AnnSearchRequest([vec], "embedding", {"metric_type": "COSINE"}, limit, expr=expr),
            AnnSearchRequest([query], "sparse_vector", {"metric_type": "BM25"}, limit, expr=expr)]
    res = client.hybrid_search(coll, reqs, RRFRanker(k=RRF_K), limit=limit, output_fields=fields)
    norm = 2 / (RRF_K + 1)
    return [{**h["entity"], "score": h["distance"] / norm} for h in res[0]]


async def retrieve(user: str, query: str, k: int = 3, mode: str = "weighted", *,
                   reviewed_only: bool = False, domain_id: int | None = None) -> list[dict]:
    """Top-k passages from the user's own docs.

    For `weighted`, the candidate pool doubles until no chunk outside it could
    reach the top k: an unseen chunk scores at most the pool's lowest hybrid
    score, so its final score is at most that x (1 + 0.1 x 5).
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    sql, args = "SELECT * FROM docs WHERE user_id=?", [user]
    if reviewed_only:
        sql += " AND reviewed=1"
    if domain_id:
        sql += " AND (domain_id=? OR domain_id IS NULL)"  # untagged docs apply to every domain
        args.append(domain_id)
    docs = {str(doc_path(d["id"])): d for d in db.rows(sql, *args)}
    if not docs or not query.strip():
        return []
    expr = "source in [" + ",".join(f'"{s}"' for s in docs) + "]"
    vec = None if mode == "bm25" else (await mem()._embedder.embed([query]))[0]

    pool = k
    while True:
        hits = await asyncio.to_thread(_search, mode, query, vec, pool, expr)
        for h in hits:
            d = docs[h["source"]]
            h.update(doc_id=d["id"], title=d["title"], topic=d["topic"], version=d["version"],
                     reviewed=bool(d["reviewed"]), priority=d["priority"], id=h["chunk_hash"],
                     base_score=round(h["score"], 4))
            boost = 1 + WEIGHT * d["priority"] if mode == "weighted" else 1.0
            h["final_score"] = round(h["score"] * boost, 4)
        hits.sort(key=lambda h: h["final_score"], reverse=True)  # stable: equal scores keep order
        if mode != "weighted" or len(hits) < pool:
            break
        floor = min(h["base_score"] for h in hits) * (1 + WEIGHT * P_MAX)
        if floor < hits[k - 1]["final_score"]:
            break
        pool *= 2
    return hits[:k]


def claims(answer: str) -> list[str]:
    """Split an answer into sentence-level claims (rule-based, no model call)."""
    parts = re.split(r"[。！？!?；;\n]+", answer)
    return [c.strip() for c in parts if re.search(r"\w", c)]


async def evidence(user: str, question: str, answer: str = "", k: int = 3, mode: str = "weighted",
                   domain_id: int | None = None) -> list[dict]:
    """Evaluator evidence (reviewed docs only; generated or unreviewed text never scores answers).

    1. Start from the question + concept: top-k reranked passages (E1..Ek).
    2. Check specific claims: for every sentence of the answer, its best passage is added
       (E{k+1}..) unless already present, labelled with the claim it was retrieved for.
    """
    top = await retrieve(user, question, k, mode, reviewed_only=True, domain_id=domain_id)
    seen = {h["id"] for h in top}
    for claim in claims(answer):
        for h in await retrieve(user, claim, 1, mode, reviewed_only=True, domain_id=domain_id):
            if h["id"] not in seen:
                seen.add(h["id"])
                top.append({**h, "claim": claim})
    for i, h in enumerate(top, 1):
        h["eid"] = f"E{i}"
    return top


def cite(passages: list[dict]) -> list[dict]:
    """Snapshot of evidence stored with an evaluation (traceable even if the doc changes later)."""
    return [{"eid": p["eid"], "chunk": p["id"], "doc_id": p["doc_id"], "version": p["version"],
             "title": p["title"], "heading": p["heading"], "snippet": p["content"][:300],
             "final_score": p["final_score"], "claim": p.get("claim", "")} for p in passages]


# ── related questions (question bank; context only, never scoring evidence) ──

_qvec: dict[str, list[float]] = {}


async def related_questions(user: str, text: str, exclude: set[int], k: int = 3) -> list[dict]:
    """Nearest questions in the learner's bank by bge-m3 cosine similarity."""
    qs = [q for q in db.rows("SELECT id, text, concept, origin, parent_id FROM questions WHERE user_id=?", user)
          if q["id"] not in exclude]
    if not qs:
        return []
    missing = [t for t in {text, *(q["text"] for q in qs)} if t not in _qvec]
    if missing:
        for t, v in zip(missing, await mem()._embedder.embed(missing)):
            _qvec[t] = v
    base = _qvec[text]
    for q in qs:
        q["similarity"] = round(sum(a * b for a, b in zip(base, _qvec[q["text"]])), 3)  # bge-m3 vectors are unit-norm
    return sorted(qs, key=lambda q: q["similarity"], reverse=True)[:k]


def as_context(passages: list[dict]) -> str:
    # Chunks are already capped by Memsearch (max_chunk_size=1500), so pass them whole.
    return "\n\n".join(f"[{p.get('eid', i)}] {p['title']} / {p['heading']}"
                       + (f"（用于核对：「{p['claim']}」）" if p.get("claim") else "") + f"\n{p['content']}"
                       for i, p in enumerate(passages, 1)) or "（无参考资料）"
