/* 面壁 Mianbi — single-file vanilla UI. Every dynamic value goes through h`` (HTML-escaped). */

const S = { user: localStorage.user || 'default', domain: localStorage.domain || '', domains: [] };
const main = document.getElementById('main');

// ── tiny helpers ──────────────────────────────────────────────────────
class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
const raw = s => new Raw(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = v => v instanceof Raw ? v.s : Array.isArray(v) ? v.map(fmt).join('') : (v === false || v == null) ? '' : esc(v);
const h = (str, ...vals) => raw(str.reduce((a, s, i) => a + s + (i < vals.length ? fmt(vals[i]) : ''), ''));
const $ = sel => document.querySelector(sel);
const val = id => document.getElementById(id).value;
const set = (el, html) => { (typeof el === 'string' ? $(el) : el).innerHTML = fmt(html); };
const when = iso => iso ? new Date(iso).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
const dq = (p = '?') => S.domain ? `${p}domain_id=${S.domain}` : '';
const domainId = () => S.domain ? +S.domain : null;

function toast(msg, err = false) {
  const d = document.createElement('div');
  d.textContent = msg; if (err) d.className = 'err';
  $('#toast').appendChild(d); setTimeout(() => d.remove(), err ? 6000 : 2600);
}

async function api(path, { method = 'GET', body, form } = {}) {
  const opt = { method, headers: { 'X-User': S.user } };
  if (form) opt.body = form;
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(path, opt);
  const data = (r.headers.get('content-type') || '').includes('json') ? await r.json() : await r.text();
  if (!r.ok) {
    const d = data && data.detail;
    const msg = typeof d === 'string' ? d : d ? d.map(x => x.msg).join('；') : `${r.status} ${r.statusText}`;
    toast(msg, true); throw new Error(msg);
  }
  return data;
}
const post = (p, b = {}) => api(p, { method: 'POST', body: b });
const put = (p, b = {}) => api(p, { method: 'PUT', body: b });
const del = p => api(p, { method: 'DELETE' });

async function busy(btn, fn) {
  const label = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<span class="spin"></span> ' + label;
  try { return await fn(); } catch (e) { console.warn(e); } finally { btn.disabled = false; btn.innerHTML = label; }
}

const KIND = { knowledge: '专业知识', behavioral: '行为', case: '案例分析' };
const ORIGIN = { manual: '手动', interview: '模拟面试', scenario: '情境题', reflection: '复盘', eval: '实验' };
const MODE = { feynman: '讲解', interview: '面试', scenario: '情境题', eval: '实验' };
const DIM = { correctness: '正确性', coverage: '覆盖度', reasoning: '推理', clarity: '清晰度' };
const avg = s => s ? (Object.values(s).reduce((a, b) => a + b, 0) / 4).toFixed(1) : null;
const empty = (title, hint) => h`<div class="empty"><b>${title}</b>${hint}</div>`;
const seg = (id, opts, on) => h`<div class="seg" id="${id}">${Object.entries(opts).map(([k, v]) =>
  h`<button data-v="${k}" class="${k === on ? 'on' : ''}" onclick="segPick(this)">${v}</button>`)}</div>`;
function segPick(b) { b.parentNode.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); b.parentNode.dispatchEvent(new Event('change')); }
const segVal = id => $(`#${id} .on`).dataset.v;

// ── shell ─────────────────────────────────────────────────────────────
const ICON = {
  kb: '<path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H20v15H5.5A1.5 1.5 0 0 0 4 19.5z"/><path d="M4 19.5A1.5 1.5 0 0 0 5.5 21H20"/><path d="M9 7h7"/>',
  practice: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9V16h7v-2.1A6 6 0 0 0 12 3z"/>',
  interview: '<path d="M20 12a8 8 0 0 1-11.5 7.2L4 20l.9-4.2A8 8 0 1 1 20 12z"/>',
  speech: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
  cards: '<rect x="3" y="7" width="14" height="13" rx="2"/><path d="M7 4h11a2 2 0 0 1 2 2v10"/>',
  records: '<path d="M4 20V11M10 20V5M16 20v-6M21 20H3"/>',
};
const NAV = { practice: '练习', interview: '模拟面试', speech: '语音复盘', cards: '闪卡', kb: '知识库', records: '学习记录' };

function renderNav(active, due) {
  set('#nav', Object.entries(NAV).map(([k, v]) => h`<a href="#${k}" class="${k === active ? 'active' : ''}">
    <svg viewBox="0 0 24 24">${raw(ICON[k])}</svg>${v}${k === 'cards' && due ? h`<span class="badge accent">${due}</span>` : ''}</a>`));
  set('#user-name', S.user); set('#user-avatar', S.user[0].toUpperCase());
}

async function loadDomains() {
  S.domains = await api('/api/domains');
  if (S.domain && !S.domains.some(d => d.id == S.domain)) S.domain = '';
  set('#domain-select', [h`<option value="">全部领域</option>`, ...S.domains.map(d =>
    h`<option value="${d.id}" ${d.id == S.domain ? 'selected' : ''}>${d.name}</option>`)]);
}
$('#domain-select').onchange = e => { S.domain = localStorage.domain = e.target.value; route(); };

const VIEWS = {};
function go(path) { location.hash = path; }
window.onhashchange = () => route();
async function route() {
  const [v, id] = (location.hash.slice(1) || 'practice').split('/');
  const stats = await api('/api/cards/stats').catch(() => ({}));
  renderNav(VIEWS[v] ? v : 'practice', stats.due);
  main.innerHTML = '';
  await (VIEWS[v] || VIEWS.practice)(id);
}

// ── evaluation rendering (shared) ─────────────────────────────────────
function meters(scores) {
  return h`<div class="stack" style="gap:6px">${Object.entries(DIM).map(([k, label]) => h`<div class="meter">
    <span class="muted">${label}</span><div class="bar"><i style="width:${scores[k] * 20}%"></i></div><b>${scores[k]}</b></div>`)}</div>`;
}

