"""End-to-end API test: real retrieval (bge-m3 ONNX + Milvus Lite), scripted fake LLM.

Run: .venv/bin/python -m pytest -q tests
"""

import json
import os
import tempfile
from datetime import datetime, timezone

os.environ["MIANBI_DATA"] = tempfile.mkdtemp(prefix="mianbi-test-")
os.environ["LLM_API_KEY"] = "test"
os.environ["LLM_MODEL"] = "fake-model"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import llm, srs  # noqa: E402
from app.main import app  # noqa: E402

PROMPTS: list[str] = []
BROKEN = {"on": False}


llm._orig_complete = llm.complete


def fake_complete(system, messages, max_tokens):
    p = messages[0]["content"]
    PROMPTS.append(p)
    if BROKEN["on"]:
        return "not json", 1, 1
    if "## 学习者回答" in p:
        answer = p.split("## 学习者回答")[1].split("\n", 1)[1].split("\n\n")[0]
        out = {"status": "ok", "scores": {"correctness": 4, "coverage": 3, "reasoning": 3, "clarity": 4},
               "strengths": [{"text": "提到 RDB", "quote": answer[:4], "evidence": ["E1", "E9"]}],
               "omissions": [{"text": "没讲 AOF 重写", "quote": "编造的话", "evidence": []}],
               "misconceptions": [], "revisions": ["补充 AOF"], "recurring": [], "resolved": []}
    elif '"action"' in p:
        out = {"action": "follow_up", "question": f"追问{len(PROMPTS)}：AOF 怎么重写？", "concept": "Redis 持久化"}
    elif "转写稿" in p:
        out = {"summary": "讲了持久化", "key_points": ["RDB"], "weaknesses": ["AOF 不熟"], "improvements": ["复习"]}
    elif "设计一道新的情境题" in p:
        out = {"question": "一个计数服务每秒写 1 万次，宕机最多丢 1 秒数据，怎么配置持久化？",
               "context": "写多读少，磁盘一般", "eval_points": ["选 AOF everysec"], "concept": "Redis 持久化"}
    elif "判断：1)" in p:
        out = {"concept_aligned": True, "answerable": True, "duplicate_of": None, "reason": ""}
    elif "改写成一道让学习者" in p:
        out = {"question": "请讲清楚 AOF 重写的作用和过程", "concept": "Redis 持久化"}
    elif "闪卡" in p:
        out = {"cards": [{"question": "AOF 重写做什么？", "answer": "压缩日志", "evidence": ["E1"]}]}
    elif "给一条提示" in p:
        return "想想宕机时会丢多少数据。", 10, 5
    elif "归纳该学习者" in p:
        return "- 只给思考方向，不要给结论", 10, 5
    else:
        return "整体不错。", 10, 5
    return json.dumps(out, ensure_ascii=False), 10, 5


@pytest.fixture(scope="module")
def c():
    llm.complete = fake_complete
    with TestClient(app) as client:
        client.headers["X-User"] = "alice"
        yield client


