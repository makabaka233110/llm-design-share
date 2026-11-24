"""Agent tools: every LLM-backed step with structured input/output.

All prompts live here so their versions can be inspected and bumped together.
"""

import asyncio
import hashlib
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app import calc, db, llm, retrieval

RUBRIC_VERSION = "r1"
DIMENSIONS = ("correctness", "coverage", "reasoning", "clarity")

# Task kinds (proposal §2: professional-knowledge, behavioral, case-based).
KINDS = {
    "knowledge": {"label": "专业知识", "need_evidence": True,
                  "focus": "概念是否准确、关键点是否齐全、因果是否讲清、能否举例"},
    "behavioral": {"label": "行为", "need_evidence": False,
                   "focus": "按 STAR（情境、任务、行动、结果）讲述，行动具体、结果可衡量、有反思"},
    "case": {"label": "案例分析", "need_evidence": False,
             "focus": "澄清问题与约束、结构化拆解、取舍有依据、结论可执行"},
}

RUBRIC = """评分维度（每项 1-5 分）：
- correctness 正确性：论断与参考资料一致，无错误（1=多处错误，5=完全正确）
- coverage 覆盖度：覆盖题目要求的关键点（1=大量遗漏，5=完整）
- reasoning 推理：因果、取舍、步骤是否讲清（1=无推理，5=严密）
- clarity 清晰度：结构与表达（1=混乱，5=清楚简洁）"""


def _domain(domain_id) -> dict:
    return db.row("SELECT * FROM domains WHERE id=?", domain_id) or {"name": "", "goals": "", "criteria": ""}


# ── evaluation (shared by interview, Feynman practice and scenarios) ────

class Point(BaseModel):
    text: str
    quote: str = ""                       # learner's own wording
    evidence: list[str] = Field(default_factory=list)  # evidence ids, e.g. ["E1"]


class EvalOut(BaseModel):
    status: Literal["ok", "uncertain"]
    reason: str = ""
    scores: dict[str, int] | None = None
    strengths: list[Point] = Field(default_factory=list)
    omissions: list[Point] = Field(default_factory=list)
    misconceptions: list[Point] = Field(default_factory=list)
    revisions: list[str] = Field(default_factory=list)
    recurring: list[str] = Field(default_factory=list)
    resolved: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self):
        if self.status == "ok":
            if not self.scores or set(self.scores) != set(DIMENSIONS):
                raise ValueError(f"status=ok 时 scores 必须恰好包含 {DIMENSIONS}")
            if any(not 1 <= v <= 5 for v in self.scores.values()):
                raise ValueError("分数必须是 1-5 的整数")
        else:
            self.scores = None
        return self


EVAL_SYSTEM = ("你是严谨的学习评估者。事实判断只依据给定参考资料；参考资料未覆盖的论断不要判错，"
               "而是说明无法核实。只返回 JSON。")


def _history_text(question_id: int, before_attempt: int) -> str:
    past = db.rows("""SELECT a.version, a.answer, e.feedback FROM attempts a
                      LEFT JOIN evaluations e ON e.attempt_id=a.id
                      WHERE a.question_id=? AND a.id<? ORDER BY a.id""", question_id, before_attempt)
    lines = []
    for p in past:
        fb = p["feedback"] or {}
        issues = [x["text"] for x in fb.get("misconceptions", []) + fb.get("omissions", [])]
        lines.append(f"v{p['version']}：{p['answer']}\n  当时指出的问题：{'；'.join(issues) or '无'}")
    return "\n".join(lines)