function evalView(ev, { questionId, compact = false } = {}) {
  if (!ev) return '';
  const fb = ev.feedback || {};
  const ids = Object.fromEntries((ev.evidence || []).map(e => [e.eid, e]));
  const chips = p => (p.evidence || []).map(e => h`<span class="eid" title="${ids[e] ? ids[e].title + ' / ' + ids[e].heading + '\n' + ids[e].snippet : ''}">${e}</span>`);
  const pts = (title, list, cls, gap) => list && list.length ? h`<h3>${title}</h3><ul class="points ${cls}">${list.map(p => h`<li>${p.text}${chips(p)}
      ${p.quote ? h`<span class="quote">“${p.quote}”</span>` : ''}
      ${gap ? h`<button class="ghost sm" data-text="${p.text}" onclick="markGap(this, ${questionId || 'null'})">记为薄弱点</button>` : ''}</li>`)}</ul>` : '';
  const strs = (title, list, cls) => list && list.length ? h`<h3>${title}</h3><ul class="points ${cls}">${list.map(t => h`<li>${t}</li>`)}</ul>` : '';
  let head;
  if (ev.status === 'ok') head = h`<div class="row between"><b>综合 ${avg(ev.scores)} / 5</b><span class="badge ok">有依据评分</span></div><div style="margin-top:10px">${meters(ev.scores)}</div>`;
  else if (ev.status === 'uncertain') head = h`<div class="notice warn"><b>无法确定评分</b>　${fb.reason || ''}</div>`;
  else head = h`<div class="notice bad"><b>评估不可用</b>　${fb.reason || ''}</div>`;
  return h`<div class="fade">${head}
    ${pts('做得好', fb.strengths, 'ok')}${pts('遗漏', fb.omissions, 'warn', true)}${pts('误解', fb.misconceptions, 'bad', true)}
    ${strs('修改建议', fb.revisions)}${strs('反复出现的问题', fb.recurring, 'bad')}${strs('已纠正', fb.resolved, 'ok')}
    ${!compact && ev.evidence && ev.evidence.length ? h`<h3>证据</h3><div class="stack">${ev.evidence.map(e => h`<div class="evidence">
      <div class="row between"><span><span class="eid">${e.eid}</span> <b>${e.title}</b> <span class="muted tiny">${e.heading} · v${e.version}</span></span>
      <span class="row"><button class="ghost sm" onclick="kbFeedback(${e.doc_id}, true)">有用</button><button class="ghost sm" onclick="kbFeedback(${e.doc_id}, false)">没用</button></span></div>
      ${e.claim ? h`<div class="tiny" style="color:var(--info)">核对你说的：「${e.claim}」</div>` : ''}
      <div class="snippet">${e.snippet}</div></div>`)}</div>` : ''}
    <p class="muted tiny" style="margin-top:12px">评分标准 ${ev.rubric_version} · 模型 ${ev.model || '—'} · 证据 ${ev.evidence_mode}${ev.history_aware ? ' · 参考历史' : ''}</p></div>`;
}

async function markGap(btn, questionId) {
  await busy(btn, async () => {
    await post('/api/gaps', { text: btn.dataset.text, question_id: questionId, domain_id: domainId() });
    btn.textContent = '已记录'; btn.disabled = true; toast('已加入薄弱点（学习记录）');
  });
}
async function kbFeedback(docId, helpful) {
  const r = await post('/api/kb/feedback', { doc_id: docId, helpful });
  toast(`资料优先级 ${r.old_priority} → ${r.new_priority}`);
}

// ── practice (Feynman) ────────────────────────────────────────────────
VIEWS.practice = async id => id ? practiceDetail(+id) : practiceList();

async function practiceList() {
  set(main, h`<div class="page-head"><div><h1>练习</h1><p>用自己的话讲解一道题或一个概念。AI 依据已审核资料指出遗漏与误解，每次修改都保留为新版本。</p></div></div>
  <div class="grid cols-side">
    <div class="card"><div class="row between" style="margin-bottom:10px"><h2 style="margin:0">题库</h2>
      ${seg('q-origin', { '': '全部', manual: '手动', interview: '面试', scenario: '情境题', concept: '按概念' }, '')}</div><div id="q-list" class="list"></div></div>
    <div class="card"><h2>新题目 / 概念</h2><div class="stack">
      <label class="field"><span>题目或要讲解的概念</span><textarea id="q-text" rows="3" placeholder="例如：解释机会成本，并举一个例子"></textarea></label>
      <div class="grid cols-2"><label class="field"><span>核心概念（用于关联）</span><input id="q-concept" placeholder="机会成本"></label>
      <label class="field"><span>题型</span><select id="q-kind">${Object.entries(KIND).map(([k, v]) => h`<option value="${k}">${v}</option>`)}</select></label></div>
      <div class="row end"><button class="primary" onclick="createQuestion(this)">开始讲解</button></div></div></div>
  </div>`);
  $('#q-origin').onchange = loadQuestions;
  await loadQuestions();
}

const scoreBadge = s => s == null ? h`<span class="badge">未评分</span>` : h`<span class="badge ${s >= 4 ? 'ok' : s >= 3 ? '' : 'warn'}">${s}</span>`;

async function loadConcepts() {
  const gs = await api('/api/concepts' + dq());
  set('#q-list', gs.length ? h`<p class="muted tiny">同一概念在定义题、面试题和情境题上的最新得分。弱的概念排在前面。</p>${gs.map(g => h`
    <div class="evidence" style="margin-bottom:10px"><div class="row between"><b>${g.concept}</b>${scoreBadge(g.avg)}</div>
    <div class="stack" style="gap:4px;margin-top:6px">${g.questions.map(q => h`<div class="row tiny" style="cursor:pointer" onclick="go('practice/${q.id}')">
      <span class="badge ${q.origin === 'scenario' ? 'info' : q.origin === 'interview' ? 'accent' : ''}">${ORIGIN[q.origin] || q.origin}</span>
      <span class="grow" style="flex:1">${q.text.slice(0, 50)}</span>${scoreBadge(q.latest_score)}</div>`)}</div></div>`)}`
    : empty('还没有带概念标签的题目', '新建题目时填写“核心概念”即可按概念汇总。'));
}

async function loadQuestions() {
  const origin = segVal('q-origin');
  if (origin === 'concept') return loadConcepts();
  const qs = await api('/api/questions?' + [origin && `origin=${origin}`, dq('')].filter(Boolean).join('&'));
  set('#q-list', qs.length ? qs.map(q => h`<div class="item" onclick="go('practice/${q.id}')"><div class="grow">
    <div class="title">${q.text}</div><div class="row tiny" style="margin-top:4px">
    <span class="badge ${q.origin === 'scenario' ? 'info' : q.origin === 'interview' ? 'accent' : ''}">${ORIGIN[q.origin] || q.origin}</span>
    ${q.concept ? h`<span class="badge">${q.concept}</span>` : ''}<span class="muted">${q.attempts} 次作答</span></div></div></div>`)
    : empty('还没有题目', '在右侧输入一个概念开始讲解，或先进行一次模拟面试。'));
}

async function createQuestion(btn) {
  if (!val('q-text').trim()) return toast('请输入题目', true);
  await busy(btn, async () => {
    const q = await post('/api/questions', { text: val('q-text'), concept: val('q-concept'), kind: val('q-kind'), domain_id: domainId() });
    go('practice/' + q.id);
  });
}