def test_knowledge_and_retrieval(c):
    d = c.post("/api/domains", json={"name": "计算机", "goals": "后端面试", "criteria": "重视原理"}).json()
    r = c.post("/api/kb/docs", json={"title": "Redis 笔记", "domain_id": d["id"], "reviewed": True,
                                      "body": "Redis 持久化有哪些方式？\nRDB 快照，AOF 追加日志，AOF 重写压缩日志。\n"
                                              "为什么 TCP 要三次握手？\n同步序列号，防止历史连接。"}).json()
    assert r["auto_structured"] and r["priority"] == 2
    c.post("/api/kb/docs", json={"title": "机会成本", "body": "选择一项时放弃的次优选择的价值。", "topic": "经济学", "reviewed": True})
    pasted = c.post("/api/kb/docs", json={"title": "未审核面经", "body": "Redis 持久化只有 RDB。"}).json()
    assert pasted["reviewed"] == 0                     # pasted material is not ground truth by default
    for mode in ("bm25", "dense", "hybrid", "weighted"):
        hits = c.post("/api/kb/search", json={"query": "Redis 持久化", "mode": mode}).json()["results"]
        assert hits and "Redis" in hits[0]["content"], mode
    # weighted = hybrid x (1 + 0.1 p): with p=2 every final score is 1.2x the base score
    h = c.post("/api/kb/search", json={"query": "Redis 持久化", "mode": "weighted"}).json()["results"][0]
    assert h["final_score"] == pytest.approx(h["base_score"] * (1 + 0.1 * h["priority"]), abs=1e-3)
    # review filter + isolation
    hits = c.post("/api/kb/search", json={"query": "Redis", "reviewed_only": True, "k": 10}).json()["results"]
    assert all(x["reviewed"] for x in hits)
    assert c.post("/api/kb/search", json={"query": "Redis"}, headers={"X-User": "bob"}).json()["results"] == []
    # feedback: +0.5 / -1, clamped to [0, 5]; every chunk of the doc sees the new priority
    assert c.post("/api/kb/feedback", json={"doc_id": r["id"], "helpful": False}).json()["new_priority"] == 1.0
    for _ in range(3):
        last = c.post("/api/kb/feedback", json={"doc_id": r["id"], "helpful": False}).json()
    assert last["new_priority"] == 0
    hits = c.post("/api/kb/search", json={"query": "TCP 三次握手", "k": 10}).json()["results"]
    assert all(x["priority"] == 0 for x in hits if x["doc_id"] == r["id"])
    # edit bumps version
    e = c.put(f"/api/kb/docs/{r['id']}", json={"body": "## Redis 持久化\nRDB 与 AOF，AOF 重写压缩日志。", "priority": 3}).json()
    assert e["version"] == 2 and e["priority"] == 3


def test_feynman_history_and_evaluation(c):
    q = c.post("/api/questions", json={"text": "Redis 有哪些持久化方式？", "concept": "Redis 持久化"}).json()
    r1 = c.post(f"/api/questions/{q['id']}/attempts", json={"answer": "RDB 快照"}).json()
    ev = r1["evaluation"]
    assert ev["status"] == "ok" and ev["rubric_version"] == "r1+calc" and 1 <= len(ev["evidence"]) <= 3
    assert ev["feedback"]["strengths"][0]["evidence"] == ["E1"]      # unknown id E9 dropped
    assert ev["feedback"]["omissions"][0]["quote"] == ""              # invented quote dropped
    r2 = c.post(f"/api/questions/{q['id']}/attempts", json={"answer": "RDB 和 AOF"}).json()
    assert r2["attempt"]["version"] == 2 and "## 历史作答" in PROMPTS[-1] and "没讲 AOF 重写" in PROMPTS[-1]
    c.post(f"/api/questions/{q['id']}/attempts", json={"answer": "RDB", "history_aware": False})
    assert "## 历史作答" not in PROMPTS[-1]
    detail = c.get(f"/api/questions/{q['id']}").json()
    assert [a["answer"] for a in detail["attempts"]] == ["RDB 快照", "RDB 和 AOF", "RDB"]  # originals unchanged
    # no reviewed evidence -> explicit uncertain, no invented score
    qb = c.post("/api/questions", json={"text": "什么是 CAP？"}, headers={"X-User": "bob"}).json()
    rb = c.post(f"/api/questions/{qb['id']}/attempts", json={"answer": "一致性"}, headers={"X-User": "bob"}).json()
    assert rb["evaluation"]["status"] == "uncertain" and rb["evaluation"]["scores"] is None
    # invalid model output after the corrective retry -> unavailable
    BROKEN["on"] = True
    ru = c.post(f"/api/questions/{q['id']}/attempts", json={"answer": "x"}).json()
    BROKEN["on"] = False
    assert ru["evaluation"]["status"] == "unavailable" and ru["evaluation"]["scores"] is None
    # cross-user access is blocked
    assert c.get(f"/api/questions/{q['id']}", headers={"X-User": "bob"}).status_code == 404


