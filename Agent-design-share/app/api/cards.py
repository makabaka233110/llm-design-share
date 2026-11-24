"""Flashcards: CRUD, collections, CSV import/export, due queue, SM-2 / fixed scheduling, AI generation."""

import csv
import io
import os
from typing import Literal

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import agent, db, retrieval, srs
from app.api import User, call

router = APIRouter(prefix="/api/cards", tags=["cards"])
DEFAULT_POLICY = os.getenv("SRS_POLICY", "sm2")


class CardIn(BaseModel):
    question: str
    answer: str
    collection: str = "General"
    policy: Literal["sm2", "fixed"] | None = None
    domain_id: int | None = None
    gap_id: int | None = None
    question_id: int | None = None
    sources: list[int] = []


class CardPatch(BaseModel):
    question: str | None = None
    answer: str | None = None
    collection: str | None = None


class RateIn(BaseModel):
    rating: Literal["again", "hard", "good", "easy", "retire"]
    user_answer: str = ""


class GenerateIn(BaseModel):
    topic: str
    count: int = 5
    collection: str = "AI生成"
    domain_id: int | None = None


def _add(user: str, c: CardIn) -> dict:
    fields = c.model_dump()
    fields["policy"] = c.policy or DEFAULT_POLICY
    cid = db.insert("cards", user_id=user, due_at=db.now(), **fields)
    return db.owned("cards", cid, user)


@router.get("")
def list_cards(user: User, collection: str | None = None, status: str | None = None):
    sql, args = "SELECT * FROM cards WHERE user_id=?", [user]
    for col, v in (("collection", collection), ("status", status)):
        if v:
            sql += f" AND {col}=?"
            args.append(v)
    return db.rows(sql + " ORDER BY id DESC", *args)


@router.post("")
def create(c: CardIn, user: User):
    return _add(user, c)


@router.put("/{cid}")
def edit(cid: int, p: CardPatch, user: User):
    db.owned("cards", cid, user)
    if fields := p.model_dump(exclude_unset=True, exclude_none=True):
        db.update("cards", cid, **fields)
    return db.owned("cards", cid, user)


@router.delete("/{cid}")
def delete(cid: int, user: User):
    db.owned("cards", cid, user)
    db.run("DELETE FROM reviews WHERE card_id=?", cid)
    db.run("DELETE FROM cards WHERE id=?", cid)
    return {"ok": True}


@router.delete("/collections/{name}")
def delete_collection(name: str, user: User):
    db.run("DELETE FROM reviews WHERE card_id IN (SELECT id FROM cards WHERE user_id=? AND collection=?)", user, name)
    db.run("DELETE FROM cards WHERE user_id=? AND collection=?", user, name)
    return {"ok": True}


@router.get("/due")
def due(user: User, collection: str | None = None):
    sql, args = "SELECT * FROM cards WHERE user_id=? AND status='learning' AND due_at<=?", [user, db.now()]
    if collection:
        sql += " AND collection=?"
        args.append(collection)
    return db.rows(sql + " ORDER BY due_at", *args)


@router.post("/{cid}/rate")
def rate(cid: int, r: RateIn, user: User):
    card = db.owned("cards", cid, user)
    db.update("cards", cid, **srs.schedule(card, r.rating))
    db.insert("reviews", card_id=cid, rating=r.rating, user_answer=r.user_answer)
    return db.owned("cards", cid, user)


@router.get("/stats")
def stats(user: User):
    s = db.row("""SELECT COUNT(*) total, SUM(status='learning') learning, SUM(status='retired') retired,
                    SUM(status='learning' AND due_at<=?) due FROM cards WHERE user_id=?""", db.now(), user)
    s["collections"] = db.rows("SELECT collection, COUNT(*) n FROM cards WHERE user_id=? GROUP BY collection", user)
    s["reviews_7d"] = db.row("""SELECT COUNT(*) n FROM reviews r JOIN cards c ON c.id=r.card_id
                                WHERE c.user_id=? AND r.created_at>=strftime('%Y-%m-%dT%H:%M:%S', 'now', '-7 days')""", user)["n"]
    return s


@router.post("/import")
async def import_csv(file: UploadFile, user: User, collection: str = "Imported"):
    """CSV rows: question,answer[,collection] (same format as the old Memento export)."""
    n = 0
    for row in csv.reader(io.StringIO((await file.read()).decode("utf-8-sig"))):
        if len(row) >= 2 and row[0].strip() and row[1].strip():
            col = row[2].strip() if len(row) > 2 and row[2].strip() else collection
            _add(user, CardIn(question=row[0].strip(), answer=row[1].strip(), collection=col))
            n += 1
    return {"imported": n}


@router.get("/export")
def export_csv(user: User):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for c in db.rows("SELECT question, answer, collection FROM cards WHERE user_id=?", user):
        w.writerow([c["question"], c["answer"], c["collection"]])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=flashcards.csv"})


@router.post("/generate")
async def generate(g: GenerateIn, user: User):
    passages = await retrieval.evidence(user, g.topic, k=5, domain_id=g.domain_id)
    if not passages:
        raise HTTPException(404, f"知识库中没有与「{g.topic}」相关的已审核资料")
    items = await call(agent.gen_cards, user, g.topic, g.count, passages)
    return [_add(user, CardIn(collection=g.collection, domain_id=g.domain_id, **c)) for c in items]