async function practiceDetail(id) {
  const q = S.q = await api('/api/questions/' + id);
  const last = q.attempts[q.attempts.length - 1];
  S.sel = last ? last.id : null; S.cmp = new Set();
  set(main, h`<div class="page-head"><div><a onclick="go('practice')" class="tiny">← 题库</a></div></div>
  <div class="grid cols-side">
    <div class="stack">
      <div class="card"><div class="row" style="margin-bottom:8px"><span class="badge">${KIND[q.kind]}</span>
        <span class="badge ${q.origin === 'scenario' ? 'info' : ''}">${ORIGIN[q.origin] || q.origin}</span>
        ${q.concept ? h`<span class="badge accent">${q.concept}</span>` : ''}${q.difficulty ? h`<span class="badge">难度 ${q.difficulty}</span>` : ''}
        <span class="spacer"></span><button class="ghost sm danger" onclick="deleteQuestion(${q.id})">删除</button></div>
        <div style="font-size:16px;font-weight:500" class="pre">${q.text}</div>
        ${q.context ? h`<div class="notice info" style="margin-top:10px">${q.context}</div>` : ''}
        ${q.parent ? h`<p class="tiny muted" style="margin-top:10px">由 <a onclick="go('practice/${q.parent.id}')">${q.parent.text.slice(0, 40)}</a> 生成</p>` : ''}
        <div class="divider"></div>
        <div class="row"><button onclick="askHint(this)">💡 提示</button>
          <span class="spacer"></span><select id="sc-diff" style="width:auto"><option>更简单</option><option selected>相当</option><option>更难</option></select>
          <button onclick="makeScenario(this, [])">试试情境题</button></div>
        <div id="hints"></div></div>
      <div class="card"><h2>${q.attempts.length ? '再讲一遍（新版本）' : '用自己的话讲解'}</h2><div class="stack">
        <textarea id="ans" rows="6" placeholder="讲清楚概念、因果关系，并举例。"></textarea>
        <div class="row">${last ? h`<button class="ghost sm" onclick="document.getElementById('ans').value = S.q.attempts.at(-1).answer">基于上一版修改</button>` : ''}
          <label class="btn sm" style="padding:3px 9px">🎙 录音转文字<input type="file" accept="audio/*" hidden onchange="transcribeInto(this, 'ans')"></label>
          <span class="spacer"></span>
          <details><summary>评估选项</summary><div class="stack" style="padding:8px 0">
            <label class="check"><input type="checkbox" id="opt-hist" checked>参考历史作答（识别反复出现的错误）</label>
            <label class="field"><span>证据</span><select id="opt-ev"><option value="weighted">资料（按优先级重排）</option><option value="hybrid">资料（不加权）</option><option value="none">不使用资料</option></select></label></div></details>
          <button class="primary" onclick="submitAnswer(this)">提交讲解</button></div></div></div>
      <div class="card" id="eval-card" ${q.attempts.length ? '' : 'hidden'}><div id="eval"></div></div>
    </div>
    <div class="stack">
      <div class="card"><div class="row between"><h2 style="margin:0">作答历史</h2><button class="sm" onclick="compare()">对比所选两版</button></div>
        <p class="muted tiny" style="margin:4px 0 10px">原始回答不会被修改；勾选两版可并排对比。</p><div id="timeline"></div></div>
      ${q.concept_family.length > 1 ? h`<div class="card"><h2>同一概念的表现</h2><p class="muted tiny">原题、追问和情境题的最新得分，用来区分“会背”和“会用”。</p>
        <div class="list">${q.concept_family.map(c => h`<div class="item ${c.id === q.id ? 'active' : ''}" onclick="go('practice/${c.id}')"><div class="grow">
        <div class="title">${c.text}</div><div class="row tiny" style="margin-top:3px"><span class="badge ${c.origin === 'scenario' ? 'info' : ''}">${ORIGIN[c.origin] || c.origin}</span>
        ${c.difficulty ? h`<span class="badge">${c.difficulty}</span>` : ''}<span class="muted">${c.attempts} 次作答</span></div></div>${scoreBadge(c.latest_score)}</div>`)}</div></div>` : ''}
      ${q.related.length ? h`<div class="card"><h2>题库中的相关问题</h2><p class="muted tiny">按语义相似度找出，可能是面试官的追问方向；仅供参考，不作为评分依据。</p>
        <div class="list">${q.related.map(r => h`<div class="item" onclick="go('practice/${r.id}')"><div class="grow"><div class="title">${r.text}</div>
        <div class="row tiny" style="margin-top:3px"><span class="badge">${ORIGIN[r.origin] || r.origin}</span><span class="muted">相似度 ${r.similarity}</span></div></div></div>`)}</div></div>` : ''}
      ${q.eval_points ? h`<div class="card sunken"><h2>评分要点</h2><ul class="points">${q.eval_points.map(p => h`<li>${p}</li>`)}</ul></div>` : ''}
    </div>
  </div>`);
  renderHints(); renderTimeline(); showAttempt(S.sel);
}

function renderTimeline() {
  const q = S.q;
  set('#timeline', q.attempts.length ? h`<div class="timeline">${[...q.attempts].reverse().map(a => {
    const ev = a.evaluations.at(-1);
    return h`<div class="tl ${a.id === S.sel ? 'active' : ''}" onclick="showAttempt(${a.id})"><div class="row between">
      <b>v${a.version}</b><span class="row">${ev && ev.status === 'ok' ? h`<span class="badge ok">${avg(ev.scores)}</span>` : ev ? h`<span class="badge warn">${ev.status}</span>` : ''}
      <input type="checkbox" ${S.cmp.has(a.id) ? 'checked' : ''} onclick="event.stopPropagation(); toggleCmp(${a.id}, this.checked)"></span></div>
      <div class="muted tiny">${when(a.created_at)} · ${MODE[a.mode] || a.mode}</div><div class="tiny" style="margin-top:2px">${a.answer.slice(0, 60)}${a.answer.length > 60 ? '…' : ''}</div></div>`;
  })}</div>` : empty('暂无作答', '提交第一版讲解后会出现在这里。'));
}
function toggleCmp(id, on) { on ? S.cmp.add(id) : S.cmp.delete(id); }

function showAttempt(id) {
  S.sel = id; renderTimeline();
  const a = S.q.attempts.find(x => x.id === id);
  if (!a) return;
  $('#eval-card').hidden = false;
  set('#eval', h`<div class="row between"><h2 style="margin:0">v${a.version} 的评估</h2><span class="muted tiny">${when(a.created_at)}</span></div>
    <div class="card sunken pre" style="margin:10px 0 14px;padding:12px">${a.answer}</div>${evalView(a.evaluations.at(-1), { questionId: S.q.id })}`);
}