def test_hints_and_preferences(c):
    q = c.post("/api/questions", json={"text": "AOF 重写的原理？", "concept": "Redis 持久化"}).json()
    h = c.post(f"/api/questions/{q['id']}/hint", json={}).json()
    assert h["pref_version"] == 0
    p = c.post(f"/api/hints/{h['id']}/feedback", json={"feedback": "too_direct", "comment": "直接给了答案"}).json()
    assert p["prefs"]["version"] == 1 and "思考方向" in p["prefs"]["summary"]
    h2 = c.post(f"/api/questions/{q['id']}/hint", json={}).json()
    assert h2["pref_version"] == 1 and h2["used_feedback"] == 1 and "只给思考方向" in PROMPTS[-1]
    c.post(f"/api/questions/{q['id']}/hint", json={"personalized": False})
    assert "提示偏好" not in PROMPTS[-1]
    assert c.put("/api/prefs", json={"summary": "简短"}).json()["version"] == 2
    reset = c.post("/api/prefs/reset").json()
    assert reset["summary"] == "" and reset["source"] == "reset"
    h3 = c.post(f"/api/questions/{q['id']}/hint", json={}).json()
    assert h3["used_feedback"] == 0                               # pre-reset feedback no longer used
    assert len(c.get("/api/prefs").json()["feedback"]) == 1       # but stays traceable


def test_scenario_links_to_parent(c):
    q = c.post("/api/questions", json={"text": "Redis 持久化有哪些方式？", "concept": "Redis 持久化"}).json()
    s = c.post(f"/api/questions/{q['id']}/scenario", json={"difficulty": "更难"}).json()
    child = s["question"]
    assert child["parent_id"] == q["id"] and child["origin"] == "scenario" and "eval_points" not in child
    r = c.post(f"/api/questions/{child['id']}/attempts", json={"answer": "用 AOF everysec"}).json()
    assert "选 AOF everysec" in PROMPTS[-1] and r["attempt"]["mode"] == "scenario"
    assert c.get(f"/api/questions/{child['id']}").json()["eval_points"] == ["选 AOF everysec"]
    assert c.get(f"/api/questions/{q['id']}").json()["children"][0]["id"] == child["id"]


def test_interview_flow(c):
    s = c.post("/api/interview/start", json={"kind": "knowledge", "role": "后端"}).json()
    for i in range(3):
        r = c.post(f"/api/interview/{s['session_id']}/answer", json={"answer": f"RDB 回答{i}"}).json()
        assert r["evaluation"]["status"] == "ok"
    assert r["action"] == "next"   # model kept asking to follow up; capped at MAX_FOLLOW_UPS
    end = c.post(f"/api/interview/{s['session_id']}/end").json()
    assert end["finished"] and end["gaps"] and len(end["turns"]) == 7
    assert c.get("/api/questions?origin=interview").json()
    assert c.get("/api/interview/sessions").json()[0]["avg_score"] == pytest.approx(3.5)


def test_reflection_gap_card(c):
    a = c.post("/api/speech/reflect", json={"transcript": "我讲了 RDB，没讲 AOF"}).json()
    rec = c.post("/api/reflections", json={"transcript": "我讲了 RDB，没讲 AOF", "analysis": a}).json()
    gap = [g for g in c.get("/api/gaps?confirmed=false").json() if g["origin"] == "reflection"][0]
    assert gap["origin_id"] == rec["id"]
    assert c.post(f"/api/gaps/{gap['id']}/card-draft").status_code == 400   # must confirm first
    c.put(f"/api/gaps/{gap['id']}", json={"confirmed": True})
    draft = c.post(f"/api/gaps/{gap['id']}/card-draft").json()
    card = c.post("/api/cards", json={**draft, "answer": draft["answer"] + "（已编辑）"}).json()
    assert card["gap_id"] == gap["id"] and card["sources"]