async def evaluate(user: str, question: dict, attempt: dict, *, kind: str = "knowledge",
                   evidence_mode: str = "weighted", history_aware: bool = True, use_calc: bool = True) -> dict:
    """Evaluate one attempt and store the result. evidence_mode: weighted|hybrid|none.
    use_calc: arithmetic is computed by the program (app/calc.py), the model only judges the method."""
    spec, dom = KINDS[kind], _domain(question["domain_id"])
    # domain criteria are part of the rubric: a changed criterion is a different rubric version
    rubric = RUBRIC_VERSION + (f"+{hashlib.sha1(dom['criteria'].encode()).hexdigest()[:6]}" if dom["criteria"] else "")
    rubric += "+calc" if use_calc else ""
    checks = calc.check(attempt["answer"]) if use_calc else []
    passages = [] if evidence_mode == "none" else await retrieval.evidence(
        user, f"{question['text']} {question['concept']}", attempt["answer"], mode=evidence_mode,
        domain_id=question["domain_id"])
    history = _history_text(question["id"], attempt["id"]) if history_aware else ""
    related = await retrieval.related_questions(user, question["text"], {question["id"]})
    result = {"status": "ok", "scores": None, "feedback": {}, "evidence": retrieval.cite(passages)}

    if evidence_mode != "none" and spec["need_evidence"] and not passages:
        result.update(status="uncertain", feedback={"reason": "知识库中没有已审核的相关资料，无法给出有依据的评分。"
                                                              "请先在知识库添加并审核相关资料。"})
    else:
        prompt = f"""## 题目
{question['text']}
{('情境与约束：' + question['context']) if question['context'] else ''}
核心概念：{question['concept'] or '（未标注）'}
题型：{spec['label']}（关注：{spec['focus']}）
{('## 评分要点（不向学习者展示）\n' + chr(10).join('- ' + p for p in question['eval_points'])) if question.get('eval_points') else ''}

## 参考资料
{retrieval.as_context(passages) if evidence_mode != 'none' else '（本次评估不提供参考资料，请依据你的知识判断）'}

## 学习者回答（第 {attempt['version']} 版）
{attempt['answer']}

{('## 程序核算（回答中的算式已由程序计算，结果以此为准）' + chr(10) + calc.as_prompt(checks)) if checks else ''}

{('## 历史作答（旧→新）\n' + history) if history else ''}

{('## 题库中的相关问题（仅供参考：提示面试官可能追问的方向，不作为评分依据）\n' + chr(10).join('- ' + r['text'] for r in related)) if related else ''}

## 评分标准（{RUBRIC_VERSION}）
{RUBRIC}
{('领域补充标准：' + dom['criteria']) if dom['criteria'] else ''}

## 输出 JSON
{{"status":"ok","reason":"","scores":{{"correctness":1,"coverage":1,"reasoning":1,"clarity":1}},
 "strengths":[{{"text":"","quote":"学习者原话片段","evidence":["E1"]}}],
 "omissions":[{{"text":"","quote":"","evidence":[]}}],
 "misconceptions":[{{"text":"","quote":"","evidence":[]}}],
 "revisions":["具体修改建议"],
 "recurring":["历史中出现且本次仍存在的错误"], "resolved":["历史中出现、本次已纠正的问题"]}}
规则：quote 必须是学习者原文的连续片段；evidence 只能使用上面出现的编号；
标注「用于核对」的资料是按回答中的某句话检索到的，若它与那句话无关，该论断视为无法核实，不能据此判对错；
若参考资料不足以判断正确性，status 设为 "uncertain"、scores 设为 null 并在 reason 说明；
没有历史作答时 recurring 和 resolved 为空数组。"""
        if use_calc:
            prompt += """
数值计算交给程序：不要自己心算或重算；回答里算式的结果以「程序核算」为准。你只评判公式选择、口径和推理是否合理。
评语中需要写出数值时，写成「算式 = 结果」，系统会用程序复核。"""
        try:
            out = await asyncio.to_thread(llm.chat_json, "evaluate", EVAL_SYSTEM, prompt, EvalOut, user)
            ids = {p["eid"] for p in passages}
            for p in out.strengths + out.omissions + out.misconceptions:
                p.evidence = [e for e in p.evidence if e in ids]
                if p.quote and p.quote not in attempt["answer"]:
                    p.quote = ""  # drop quotes that are not the learner's words
            if use_calc:
                _recheck(out, checks)
            fb = out.model_dump(exclude={"status", "scores"})
            if use_calc:
                fb["calc"] = checks
            result.update(status=out.status, scores=out.scores, feedback=fb)
        except llm.LLMError as e:
            result.update(status="unavailable", feedback={"reason": str(e)})

    result["id"] = db.insert("evaluations", attempt_id=attempt["id"], status=result["status"],
                             scores=result["scores"], feedback=result["feedback"], evidence=result["evidence"],
                             evidence_mode=evidence_mode, history_aware=int(history_aware),
                             rubric_version=rubric, model=llm.MODEL)
    result.update(rubric_version=rubric, model=llm.MODEL, evidence_mode=evidence_mode, history_aware=int(history_aware))
    return result