function compare() {
  const picked = S.q.attempts.filter(a => S.cmp.has(a.id));
  if (picked.length !== 2) return toast('请在作答历史中勾选两版', true);
  const [e1, e2] = picked.map(a => a.evaluations.at(-1) || {});
  const same = ['rubric_version', 'model', 'evidence_mode', 'history_aware'].every(k => e1[k] === e2[k]);
  $('#eval-card').hidden = false;
  set('#eval', h`<div class="row between"><h2 style="margin:0">版本对比</h2><button class="ghost sm" onclick="showAttempt(S.sel)">返回单版</button></div>
    ${same ? '' : h`<div class="notice warn" style="margin:8px 0">两版的评估条件（评分标准 / 模型 / 证据设置）不同，分数不能直接当作进步。</div>`}
    <div class="grid cols-2" style="margin-top:10px">${picked.map(a => h`<div><h3>v${a.version} · ${when(a.created_at)}</h3>
      <div class="card sunken pre" style="padding:12px;margin-bottom:10px">${a.answer}</div>${evalView(a.evaluations.at(-1), { compact: true, questionId: S.q.id })}</div>`)}</div>`);
}

async function submitAnswer(btn) {
  const answer = val('ans').trim();
  if (!answer) return toast('先写下你的讲解', true);
  await busy(btn, async () => {
    const r = await post(`/api/questions/${S.q.id}/attempts`, { answer, history_aware: $('#opt-hist').checked, evidence_mode: val('opt-ev') });
    await practiceDetail(S.q.id); showAttempt(r.attempt.id);
    $('#eval-card').scrollIntoView({ behavior: 'smooth' });
  });
}

async function deleteQuestion(id) {
  if (!confirm('删除该题目及其全部作答记录？')) return;
  await del('/api/questions/' + id); go('practice');
}

// hints (Ext 1)
const HINT_FB = { too_direct: '太直接', too_vague: '太模糊', just_right: '刚好' };
function renderHints() {
  const hs = [...S.q.hints].reverse();
  set('#hints', hs.length ? h`<div class="stack" style="margin-top:12px">${hs.map(x => h`<div class="evidence">
    <div class="pre">${x.text}</div><div class="row" style="margin-top:8px">
    <span class="muted tiny">${x.personalized ? '个性化 · 偏好 v' + x.pref_version : '通用'}</span><span class="spacer"></span>
    ${x.rating ? h`<span class="badge">${HINT_FB[x.rating]}${x.comment ? '：' + x.comment : ''}</span>` : h`
      <input id="hc-${x.id}" placeholder="补充说明（可选）" style="width:160px;padding:3px 8px;font-size:12.5px">
      ${Object.entries(HINT_FB).map(([k, v]) => h`<button class="sm" onclick="rateHint(this, ${x.id}, '${k}')">${v}</button>`)}`}</div></div>`)}</div>` : '');
}
async function askHint(btn) {
  await busy(btn, async () => {
    await post(`/api/questions/${S.q.id}/hint`, {});
    S.q.hints = (await api('/api/questions/' + S.q.id)).hints; renderHints();
  });
}
async function rateHint(btn, id, rating) {
  await busy(btn, async () => {
    const r = await post(`/api/hints/${id}/feedback`, { feedback: rating, comment: val('hc-' + id) });
    toast(`提示偏好已更新到 v${r.prefs.version}`);
    S.q.hints = (await api('/api/questions/' + S.q.id)).hints; renderHints();
  });
}

// scenarios (Ext 3)
async function makeScenario(btn, gapIds, qid = S.q && S.q.id) {
  await busy(btn, async () => {
    const r = await post(`/api/questions/${qid}/scenario`, { difficulty: $('#sc-diff') ? val('sc-diff') : '相当', gap_ids: gapIds });
    toast('已生成情境题'); go('practice/' + r.question_id);
  });
}

async function transcribeInto(input, target) {
  const f = input.files[0]; if (!f) return;
  const fd = new FormData(); fd.append('file', f);
  toast('本地转写中（首次需加载 SenseVoice 模型）…');
  const r = await api('/api/speech/transcribe', { method: 'POST', form: fd });
  const el = document.getElementById(target); el.value = (el.value ? el.value + '\n' : '') + r.transcript;
  toast('转写完成，可先编辑再提交'); input.value = '';
}

// ── mock interview ────────────────────────────────────────────────────
VIEWS.interview = async id => id ? interviewSession(+id) : interviewHome();

async function interviewHome() {
  const ss = await api('/api/interview/sessions');
  set(main, h`<div class="page-head"><div><h1>模拟面试</h1><p>AI 面试官依据你的资料出题、评估并决定追问或换题；问题和薄弱点会进入题库和学习记录（标注来自模拟面试）。</p></div></div>
  <div class="grid cols-side">
    <div class="card"><h2>开始新面试</h2><div class="stack">
      <label class="field"><span>题型</span>${seg('iv-kind', KIND, 'knowledge')}</label>
      <label class="field"><span>目标岗位 / 方向</span><input id="iv-role" placeholder="例如：后端工程师、管理咨询、高中物理教师"></label>
      <p class="muted tiny">领域：${S.domain ? S.domains.find(d => d.id == S.domain).name : '全部（可在左侧选择）'}</p>
      <div class="row end"><button class="primary" onclick="startInterview(this)">开始</button></div></div></div>
    <div class="card"><h2>历史会话</h2><div class="list">${ss.length ? ss.map(s => h`<div class="item" onclick="go('interview/${s.id}')"><div class="grow">
      <div class="title">${KIND[s.kind]}${s.role ? ' · ' + s.role : ''}</div><div class="row tiny muted">${when(s.created_at)} · ${s.answers} 次回答
      ${s.avg_score != null ? h`<span class="badge ok">${s.avg_score.toFixed(1)}</span>` : ''}${s.finished ? h`<span class="badge">已结束</span>` : h`<span class="badge accent">进行中</span>`}</div></div></div>`)
      : empty('还没有面试记录', '')}</div></div>
  </div>`);
}

async function startInterview(btn) {
  await busy(btn, async () => {
    const r = await post('/api/interview/start', { kind: segVal('iv-kind'), role: val('iv-role'), domain_id: domainId() });
    go('interview/' + r.session_id);
  });
}