def test_claims_concepts_related_gap_practice(c):
    from app import retrieval
    assert retrieval.claims("RDB 是快照。AOF 记录写命令！\n好") == ["RDB 是快照", "AOF 记录写命令", "好"]
    for title, body in (("TCP 四次挥手", "TCP 断开连接需要四次挥手，TIME_WAIT 持续 2MSL。"),
                        ("UDP", "UDP 无连接、不保证可靠，开销小。"),
                        ("TCP 拥塞控制", "TCP 通过慢启动和拥塞避免调整发送窗口。")):
        c.post("/api/kb/docs", json={"title": title, "body": body, "reviewed": True})
    q = c.post("/api/questions", json={"text": "为什么 TCP 要三次握手？", "concept": "TCP 握手"}).json()
    r = c.post(f"/api/questions/{q['id']}/attempts",
               json={"answer": "为了同步双方的序列号。另外机会成本是放弃的次优选择的价值。"}).json()
    ev = r["evaluation"]["evidence"]
    claimed = [e for e in ev if e["claim"]]
    # question passages first (at most 3, off-topic ones dropped), then one passage per claim, labelled with it
    n_q = len(ev) - len(claimed)
    assert claimed and 1 <= n_q <= 3 and all(int(e["eid"][1:]) > n_q for e in claimed)
    assert all(e["title"] != "UDP" for e in ev)  # retrieved for the question, but off-topic: not shown
    assert any(e["title"] == "机会成本" and "机会成本" in e["claim"] for e in claimed)
    assert "用于核对" in PROMPTS[-1] and "## 题库中的相关问题" in PROMPTS[-1]
    # concept view: original question and its scenario are grouped, weakest concept first
    groups = {g["concept"]: g for g in c.get("/api/concepts").json()}
    redis = groups["Redis 持久化"]
    assert {"manual", "scenario"} <= {x["origin"] for x in redis["questions"]} and redis["avg"] == 3.5
    detail = c.get(f"/api/questions/{q['id']}").json()
    assert detail["concept_family"][0]["id"] == q["id"] and detail["related"]
    # confirmed gap -> practice question (linked back), second call reuses it
    gap = c.post("/api/gaps", json={"text": "AOF 重写讲不清"}).json()
    qid = c.post(f"/api/gaps/{gap['id']}/practice").json()["question_id"]
    assert c.get(f"/api/questions/{qid}").json()["concept"] == "Redis 持久化"
    assert c.post(f"/api/gaps/{gap['id']}/practice").json()["question_id"] == qid


def test_cards(c):
    card = c.post("/api/cards", json={"question": "Q", "answer": "A"}).json()
    assert card["policy"] == "sm2" and any(x["id"] == card["id"] for x in c.get("/api/cards/due").json())
    intervals = [c.post(f"/api/cards/{card['id']}/rate", json={"rating": "good"}).json()["interval"] for _ in range(3)]
    assert intervals == [1, 6, 15]
    fixed = c.post("/api/cards", json={"question": "Q2", "answer": "A2", "policy": "fixed"}).json()
    for _ in range(3):
        f = c.post(f"/api/cards/{fixed['id']}/rate", json={"rating": "easy"}).json()
    assert f["status"] == "retired"
    gen = c.post("/api/cards/generate", json={"topic": "AOF 重写", "count": 1}).json()
    assert gen[0]["sources"]
    n = c.post("/api/cards/import", files={"file": ("a.csv", "问1,答1\n问2,答2,集合X\n".encode())}).json()
    assert n["imported"] == 2 and "问2,答2,集合X" in c.get("/api/cards/export").text
    assert c.get("/api/cards/stats").json()["retired"] == 1