def _recheck(out: EvalOut, checks: list[dict]) -> None:
    """The model's own arithmetic is not trusted either: annotate wrong results in its feedback, and flag
    misconceptions that quote a calculation the program found correct."""
    def fix(t: str) -> str:
        bad = [c for c in calc.check(t) if not c["ok"]]
        return t + "".join(f"（程序核算：{c['expr']} = {c['value']}，评语中的「{c['claimed']}」有误）" for c in bad)
    out.reason = fix(out.reason)
    out.revisions = [fix(t) for t in out.revisions]
    for p in out.strengths + out.omissions + out.misconceptions:
        p.text = fix(p.text)
    for p in out.misconceptions:
        right = [c for c in checks if c["ok"] and p.quote and (c["text"] in p.quote or p.quote in c["text"])]
        if right:
            p.text += f"（程序核算：所引算式 {right[0]['expr']} = {right[0]['value']}，计算本身正确）"


def record_attempt(user: str, question_id: int, answer: str, mode: str) -> dict:
    """Answers are immutable; each revision is a new version."""
    n = db.row("SELECT COUNT(*) n FROM attempts WHERE question_id=?", question_id)["n"]
    aid = db.insert("attempts", user_id=user, question_id=question_id, mode=mode, answer=answer, version=n + 1)
    return db.row("SELECT * FROM attempts WHERE id=?", aid)


def add_gaps(user: str, texts: list[str], origin: str, origin_id: int, domain_id=None, question_id=None,
             confirmed: bool = False) -> None:
    """Candidate gaps enter unconfirmed; only learner-confirmed gaps feed cards and scenarios."""
    for t in texts:
        db.insert("gaps", user_id=user, domain_id=domain_id, text=t, origin=origin, origin_id=origin_id,
                  question_id=question_id, confirmed=int(confirmed))


# ── mock interview ──────────────────────────────────────────────────────

MAX_FOLLOW_UPS = 2  # interviewer follows up at most twice on one question, then moves on


class TurnOut(BaseModel):
    action: Literal["follow_up", "next"]
    question: str
    concept: str = ""