async function interviewSession(id) {
  const s = await api('/api/interview/' + id);
  set(main, h`<div class="page-head"><div><a onclick="go('interview')" class="tiny">← 模拟面试</a>
    <h1 style="margin-top:4px">${KIND[s.kind]}面试${s.role ? ' · ' + s.role : ''}</h1></div>
    ${s.finished ? h`<span class="badge">已结束</span>` : h`<button onclick="endInterview(this, ${id})">结束并复盘</button>`}</div>
  <div style="max-width:820px">
    <div class="chat" id="chat">${s.turns.map(t => turnView(t))}</div>
    ${s.finished ? h`<div class="card"><h2>面试总结</h2><div class="pre">${s.summary}</div>
      ${s.gaps.length ? h`<h3>本次发现的薄弱点（待确认）</h3><div class="stack">${s.gaps.map(g => gapRow(g))}</div>` : ''}</div>`
    : h`<div class="composer"><div class="box"><textarea id="iv-ans" placeholder="输入你的回答…（⌘/Ctrl + Enter 发送）"></textarea>
      <div class="row"><label class="btn sm ghost" style="padding:3px 9px">🎙 录音转文字<input type="file" accept="audio/*" hidden onchange="transcribeInto(this, 'iv-ans')"></label>
      <span class="spacer"></span><button class="primary" id="iv-send" onclick="sendAnswer(this, ${id})">发送</button></div></div></div>`}
  </div>`);
  const ta = $('#iv-ans');
  if (ta) ta.onkeydown = e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) $('#iv-send').click(); };
  window.scrollTo(0, document.body.scrollHeight);
}

function turnView(t) {
  if (t.role === 'interviewer') return h`<div class="msg ai fade"><div class="who">面试官</div><div class="bubble">${t.content}</div></div>`;
  const ev = t.evaluation;
  return h`<div class="msg me fade"><div class="who" style="text-align:right">你</div><div class="bubble">${t.content}</div>
    ${ev ? h`<details style="margin-top:4px"><summary>${ev.status === 'ok' ? `评估 ${avg(ev.scores)} / 5` : '评估：' + ev.status}</summary>
      <div class="card flat" style="margin-top:6px">${evalView(ev, { questionId: t.question_id })}</div></details>` : ''}</div>`;
}

async function sendAnswer(btn, id) {
  const answer = val('iv-ans').trim(); if (!answer) return;
  await busy(btn, async () => { await post(`/api/interview/${id}/answer`, { answer }); await interviewSession(id); });
}
async function endInterview(btn, id) { await busy(btn, async () => { await post(`/api/interview/${id}/end`); await interviewSession(id); }); }

// ── speech reflection ─────────────────────────────────────────────────
VIEWS.speech = async () => {
  const rs = await api('/api/reflections');
  set(main, h`<div class="page-head"><div><h1>语音复盘</h1><p>上传真实面试或口头练习录音，本地 SenseVoice 转写；校对文字后再分析，薄弱点进入学习记录待确认。</p></div></div>
  <div class="grid cols-2">
    <div class="card"><h2>1 · 转写并校对</h2><div class="stack">
      <label class="btn" style="justify-content:center">选择录音文件（wav / mp3 / m4a …）<input type="file" accept="audio/*" hidden onchange="transcribeInto(this, 'sp-text')"></label>
      <textarea id="sp-text" rows="12" placeholder="转写结果会出现在这里，可直接粘贴文字。分析前请先校对。"></textarea>
      <div class="row"><select id="sp-kind" style="width:auto">${Object.entries(KIND).map(([k, v]) => h`<option value="${k}">${v}</option>`)}</select>
        <span class="spacer"></span><button class="primary" onclick="analyzeSpeech(this)">分析</button></div></div></div>
    <div class="card"><h2>2 · 复盘</h2><div id="sp-out">${empty('尚未分析', '左侧校对完文字后点击“分析”。')}</div></div>
  </div>
  <div class="card" style="margin-top:16px"><h2>已保存的复盘</h2>${rs.length ? rs.map(r => h`<details style="border-bottom:1px solid var(--border);padding:6px 0">
    <summary><b style="color:var(--text)">${r.title}</b>　${when(r.created_at)}</summary><div class="grid cols-2" style="padding:8px 0">
    <div class="pre tiny">${r.transcript}</div><div>${reflectionView(r.analysis)}<button class="ghost sm danger" onclick="delReflection(${r.id})">删除</button></div></div></details>`)
    : empty('暂无', '')}</div>`);
};

function reflectionView(a) {
  const list = (t, xs, cls) => xs && xs.length ? h`<h3>${t}</h3><ul class="points ${cls}">${xs.map(x => h`<li>${x}</li>`)}</ul>` : '';
  return h`<p class="pre">${a.summary}</p>${list('要点', a.key_points, 'ok')}${list('不足', a.weaknesses, 'warn')}${list('改进方向', a.improvements)}`;
}

async function analyzeSpeech(btn) {
  const transcript = val('sp-text').trim(); if (!transcript) return toast('没有可分析的文字', true);
  await busy(btn, async () => {
    S.reflection = { transcript, analysis: await post('/api/speech/reflect', { transcript, kind: val('sp-kind') }) };
    set('#sp-out', h`${reflectionView(S.reflection.analysis)}<div class="divider"></div><div class="row">
      <input id="sp-title" placeholder="标题（可选）"><button class="primary" onclick="saveReflection(this)">保存到学习记录</button></div>`);
  });
}
async function saveReflection(btn) {
  await busy(btn, async () => {
    await post('/api/reflections', { ...S.reflection, title: val('sp-title'), domain_id: domainId() });
    toast('已保存；不足已作为待确认薄弱点加入学习记录'); VIEWS.speech();
  });
}
async function delReflection(id) { if (confirm('删除这条复盘？')) { await del('/api/reflections/' + id); VIEWS.speech(); } }

// ── flashcards ────────────────────────────────────────────────────────
VIEWS.cards = async () => {
  const st = await api('/api/cards/stats');
  set(main, h`<div class="page-head"><div><h1>闪卡</h1><p>到期复习：评分决定下次复习时间（默认 SM-2，可选固定 1/3/7 天）；已掌握的卡片移出队列。</p></div></div>
  <div class="grid cols-4" style="margin-bottom:16px">${[['待复习', st.due], ['学习中', st.learning], ['已掌握', st.retired], ['全部', st.total], ['近 7 天复习', st.reviews_7d]]
    .map(([k, v]) => h`<div class="card stat"><b>${v || 0}</b><span>${k}</span></div>`)}</div>
  <div class="grid cols-side">
    <div class="card"><div id="review"></div></div>
    <div class="card"><div class="row between" style="margin-bottom:12px">${seg('fc-tab', { add: '新建', ai: 'AI 生成', io: '导入导出' }, 'add')}</div><div id="fc-pane"></div></div>
  </div>
  <div class="card" style="margin-top:16px"><div class="row between"><h2 style="margin:0">全部卡片</h2>
    <span class="row"><select id="fc-col" style="width:auto" onchange="loadCardList()"><option value="">全部集合</option>${st.collections.map(c => h`<option>${c.collection}</option>`)}</select>
    <button class="ghost sm danger" onclick="delCollection()">删除该集合</button></span></div><div id="fc-list" style="margin-top:8px"></div></div>`);
  $('#fc-tab').onchange = cardPane; cardPane(); nextCard(); loadCardList();
};