def test_sm2_against_reference():
    card = {"policy": "sm2", "ef": 2.5, "reps": 2, "interval": 6, "streak": 0}
    out = srs.schedule(card, "hard", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert out["interval"] == 15 and out["ef"] == pytest.approx(2.36)   # EF' = 2.5 + 0.1 - 2*(0.08+2*0.02)
    assert srs.schedule(card, "again")["ef"] == 2.5 and srs.schedule(card, "again")["interval"] == 1


def test_usage_and_delete(c):
    u = {x["task"]: x for x in c.get("/api/usage").json()}
    assert u["evaluate"]["calls"] >= 1 and u["evaluate"]["failures"] >= 2
    assert c.delete("/api/me").json()["ok"]
    assert c.get("/api/kb/docs").json() == [] and c.get("/api/cards").json() == []


def test_review_fixes(c):
    # domain criteria are part of the rubric version; domain docs + untagged docs are evidence
    d = c.post("/api/domains", json={"name": "后端", "criteria": "重视原理"}).json()
    c.post("/api/kb/docs", json={"title": "Redis", "body": "RDB 快照，AOF 日志。", "reviewed": True})  # untagged
    q = c.post("/api/questions", json={"text": "Redis 持久化？", "concept": "Redis 持久化", "domain_id": d["id"]}).json()
    ev = c.post(f"/api/questions/{q['id']}/attempts", json={"answer": "RDB"}).json()["evaluation"]
    assert ev["rubric_version"].startswith("r1+") and ev["history_aware"] == 1 and ev["status"] == "ok"
    # hint feedback survives deleting its question (preferences stay traceable)
    h = c.post(f"/api/questions/{q['id']}/hint", json={}).json()
    c.post(f"/api/hints/{h['id']}/feedback", json={"feedback": "just_right"})
    c.delete(f"/api/questions/{q['id']}")
    assert any(f["id"] == h["id"] and f["qtext"] == "（题目已删除）" for f in c.get("/api/prefs").json()["feedback"])
    # explicit null in a patch does not blank a field
    card = c.post("/api/cards", json={"question": "Q", "answer": "A"}).json()
    assert c.put(f"/api/cards/{card['id']}", json={"question": None, "answer": "B"}).json()["question"] == "Q"
    # LLM not configured -> evaluation stored as unavailable, not a half-written attempt
    from app import llm
    saved, llm.complete, llm._client = llm.complete, llm.__dict__["_orig_complete"], None
    old_model, llm.MODEL = llm.MODEL, ""
    try:
        q2 = c.post("/api/questions", json={"text": "Redis 持久化？"}).json()
        ev2 = c.post(f"/api/questions/{q2['id']}/attempts", json={"answer": "RDB"}).json()["evaluation"]
        assert ev2["status"] == "unavailable" and ev2["scores"] is None
    finally:
        llm.complete, llm.MODEL = saved, old_model


def test_program_arithmetic(c):
    # arithmetic in the answer is computed by the program and given to the evaluator as fact
    c.post("/api/kb/docs", json={"title": "CLV", "body": "CLV = 毛利×留存率÷(1−留存率)。", "reviewed": True})
    q = c.post("/api/questions", json={"text": "这个用户的 CLV 是多少？", "concept": "CLV"}).json()
    ev = c.post(f"/api/questions/{q['id']}/attempts", json={"answer": "30×0.8÷(1−0.8)=240 元"}).json()["evaluation"]
    p = next(x for x in reversed(PROMPTS) if "## 学习者回答" in x)
    assert "## 程序核算" in p and "= 120" in p and "不一致" in p
    assert ev["feedback"]["calc"] == [{"text": "30×0.8÷(1−0.8)=240", "expr": "30×0.8÷(1−0.8)", "claimed": "240",
                                       "value": "120", "ok": False}]


def test_no_relevant_material_is_uncertain(c):
    # retrieval always returns something; below the relevance floor it is not evidence, so no score
    c.post("/api/kb/docs", json={"title": "Redis 主从复制", "body": "Redis 从节点首次连接时全量同步，之后增量同步。",
                                 "reviewed": True})
    q = c.post("/api/questions", json={"text": "光合作用的暗反应在哪里进行？", "concept": "光合作用"}).json()
    ev = c.post(f"/api/questions/{q['id']}/attempts", json={"answer": "在叶绿体基质中进行。"}).json()["evaluation"]
    assert ev["status"] == "uncertain" and ev["scores"] is None and ev["evidence"] == []


def test_overall_caps_wrong_core_concept():
    from app import agent
    assert agent.overall({"correctness": 5, "coverage": 4, "reasoning": 4, "clarity": 5}) == 4.5
    # fluent but wrong: 2 + 4 + 4 + 4 would average 3.5
    assert agent.overall({"correctness": 2, "coverage": 4, "reasoning": 4, "clarity": 4}) == 2
    assert agent.overall(None) is None