def interviewer_turn(user: str, session: dict, follow_ups: int, last_eval: dict | None) -> TurnOut:
    spec, dom = KINDS[session["kind"]], _domain(session["domain_id"])
    turns = db.rows("SELECT role, content FROM turns WHERE session_id=? ORDER BY id", session["id"])
    topics = db.rows("SELECT title, topic FROM docs WHERE user_id=? AND (domain_id=? OR ? IS NULL) AND reviewed=1",
                     user, session["domain_id"], session["domain_id"])
    history = "\n".join(f"[{'面试官' if t['role'] == 'interviewer' else '候选人'}] {t['content']}" for t in turns)
    allowed = "follow_up 或 next" if turns and follow_ups < MAX_FOLLOW_UPS else "只能 next（换一个新问题）"
    ev = ""
    if last_eval and last_eval.get("feedback"):
        fb = last_eval["feedback"]
        ev = "；".join(p["text"] for p in fb.get("omissions", []) + fb.get("misconceptions", [])) or "回答充分"
    system = (f"你是{spec['label']}面试官。目标岗位：{session['role'] or '未指定'}；领域：{dom['name'] or '未指定'}。"
              f"学习目标：{dom['goals'] or '未指定'}。关注：{spec['focus']}。每次只问一个简洁的问题。只返回 JSON。")
    prompt = f"""对话记录：
{history or '（尚未开始）'}

上一回答的评估要点：{ev or '无'}
学习者资料中的主题（出题可参考）：{'、'.join(f"{t['title']}({t['topic']})" if t['topic'] else t['title'] for t in topics) or '无'}

本轮可选动作：{allowed}。回答有明显遗漏或误解时追问，否则换题；不要重复已问过的问题。
返回 {{"action":"follow_up|next","question":"...","concept":"本题考查的核心概念"}}"""
    out = llm.chat_json("interview_turn", system, prompt, TurnOut, user, max_tokens=400)
    if not turns or follow_ups >= MAX_FOLLOW_UPS:
        out.action = "next"
    return out


def interview_summary(user: str, session: dict) -> str:
    turns = db.rows("SELECT role, content FROM turns WHERE session_id=? ORDER BY id", session["id"])
    history = "\n".join(f"[{t['role']}] {t['content']}" for t in turns)
    return llm.chat("interview_summary", "你是面试复盘助手。", f"""总结这次{KINDS[session['kind']]['label']}模拟面试：
{history}

输出：1. 整体表现（1-2 句） 2. 优点 3. 需要改进的地方 4. 建议的学习方向""", user, 800)


# ── speech reflection ───────────────────────────────────────────────────

class ReflectionOut(BaseModel):
    summary: str
    key_points: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)


def reflect(user: str, transcript: str, kind: str) -> ReflectionOut:
    return llm.chat_json("reflect", "你是面试复盘助手。只返回 JSON。", f"""以下是一次{KINDS[kind]['label']}面试或口头练习的转写稿（已由学习者校对）。
总结核心要点，找出不足（回答不完整、缺乏深度、表达问题等），给出改进建议。

{transcript}

返回 {{"summary":"3-5 句总结","key_points":[...],"weaknesses":["每条一个具体不足"],"improvements":[...]}}""",
                         ReflectionOut, user)


# ── Extension 1: feedback-driven hints ──────────────────────────────────

HINT_FEEDBACK = {"too_direct": "太直接，泄露了答案", "too_vague": "太模糊", "just_right": "刚好"}
RELATED_FEEDBACK = 5  # generation budget: at most 5 past feedback items in the prompt


def root_of(q: dict) -> int:
    while q["parent_id"]:
        q = db.row("SELECT * FROM questions WHERE id=?", q["parent_id"])
    return q["id"]


def current_prefs(user: str) -> dict:
    return db.row("SELECT * FROM hint_prefs WHERE user_id=? ORDER BY version DESC LIMIT 1", user) or \
        {"version": 0, "summary": "", "source": "none", "created_at": ""}


def _feedback_since_reset(user: str) -> list[dict]:
    reset = db.row("SELECT created_at FROM hint_prefs WHERE user_id=? AND source='reset' "
                   "ORDER BY version DESC LIMIT 1", user)
    return db.rows("""SELECT h.*, q.text qtext, q.concept, q.parent_id FROM hints h LEFT JOIN questions q ON q.id=h.question_id
                      WHERE h.user_id=? AND h.rating IS NOT NULL AND h.feedback_at>? ORDER BY h.feedback_at DESC""",
                   user, reset["created_at"] if reset else "")