function cardPane() {
  const t = segVal('fc-tab');
  if (t === 'add') set('#fc-pane', h`<div class="stack"><label class="field"><span>问题</span><textarea id="c-q" rows="2"></textarea></label>
    <label class="field"><span>答案</span><textarea id="c-a" rows="3"></textarea></label>
    <div class="grid cols-2"><label class="field"><span>集合</span><input id="c-col" value="General"></label>
    <label class="field"><span>调度</span><select id="c-pol"><option value="sm2">SM-2</option><option value="fixed">固定 1/3/7 天</option></select></label></div>
    <div class="row end"><button class="primary" onclick="addCard(this)">添加</button></div></div>`);
  if (t === 'ai') set('#fc-pane', h`<div class="stack"><p class="muted tiny">从知识库中检索已审核资料，生成带出处的问答卡。</p>
    <label class="field"><span>主题</span><input id="g-topic" placeholder="例如：Redis 持久化"></label>
    <div class="grid cols-2"><label class="field"><span>数量</span><input id="g-n" type="number" value="5" min="1" max="20"></label>
    <label class="field"><span>集合</span><input id="g-col" value="AI生成"></label></div>
    <div class="row end"><button class="primary" onclick="genCards(this)">生成</button></div></div>`);
  if (t === 'io') set('#fc-pane', h`<div class="stack"><p class="muted tiny">CSV 每行：问题,答案[,集合]</p>
    <input type="file" id="imp" accept=".csv"><div class="row"><button onclick="importCards(this)">导入</button><span class="spacer"></span>
    <button onclick="exportCards()">导出 CSV</button></div></div>`);
}

async function nextCard() {
  const due = await api('/api/cards/due');
  if (!due.length) return set('#review', empty('今天没有待复习的卡片', '新建或生成卡片，或者稍后再来。'));
  const c = S.card = due[0];
  set('#review', h`<div class="row between"><h2 style="margin:0">复习</h2><span class="muted tiny">剩余 ${due.length} · ${c.collection} · ${c.policy === 'fixed' ? '固定间隔' : 'SM-2'}</span></div>
    <div class="flash"><div class="pre">${c.question}</div><div id="flash-a"></div></div>
    <textarea id="my-a" rows="2" placeholder="先写下你的回答（可选）"></textarea>
    <div class="row end" id="flash-btns" style="margin-top:10px"><button class="primary" onclick="reveal()">显示答案</button></div>`);
}
function reveal() {
  set('#flash-a', h`<div class="answer pre">${S.card.answer}</div>`);
  set('#flash-btns', h`${[['again', '重来'], ['hard', '困难'], ['good', '良好'], ['easy', '简单']].map(([k, v]) => h`<button onclick="rateCard('${k}')">${v}</button>`)}
    <span class="spacer"></span><button class="ghost" onclick="rateCard('retire')">已掌握，移出队列</button>`);
}
async function rateCard(rating) {
  const c = await post(`/api/cards/${S.card.id}/rate`, { rating, user_answer: val('my-a') });
  toast(c.status === 'retired' ? '已移出复习队列' : `下次复习：${when(c.due_at)}`); VIEWS.cards();
}
async function addCard(btn) {
  await busy(btn, async () => {
    await post('/api/cards', { question: val('c-q'), answer: val('c-a'), collection: val('c-col'), policy: val('c-pol'), domain_id: domainId() });
    toast('已添加'); VIEWS.cards();
  });
}
async function genCards(btn) {
  await busy(btn, async () => {
    const r = await post('/api/cards/generate', { topic: val('g-topic'), count: +val('g-n'), collection: val('g-col'), domain_id: domainId() });
    toast(`生成了 ${r.length} 张卡片`); VIEWS.cards();
  });
}
async function importCards(btn) {
  const f = $('#imp').files[0]; if (!f) return;
  const fd = new FormData(); fd.append('file', f);
  await busy(btn, async () => { const r = await api('/api/cards/import', { method: 'POST', form: fd }); toast(`导入 ${r.imported} 张`); VIEWS.cards(); });
}
async function exportCards() {
  const r = await fetch('/api/cards/export', { headers: { 'X-User': S.user } });
  const a = document.createElement('a'); a.href = URL.createObjectURL(await r.blob()); a.download = 'flashcards.csv'; a.click();
}
async function loadCardList() {
  const col = val('fc-col');
  const cs = await api('/api/cards' + (col ? '?collection=' + encodeURIComponent(col) : ''));
  set('#fc-list', cs.length ? h`<table><tr><th>问题</th><th>答案</th><th>集合</th><th>下次</th><th></th></tr>${cs.map(c => h`<tr>
    <td class="pre">${c.question}</td><td class="pre muted">${c.answer}</td><td><span class="badge">${c.collection}</span>${c.gap_id ? h` <span class="badge warn">薄弱点</span>` : ''}</td>
    <td class="tiny muted">${c.status === 'retired' ? '已掌握' : when(c.due_at)}</td>
    <td><button class="ghost sm" onclick="editCard(${c.id})">编辑</button><button class="ghost sm danger" onclick="delCard(${c.id})">删除</button></td></tr>`)}</table>`
    : empty('暂无卡片', ''));
  S.cards = cs;
}
async function editCard(id) {
  const c = S.cards.find(x => x.id === id);
  const question = prompt('问题', c.question); if (question === null) return;
  const answer = prompt('答案', c.answer); if (answer === null) return;
  await put('/api/cards/' + id, { question, answer }); loadCardList();
}
async function delCard(id) { if (confirm('删除这张卡片？')) { await del('/api/cards/' + id); VIEWS.cards(); } }
async function delCollection() {
  const col = val('fc-col'); if (!col) return toast('先选择一个集合', true);
  if (confirm(`删除集合「${col}」中的全部卡片？`)) { await del('/api/cards/collections/' + encodeURIComponent(col)); VIEWS.cards(); }
}

// ── knowledge base ────────────────────────────────────────────────────
VIEWS.kb = async () => {
  set(main, h`<div class="page-head"><div><h1>知识库</h1><p>参考资料。只有“已审核”的资料会作为评分证据；对检索结果的有用 / 没用反馈会调整该资料的优先级。</p></div>
    <button class="primary" onclick="kbEdit()">+ 添加资料</button></div>
  <div id="kb-editor"></div>
  <div class="grid cols-side">
    <div class="card"><div class="row"><input id="kb-q" placeholder="检索资料，例如：宕机时会丢多少数据" onkeydown="if(event.key==='Enter') kbSearch()">
      <button onclick="kbSearch()">检索</button></div>
      <div class="row between" style="margin-top:10px">${seg('kb-mode', { bm25: 'BM25', dense: '向量', hybrid: '混合', weighted: '混合 + 优先级' }, 'weighted')}
      <label class="check"><input type="checkbox" id="kb-rev">仅已审核</label></div>
      <div id="kb-results" style="margin-top:12px"></div></div>
    <div class="card"><h2>资料（<span id="kb-count">0</span>）</h2><div id="kb-list" class="list"></div></div>
  </div>`);
  $('#kb-mode').onchange = () => val('kb-q') && kbSearch();
  await kbList();
};

