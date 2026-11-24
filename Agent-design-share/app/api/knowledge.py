"""Reference store: docs CRUD, search (4 modes), useful/not-useful feedback."""

import time

from fastapi import APIRouter
from pydantic import BaseModel

from app import db, retrieval
from app.api import User

router = APIRouter(prefix="/api/kb", tags=["knowledge"])


class DocIn(BaseModel):
    title: str
    body: str
    topic: str = ""
    source: str = "用户粘贴"
    priority: float = retrieval.P_DEFAULT
    reviewed: bool = True
    domain_id: int | None = None
    structure: bool = True


class DocPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    topic: str | None = None
    source: str | None = None
    priority: float | None = None
    reviewed: bool | None = None
    domain_id: int | None = None


class SearchIn(BaseModel):
    query: str
    k: int = 5
    mode: str = "weighted"
    reviewed_only: bool = False
    domain_id: int | None = None


class FeedbackIn(BaseModel):
    doc_id: int
    helpful: bool


def _clamp(p: float) -> float:
    return min(retrieval.P_MAX, max(retrieval.P_MIN, p))


@router.get("/docs")
def list_docs(user: User, domain_id: int | None = None):
    sql, args = "SELECT * FROM docs WHERE user_id=?", [user]
    if domain_id:
        sql += " AND domain_id=?"
        args.append(domain_id)
    return db.rows(sql + " ORDER BY updated_at DESC", *args)


@router.post("/docs")
async def create_doc(d: DocIn, user: User):
    body = retrieval.structure(d.body) if d.structure else d.body
    did = db.insert("docs", user_id=user, domain_id=d.domain_id, title=d.title, topic=d.topic, source=d.source,
                    priority=_clamp(d.priority), reviewed=int(d.reviewed), updated_at=db.now())
    await retrieval.write_doc(did, d.title, body)
    return {**db.owned("docs", did, user), "auto_structured": body != d.body}


@router.get("/docs/{doc_id}")
def get_doc(doc_id: int, user: User):
    return {**db.owned("docs", doc_id, user), "body": retrieval.read_body(doc_id)}


@router.put("/docs/{doc_id}")
async def update_doc(doc_id: int, p: DocPatch, user: User):
    doc = db.owned("docs", doc_id, user)
    fields = p.model_dump(exclude_unset=True, exclude={"body"})
    if "priority" in fields:
        fields["priority"] = _clamp(fields["priority"])
    if "reviewed" in fields:
        fields["reviewed"] = int(fields["reviewed"])
    if p.body is not None or p.title is not None:  # content change -> new version, re-index
        fields["version"] = doc["version"] + 1
        await retrieval.write_doc(doc_id, p.title or doc["title"],
                                  p.body if p.body is not None else retrieval.read_body(doc_id))
    db.update("docs", doc_id, **fields, updated_at=db.now())
    return db.owned("docs", doc_id, user)


@router.delete("/docs/{doc_id}")
async def delete_doc(doc_id: int, user: User):
    db.owned("docs", doc_id, user)
    await retrieval.remove_doc(doc_id)
    db.run("DELETE FROM docs WHERE id=?", doc_id)
    return {"ok": True}


@router.post("/search")
async def search(s: SearchIn, user: User):
    t0 = time.perf_counter()
    hits = await retrieval.retrieve(user, s.query, s.k, s.mode, reviewed_only=s.reviewed_only,
                                    domain_id=s.domain_id)
    return {"results": hits, "mode": s.mode, "ms": round((time.perf_counter() - t0) * 1000, 1)}


@router.post("/feedback")
def feedback(f: FeedbackIn, user: User):
    doc = db.owned("docs", f.doc_id, user)
    return {"doc_id": f.doc_id, "old_priority": doc["priority"], "new_priority": retrieval.apply_feedback(doc, f.helpful)}


@router.post("/reindex")
async def reindex():
    return {"chunks_indexed": await retrieval.reindex()}