def hint(user: str, question: dict, personalized: bool = True, passages: list[dict] | None = None) -> dict:
    prefs = current_prefs(user) if personalized else {"version": 0, "summary": ""}
    related = []
    if personalized:
        fam, rows_ = root_of(question), _feedback_since_reset(user)
        same = [r for r in rows_ if (r["concept"] and r["concept"] == question["concept"])
                or root_of({"parent_id": r["parent_id"], "id": r["question_id"]}) == fam]
        related = (same + [r for r in rows_ if r not in same])[:RELATED_FEEDBACK]
    last = db.row("SELECT answer FROM attempts WHERE question_id=? ORDER BY id DESC LIMIT 1", question["id"])
    prompt = f"""题目：{question['text']}
{('情境：' + question['context']) if question['context'] else ''}
核心概念：{question['concept'] or '未标注'}
参考资料：
{retrieval.as_context(passages or [])}
学习者上一版回答：{last['answer'] if last else '（尚未作答）'}
"""
    if personalized:
        prompt += f"""
学习者的提示偏好（v{prefs['version']}）：{prefs['summary'] or '暂无'}
过去对提示的反馈：
{chr(10).join(f"- 题「{r['qtext'][:40]}」的提示「{r['text'][:80]}」→ {HINT_FEEDBACK[r['rating']]} {r['comment']}" for r in related) or '暂无'}
"""
    prompt += "\n给一条提示，指出思考方向而不是完整答案。直接输出提示文本。"
    text = llm.chat("hint", "你是学习教练：给提示，不给答案。", prompt, user, 400)
    hid = db.insert("hints", user_id=user, question_id=question["id"], text=text, pref_version=prefs["version"],
                    personalized=int(personalized))
    return {"id": hid, "text": text, "pref_version": prefs["version"], "used_feedback": len(related)}


def update_prefs(user: str) -> dict:
    """Summarise feedback into an inspectable preference text (new version)."""
    cur, fb = current_prefs(user), _feedback_since_reset(user)
    lines = "\n".join(f"- {HINT_FEEDBACK[r['rating']]}：{r['comment']}（提示：{r['text'][:80]}）" for r in fb)
    try:
        summary = llm.chat("hint_prefs", "你负责归纳学习者对提示的偏好。", f"""当前偏好：{cur['summary'] or '暂无'}
全部反馈（新→旧）：
{lines}
用不超过 5 条要点归纳该学习者希望提示的详略和措辞（例如：只给思考方向、不要给出结论）。只输出要点。""", user, 300)
    except llm.LLMError:
        counts = {k: sum(r["rating"] == k for r in fb) for k in HINT_FEEDBACK}
        summary = "；".join(f"{HINT_FEEDBACK[k]}×{n}" for k, n in counts.items() if n)
    return set_prefs(user, summary, "auto")


def set_prefs(user: str, summary: str, source: str) -> dict:
    v = current_prefs(user)["version"] + 1
    db.insert("hint_prefs", user_id=user, version=v, summary=summary, source=source)
    return current_prefs(user)


# ── Extension 3: linked scenario questions ──────────────────────────────

class ScenarioOut(BaseModel):
    question: str
    context: str
    eval_points: list[str]
    concept: str


class CheckOut(BaseModel):
    concept_aligned: bool
    answerable: bool
    duplicate_of: int | None = None
    reason: str = ""


SCENARIO_TRIES = 2