async function kbList() {
  const docs = await api('/api/kb/docs' + dq());
  set('#kb-count', docs.length);
  set('#kb-list', docs.length ? docs.map(d => h`<div class="item" onclick="kbEdit(${d.id})"><div class="grow">
    <div class="title">${d.title}</div><div class="row tiny" style="margin-top:3px">
    <span class="badge ${d.reviewed ? 'ok' : 'warn'}">${d.reviewed ? '已审核' : '未审核'}</span><span class="badge">P ${d.priority.toFixed(1)}</span>
    <span class="badge">v${d.version}</span>${d.topic ? h`<span class="badge">${d.topic}</span>` : ''}<span class="muted">${d.source}</span></div></div></div>`)
    : empty('知识库是空的', '添加笔记、面经或教材摘录，练习和面试的评估会引用它们。'));
}

async function kbEdit(id) {
  const d = id ? await api('/api/kb/docs/' + id) : { title: '', body: '', topic: '', source: '用户粘贴', priority: 2, reviewed: 0, domain_id: domainId() };
  set('#kb-editor', h`<div class="card fade" style="margin-bottom:16px"><div class="row between"><h2 style="margin:0">${id ? '编辑资料' : '添加资料'}</h2>
    ${id ? h`<span class="muted tiny">v${d.version} · 修改正文会生成新版本并重新索引</span>` : ''}</div><div class="stack" style="margin-top:12px">
    <div class="grid cols-2"><label class="field"><span>标题</span><input id="d-title" value="${d.title}"></label>
    <label class="field"><span>主题</span><input id="d-topic" value="${d.topic}" placeholder="如：Redis、经济学"></label></div>
    <div class="grid cols-4"><label class="field"><span>来源</span><input id="d-source" value="${d.source}"></label>
    <label class="field"><span>优先级 0–5</span><input id="d-pri" type="number" min="0" max="5" step="0.5" value="${d.priority}"></label>
    <label class="field"><span>领域</span><select id="d-domain"><option value="">未指定</option>${S.domains.map(x => h`<option value="${x.id}" ${x.id == d.domain_id ? 'selected' : ''}>${x.name}</option>`)}</select></label>
    <label class="field"><span>审核</span><label class="check" style="padding-top:8px"><input type="checkbox" id="d-rev" ${d.reviewed ? 'checked' : ''}>可作为评分证据</label></label></div>
    <label class="field"><span>正文（Markdown）</span><textarea id="d-body" rows="10" placeholder="粘贴笔记或面经。没有标题的面经会按问题自动拆分为小节。">${d.body}</textarea></label>
    <div class="row">${id ? h`<button class="ghost danger" onclick="kbDelete(${id})">删除</button>` : ''}<span class="spacer"></span>
    <button class="ghost" onclick="set('#kb-editor','')">取消</button><button class="primary" onclick="kbSave(this, ${id || 'null'})">保存</button></div></div></div>`);
  $('#d-title').focus();
}

async function kbSave(btn, id) {
  const body = { title: val('d-title') || '未命名', topic: val('d-topic'), source: val('d-source'), priority: +val('d-pri'),
    reviewed: $('#d-rev').checked, domain_id: val('d-domain') ? +val('d-domain') : null, body: val('d-body') };
  await busy(btn, async () => {
    if (id) await put('/api/kb/docs/' + id, body);
    else { const r = await post('/api/kb/docs', body); if (r.auto_structured) toast('已按问题自动拆分为小节'); }
    set('#kb-editor', ''); toast('已保存并索引'); kbList();
  });
}
async function kbDelete(id) { if (confirm('删除这份资料？')) { await del('/api/kb/docs/' + id); set('#kb-editor', ''); kbList(); } }

async function kbSearch() {
  const query = val('kb-q').trim(); if (!query) return;
  set('#kb-results', h`<span class="spin"></span>`);
  const r = await post('/api/kb/search', { query, mode: segVal('kb-mode'), reviewed_only: $('#kb-rev').checked, k: 5, domain_id: domainId() });
  set('#kb-results', h`<p class="muted tiny">${r.results.length} 条 · ${r.ms} ms</p><div class="stack">${r.results.length ? r.results.map(x => h`<div class="evidence">
    <div class="row between"><span><b>${x.title}</b> <span class="muted tiny">${x.heading}</span></span>
    <span class="row tiny"><span class="badge">base ${x.base_score}</span>${r.mode === 'weighted' ? h`<span class="badge accent">final ${x.final_score}</span>` : ''}
    <span class="badge">P ${x.priority.toFixed(1)}</span>${x.reviewed ? '' : h`<span class="badge warn">未审核</span>`}</span></div>
    <div class="snippet pre">${x.content}</div><div class="row end"><button class="ghost sm" onclick="kbFeedback(${x.doc_id}, true).then(kbSearch)">有用</button>
    <button class="ghost sm" onclick="kbFeedback(${x.doc_id}, false).then(kbSearch)">没用</button></div></div>`) : empty('没有结果', '')}</div>`);
}

