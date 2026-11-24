"""Learner settings: domains (materials, goals, criteria), usage/cost log, personal-data deletion."""

from fastapi import APIRouter
from pydantic import BaseModel

from app import db, llm, retrieval
from app.api import User

router = APIRouter(prefix="/api", tags=["me"])


class DomainIn(BaseModel):
    name: str
    goals: str = ""
    criteria: str = ""


@router.get("/domains")
def list_domains(user: User):
    return db.rows("SELECT * FROM domains WHERE user_id=? ORDER BY id", user)


@router.post("/domains")
def create_domain(d: DomainIn, user: User):
    return db.owned("domains", db.insert("domains", user_id=user, **d.model_dump()), user)


@router.put("/domains/{did}")
def update_domain(did: int, d: DomainIn, user: User):
    db.owned("domains", did, user)
    db.update("domains", did, **d.model_dump())
    return db.owned("domains", did, user)


@router.delete("/domains/{did}")
def delete_domain(did: int, user: User):
    db.owned("domains", did, user)
    db.run("DELETE FROM domains WHERE id=?", did)
    return {"ok": True}


@router.get("/usage")
def usage(user: User):
    """API calls, tokens, latency and failure rate per task (proposal §4: operational cost)."""
    rs = db.rows("""SELECT task, COUNT(*) calls, SUM(ok=0) failures, SUM(tokens_in) tokens_in,
                      SUM(tokens_out) tokens_out, CAST(AVG(ms) AS INT) avg_ms
                    FROM llm_log WHERE user_id=? GROUP BY task ORDER BY calls DESC""", user)
    for r in rs:
        r["cost_usd"] = llm.cost(r["tokens_in"], r["tokens_out"])
    return rs


@router.delete("/me")
async def delete_me(user: User):
    for d in db.rows("SELECT id FROM docs WHERE user_id=?", user):
        await retrieval.remove_doc(d["id"])
    db.delete_user(user)
    return {"ok": True, "deleted_user": user}