async def scenario(user: str, parent: dict, difficulty: str, gaps: list[str], passages: list[dict]) -> dict:
    fam = root_of(parent)
    family = {q["id"]: q for q in db.rows("SELECT id, text, parent_id, concept FROM questions WHERE user_id=?", user)
              if q["concept"] == parent["concept"] or root_of(q) == fam}
    feedback = ""
    for _ in range(SCENARIO_TRIES):
        gen = await asyncio.to_thread(llm.chat_json, "scenario", "你设计应用型练习题。只返回 JSON。", f"""原题：{parent['text']}
核心概念：{parent['concept'] or '请从原题推断'}
学习者的相关薄弱点：{'；'.join(gaps) or '无'}
难度：{difficulty}（相对原题）
参考资料：
{retrieval.as_context(passages)}
{feedback}
设计一道新的情境题：保留同一核心概念，但换一个应用情境或约束条件，不能只是改写原题。题目要自洽、信息足够作答。
返回 {{"question":"题干","context":"情境与约束","eval_points":["评分要点，不向学习者展示"],"concept":"核心概念"}}""",
                                    ScenarioOut, user)
        # near-duplicate candidates: the parent's family, same-concept questions, and the bank's nearest questions
        nearest = await retrieval.related_questions(user, gen.question, set(family))
        existing = "\n".join(f"#{q['id']} {q['text']}" for q in [*family.values(), *nearest])
        check = await asyncio.to_thread(llm.chat_json, "scenario_check", "你审核练习题质量。只返回 JSON。", f"""核心概念：{parent['concept'] or parent['text']}
新题：{gen.question}
情境：{gen.context}
已有题目：
{existing}
判断：1) 新题是否仍考查该核心概念；2) 信息是否足以作答；3) 是否与某道已有题目基本重复（只是改写、情境未变）。
返回 {{"concept_aligned":true,"answerable":true,"duplicate_of":null 或题号,"reason":""}}""", CheckOut, user, 300)
        if check.concept_aligned and check.answerable and not check.duplicate_of:
            qid = db.insert("questions", user_id=user, domain_id=parent["domain_id"], text=gen.question,
                            concept=gen.concept or parent["concept"], kind=parent["kind"], origin="scenario",
                            parent_id=parent["id"], context=gen.context, eval_points=gen.eval_points,
                            difficulty=difficulty, sources=[p["doc_id"] for p in passages])
            return {"question_id": qid, "check": check.model_dump()}
        feedback = f"上一次生成未通过审核：{check.model_dump_json()}。请修正。"
    raise llm.LLMError(f"情境题未通过检查：{check.reason}")


# ── gaps -> practice ────────────────────────────────────────────────────

class GapQuestionOut(BaseModel):
    question: str
    concept: str


def practice_from_gap(user: str, gap: dict) -> int:
    """Turn a confirmed gap into a bank question (linked back to the gap) so it can be practised."""
    try:
        out = llm.chat_json("gap_question", "你把学习者的薄弱点改写成练习题。只返回 JSON。", f"""薄弱点：{gap['text']}
改写成一道让学习者用自己的话讲解的练习题，并给出它考查的核心概念（几个字）。
返回 {{"question":"...","concept":"..."}}""", GapQuestionOut, user, 300)
        text, concept = out.question, out.concept
    except llm.LLMError:
        text, concept = f"请用自己的话讲清楚：{gap['text']}", ""
    qid = db.insert("questions", user_id=user, domain_id=gap["domain_id"], text=text, concept=concept,
                    origin=gap["origin"] if gap["origin"] in ("reflection", "interview") else "manual")
    db.update("gaps", gap["id"], question_id=qid)
    return qid


# ── flashcards ──────────────────────────────────────────────────────────

class CardItem(BaseModel):
    question: str
    answer: str
    evidence: list[str] = Field(default_factory=list)


class CardsOut(BaseModel):
    cards: list[CardItem]


def gen_cards(user: str, topic: str, count: int, passages: list[dict]) -> list[dict]:
    out = llm.chat_json("cards", "你是闪卡生成助手。只返回 JSON。", f"""根据参考资料，为「{topic}」生成 {count} 张问答闪卡。
参考资料：
{retrieval.as_context(passages)}
要求：问题是面试或考试会问的真实问题；答案简洁准确，只使用参考资料支持的内容，并标注依据编号。
返回 {{"cards":[{{"question":"","answer":"","evidence":["E1"]}}]}}""", CardsOut, user, 1500)
    by_eid = {p["eid"]: p["doc_id"] for p in passages}
    return [{"question": c.question, "answer": c.answer,
             "sources": sorted({by_eid[e] for e in c.evidence if e in by_eid})} for c in out.cards[:count]]