// ── records: gaps, hint preferences, domains, usage, learner ──────────
VIEWS.records = async () => {
  const [prefs, usage] = await Promise.all([api('/api/prefs'), api('/api/usage')]);
  set(main, h`<div class="page-head"><div><h1>学习记录</h1><p>薄弱点、提示偏好、领域设置与用量。所有记录按学习者隔离。</p></div></div>
  <div class="grid cols-side">
    <div class="stack">
      <div class="card"><div class="row between" style="margin-bottom:10px"><h2 style="margin:0">薄弱点</h2>${seg('gap-tab', { 0: '待确认', 1: '已确认' }, '0')}</div><div id="gaps"></div><div id="gap-draft"></div></div>
      <div class="card"><h2>提示偏好 <span class="badge">v${prefs.current.version}</span> <span class="muted tiny">${prefs.current.source}</span></h2>
        <p class="muted tiny">由你对提示的反馈自动归纳，生成新提示时会使用。可直接编辑或重置（重置后旧反馈保留但不再使用）。</p>
        <textarea id="pref-text" rows="4">${prefs.current.summary}</textarea>
        <div class="row end" style="margin-top:8px"><button class="ghost" onclick="resetPrefs()">重置</button><button class="primary" onclick="savePrefs()">保存</button></div>
        <details style="margin-top:10px"><summary>反馈原文（${prefs.feedback.length}）与版本历史（${prefs.versions.length}）</summary>
          <table style="margin-top:6px">${prefs.feedback.map(f => h`<tr><td class="tiny muted">${when(f.feedback_at)}</td><td><span class="badge">${HINT_FB[f.rating]}</span></td>
            <td class="tiny">${f.comment}<div class="muted">${f.text.slice(0, 80)}</div></td></tr>`)}</table>
          <table style="margin-top:6px">${prefs.versions.map(v => h`<tr><td>v${v.version}</td><td class="tiny muted">${v.source} · ${when(v.created_at)}</td><td class="pre tiny">${v.summary || '（空）'}</td></tr>`)}</table>
        </details></div>
    </div>
    <div class="stack">
      <div class="card"><h2>领域</h2><p class="muted tiny">不限职业：为每个领域写下学习目标和额外评分标准，评估时会使用。</p><div id="domains" class="stack"></div>
        <details style="margin-top:8px"><summary>新建领域</summary>${domainForm({})}</details></div>
      <div class="card"><h2>用量</h2>${usage.length ? h`<table><tr><th>任务</th><th>调用</th><th>失败</th><th>tokens 入/出</th><th>费用 $</th><th>平均 ms</th></tr>
        ${usage.map(u => h`<tr><td>${u.task}</td><td>${u.calls}</td><td>${u.failures}</td><td class="tiny">${u.tokens_in || 0} / ${u.tokens_out || 0}</td><td class="tiny">${u.cost_usd || '—'}</td><td>${u.avg_ms}</td></tr>`)}</table>` : empty('暂无调用', '')}</div>
      <div class="card"><h2>学习者</h2><div class="row"><input id="who" value="${S.user}"><button onclick="switchUser()">切换</button></div>
        <p class="muted tiny" style="margin-top:8px">本地使用，无登录。分析时文本会发送到你在 .env 配置的模型服务。</p>
        <button class="danger" onclick="deleteMe()">删除「${S.user}」的全部数据</button></div>
    </div>
  </div>`);
  set('#domains', S.domains.map(d => h`<details><summary><b style="color:var(--text)">${d.name}</b></summary>${domainForm(d)}</details>`));
  $('#gap-tab').onchange = loadGaps; loadGaps();
};

const domainForm = d => h`<div class="stack" style="padding:8px 0"><input id="dn-${d.id || 'new'}" placeholder="名称，如：商科管理" value="${d.name || ''}">
  <textarea id="dg-${d.id || 'new'}" rows="2" placeholder="学习目标">${d.goals || ''}</textarea>
  <textarea id="dc-${d.id || 'new'}" rows="2" placeholder="额外评分标准，如：需结合真实案例">${d.criteria || ''}</textarea>
  <div class="row end">${d.id ? h`<button class="ghost sm danger" onclick="delDomain(${d.id})">删除</button>` : ''}<button class="sm primary" onclick="saveDomain(${d.id || 'null'})">保存</button></div></div>`;

async function saveDomain(id) {
  const k = id || 'new', body = { name: val('dn-' + k), goals: val('dg-' + k), criteria: val('dc-' + k) };
  if (!body.name) return toast('请填写名称', true);
  id ? await put('/api/domains/' + id, body) : await post('/api/domains', body);
  await loadDomains(); VIEWS.records(); toast('已保存');
}
async function delDomain(id) { if (confirm('删除该领域？（资料和题目保留）')) { await del('/api/domains/' + id); await loadDomains(); VIEWS.records(); } }

const GAP_ORIGIN = { interview: '模拟面试', reflection: '语音复盘', manual: '练习中标记' };
const gapRow = g => h`<div class="evidence row between" id="gap-${g.id}"><div class="grow"><div>${g.text}</div><div class="row tiny muted">
  <span class="badge">${GAP_ORIGIN[g.origin] || g.origin}</span>${g.question_id ? h`<a onclick="go('practice/${g.question_id}')">相关题目</a>` : ''}<span>${when(g.created_at)}</span></div></div>
  <div class="row">${g.confirmed ? h`<button class="sm" onclick="gapPractice(this, ${g.id})">去练习</button><button class="sm" onclick="gapDraft(this, ${g.id})">生成闪卡</button>
    ${g.question_id ? h`<button class="sm" onclick="makeScenario(this, [${g.id}], ${g.question_id})">情境题</button>` : ''}`
    : h`<button class="sm primary" onclick="gapConfirm(${g.id})">确认</button>`}<button class="ghost sm" onclick="gapDelete(${g.id})">忽略</button></div></div>`;

async function loadGaps() {
  const gs = await api('/api/gaps?confirmed=' + (segVal('gap-tab') === '1'));
  set('#gaps', gs.length ? h`<div class="stack">${gs.map(gapRow)}</div>` : empty('没有记录', '模拟面试、语音复盘和练习中的薄弱点会出现在这里。'));
}
async function gapPractice(btn, id) {
  await busy(btn, async () => go('practice/' + (await post(`/api/gaps/${id}/practice`)).question_id));
}
async function gapConfirm(id) { await put('/api/gaps/' + id, { confirmed: true }); $('#gap-' + id)?.remove(); toast('已确认'); }
async function gapDelete(id) { await del('/api/gaps/' + id); document.getElementById('gap-' + id)?.remove(); }
async function gapDraft(btn, id) {
  await busy(btn, async () => {
    const d = S.draft = await post(`/api/gaps/${id}/card-draft`);
    set('#gap-draft', h`<div class="card sunken fade" style="margin-top:12px"><h2>闪卡草稿（可编辑）</h2><div class="stack">
      <textarea id="gd-q" rows="2">${d.question}</textarea><textarea id="gd-a" rows="4">${d.answer}</textarea>
      <div class="row"><input id="gd-col" value="薄弱点"><button class="primary" onclick="saveDraft(this)">保存为闪卡</button></div></div></div>`);
  });
}
async function saveDraft(btn) {
  await busy(btn, async () => {
    await post('/api/cards', { ...S.draft, question: val('gd-q'), answer: val('gd-a'), collection: val('gd-col') });
    set('#gap-draft', ''); toast('已加入闪卡复习队列');
  });
}
async function savePrefs() { const p = await put('/api/prefs', { summary: val('pref-text') }); toast(`已保存为 v${p.version}`); VIEWS.records(); }
async function resetPrefs() { if (confirm('重置提示偏好？')) { await post('/api/prefs/reset'); VIEWS.records(); } }
function switchUser() { S.user = localStorage.user = val('who').trim() || 'default'; init(); }
async function deleteMe() {
  if (prompt(`输入 ${S.user} 确认删除其全部资料、作答、闪卡与记录`) !== S.user) return;
  await del('/api/me'); toast('已删除'); init();
}

// ── boot ──────────────────────────────────────────────────────────────
async function init() {
  await loadDomains();
  route();
  const hs = await api('/api/health').catch(() => null);
  if (hs) set('#health', h`索引 ${hs.index.split(' ')[0]} · 模型 ${hs.llm_model}`);
}
init();
