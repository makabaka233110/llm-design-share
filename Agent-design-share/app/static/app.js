/* 面壁 Mianbi — single-file vanilla UI. Every dynamic value goes through h`` (HTML-escaped). */

const S = { user: localStorage.user || 'default', domain: localStorage.domain || '', domains: [], health: null };
const main = document.getElementById('main');
const t = (k, v) => I18N.t(k, v);

// ── tiny helpers ──────────────────────────────────────────────────────
class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
const raw = s => new Raw(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = v => v instanceof Raw ? v.s : Array.isArray(v) ? v.map(fmt).join('') : (v === false || v == null) ? '' : esc(v);
const h = (str, ...vals) => raw(str.reduce((a, s, i) => a + s + (i < vals.length ? fmt(vals[i]) : ''), ''));
const tHtml = (key, slots) => raw(esc(t(key)).replace(/\{(\w+)\}/g, (_, k) => (k in slots ? fmt(slots[k]) : '')));
const $ = sel => document.querySelector(sel);
const val = id => document.getElementById(id).value;
const set = (el, html) => { (typeof el === 'string' ? $(el) : el).innerHTML = fmt(html); };
const when = iso => iso ? new Date(iso).toLocaleString(I18N.locale(), { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
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

const KINDS = ['knowledge', 'behavioral', 'case'];
const DIMS = ['correctness', 'coverage', 'reasoning', 'clarity'];
const HINT_FBS = ['too_direct', 'too_vague', 'just_right'];
const kindMap = () => Object.fromEntries(KINDS.map(k => [k, t('kind.' + k)]));
const kindLabel = k => t('kind.' + k);
const originLabel = k => (['manual', 'interview', 'scenario', 'reflection', 'eval'].includes(k) ? t('origin.' + k) : k);
const modeLabel = k => (['feynman', 'interview', 'scenario', 'eval'].includes(k) ? t('mode.' + k) : k);
const diffLabel = k => (['更简单', '相当', '更难'].includes(k) ? t('diff.' + k) : k);
const hintFbMap = () => Object.fromEntries(HINT_FBS.map(k => [k, t('hintFb.' + k)]));
const hintFbLabel = k => (HINT_FBS.includes(k) ? t('hintFb.' + k) : k);
const gapOriginLabel = k => (['interview', 'reflection', 'manual'].includes(k) ? t('gapOrigin.' + k) : k);
const evStatusLabel = s => (s === 'uncertain' || s === 'unavailable' ? t('evStatus.' + s) : s);

// same rule as agent.overall: a wrong core concept (correctness <= 2) caps the overall score
const avg = s => { if (!s) return null; const m = Object.values(s).reduce((a, b) => a + b, 0) / 4;
  return (s.correctness <= 2 ? Math.min(m, s.correctness) : m).toFixed(1); };
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
const NAV_KEYS = ['practice', 'interview', 'speech', 'cards', 'kb', 'records'];

function renderHealth() {
  if (S.health) set('#health', t('app.health', { index: S.health.index.split(' ')[0], model: S.health.llm_model }));
}

function renderDomainOptions() {
  set('#domain-select', [h`<option value="">${t('app.allDomains')}</option>`, ...S.domains.map(d =>
    h`<option value="${d.id}" ${d.id == S.domain ? 'selected' : ''}>${d.name}</option>`)]);
}

function applyChrome() {
  document.title = t('app.title');
  set('#brand-name', t('app.brand'));
  set('#brand-sub', t('app.sub'));
  set('#domain-label', t('app.domain'));
  set('#arch-link', t('app.arch'));
  $('#user-chip').title = t('app.switchUserTitle');
  document.querySelectorAll('#lang-switch button').forEach(b => b.classList.toggle('on', b.dataset.lang === I18N.lang));
  renderDomainOptions();
  renderHealth();
}

function switchLang(code) {
  if (code === I18N.lang) return;
  I18N.setLang(code);
  applyChrome();
  route();
}

function renderNav(active, due) {
  set('#nav', NAV_KEYS.map(k => h`<a href="#${k}" class="${k === active ? 'active' : ''}">
    <svg viewBox="0 0 24 24">${raw(ICON[k])}</svg>${t('nav.' + k)}${k === 'cards' && due ? h`<span class="badge accent">${due}</span>` : ''}</a>`));
  set('#user-name', S.user); set('#user-avatar', S.user[0].toUpperCase());
}

async function loadDomains() {
  S.domains = await api('/api/domains');
  if (S.domain && !S.domains.some(d => d.id == S.domain)) S.domain = '';
  renderDomainOptions();
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
  return h`<div class="stack" style="gap:6px">${DIMS.map(k => h`<div class="meter">
    <span class="muted">${t('dim.' + k)}</span><div class="bar"><i style="width:${scores[k] * 20}%"></i></div><b>${scores[k]}</b></div>`)}</div>`;
}

function evalView(ev, { questionId, compact = false } = {}) {
  if (!ev) return '';
  const fb = ev.feedback || {};
  const ids = Object.fromEntries((ev.evidence || []).map(e => [e.eid, e]));
  const chips = p => (p.evidence || []).map(e => h`<span class="eid" title="${ids[e] ? ids[e].title + ' / ' + ids[e].heading + '\n' + ids[e].snippet : ''}">${e}</span>`);
  const pts = (title, list, cls, gap) => list && list.length ? h`<h3>${title}</h3><ul class="points ${cls}">${list.map(p => h`<li>${p.text}${chips(p)}
      ${p.quote ? h`<span class="quote">“${p.quote}”</span>` : ''}
      ${gap ? h`<button class="ghost sm" data-text="${p.text}" onclick="markGap(this, ${questionId || 'null'})">${t('eval.markGap')}</button>` : ''}</li>`)}</ul>` : '';
  const strs = (title, list, cls) => list && list.length ? h`<h3>${title}</h3><ul class="points ${cls}">${list.map(s => h`<li>${s}</li>`)}</ul>` : '';
  let head;
  const grounded = (ev.evidence || []).length > 0;  // scored without any reviewed passage: say so, don't claim grounding
  if (ev.status === 'ok') head = h`<div class="row between"><b>${t('eval.overall', { score: avg(ev.scores) })}</b>${grounded
    ? h`<span class="badge ok">${t('eval.grounded')}</span>` : h`<span class="badge warn">${t('eval.ungrounded')}</span>`}</div>
    ${grounded ? '' : h`<div class="notice warn tiny" style="margin-top:8px">${ev.evidence_mode === 'none' ? t('eval.noEvProvided') : t('eval.noEvFound')}${I18N.lang === 'en' ? ' ' : ''}${t('eval.ungroundedNote')}</div>`}
    <div style="margin-top:10px">${meters(ev.scores)}</div>`;
  else if (ev.status === 'uncertain') head = h`<div class="notice warn"><b>${t('eval.uncertainTitle')}</b>　${fb.reason || ''}</div>`;
  else head = h`<div class="notice bad"><b>${t('eval.unavailableTitle')}</b>　${fb.reason || ''}</div>`;
  const calc = fb.calc && fb.calc.length ? h`<h3>${t('eval.calc')}</h3><ul class="points ${fb.calc.every(c => c.ok) ? 'ok' : 'bad'}">${fb.calc.map(c => h`<li>${c.expr} = <b>${c.value}</b>
      <span class="muted tiny">${t('eval.calcClaim', { claimed: c.claimed, result: c.ok ? t('eval.calcOk') : t('eval.calcWrong') })}</span></li>`)}</ul>` : '';
  return h`<div class="fade">${head}${calc}
    ${pts(t('eval.strengths'), fb.strengths, 'ok')}${pts(t('eval.omissions'), fb.omissions, 'warn', true)}${pts(t('eval.misconceptions'), fb.misconceptions, 'bad', true)}
    ${strs(t('eval.revisions'), fb.revisions)}${strs(t('eval.recurring'), fb.recurring, 'bad')}${strs(t('eval.resolved'), fb.resolved, 'ok')}
    ${!compact && ev.evidence && ev.evidence.length ? h`<h3>${t('eval.evidence')}</h3><div class="stack">${ev.evidence.map(e => h`<div class="evidence">
      <div class="row between"><span><span class="eid">${e.eid}</span> <b>${e.title}</b> <span class="muted tiny">${e.heading} · v${e.version}</span></span>
      <span class="row"><button class="ghost sm" onclick="kbFeedback(${e.doc_id}, true)">${t('eval.helpful')}</button><button class="ghost sm" onclick="kbFeedback(${e.doc_id}, false)">${t('eval.unhelpful')}</button></span></div>
      ${e.claim ? h`<div class="tiny" style="color:var(--info)">${t('eval.checkClaim', { claim: e.claim })}</div>` : ''}
      <div class="snippet">${e.snippet}</div></div>`)}</div>` : ''}
    <p class="muted tiny" style="margin-top:12px">${t('eval.meta', { rubric: ev.rubric_version, model: ev.model || '—', mode: ev.evidence_mode })}${ev.history_aware ? t('eval.metaHistory') : ''}</p></div>`;
}

async function markGap(btn, questionId) {
  await busy(btn, async () => {
    await post('/api/gaps', { text: btn.dataset.text, question_id: questionId, domain_id: domainId() });
    btn.textContent = t('eval.markedGap'); btn.disabled = true; toast(t('eval.toastGapAdded'));
  });
}
async function kbFeedback(docId, helpful) {
  const r = await post('/api/kb/feedback', { doc_id: docId, helpful });
  toast(t('eval.toastPriority', { old: r.old_priority, new: r.new_priority }));
}

// ── practice (Feynman) ────────────────────────────────────────────────
VIEWS.practice = async id => id ? practiceDetail(+id) : practiceList();

async function practiceList() {
  set(main, h`<div class="page-head"><div><h1>${t('practice.title')}</h1><p>${t('practice.desc')}</p></div></div>
  <div class="grid cols-side">
    <div class="card"><div class="row between" style="margin-bottom:10px"><h2 style="margin:0">${t('practice.bank')}</h2>
      ${seg('q-origin', { '': t('practice.seg.all'), manual: t('practice.seg.manual'), interview: t('practice.seg.interview'), scenario: t('practice.seg.scenario'), concept: t('practice.seg.concept') }, '')}</div><div id="q-list" class="list"></div></div>
    <div class="card"><h2>${t('practice.newTitle')}</h2><div class="stack">
      <label class="field"><span>${t('practice.qLabel')}</span><textarea id="q-text" rows="3" placeholder="${t('practice.qPh')}"></textarea></label>
      <div class="grid cols-2"><label class="field"><span>${t('practice.conceptLabel')}</span><input id="q-concept" placeholder="${t('practice.conceptPh')}"></label>
      <label class="field"><span>${t('practice.kindLabel')}</span><select id="q-kind">${Object.entries(kindMap()).map(([k, v]) => h`<option value="${k}">${v}</option>`)}</select></label></div>
      <div class="row end"><button class="primary" onclick="createQuestion(this)">${t('practice.startBtn')}</button></div></div></div>
  </div>`);
  $('#q-origin').onchange = loadQuestions;
  await loadQuestions();
}

const scoreBadge = s => s == null ? h`<span class="badge">${t('practice.unscored')}</span>` : h`<span class="badge ${s >= 4 ? 'ok' : s >= 3 ? '' : 'warn'}">${s}</span>`;

async function loadConcepts() {
  const gs = await api('/api/concepts' + dq());
  set('#q-list', gs.length ? h`<p class="muted tiny">${t('practice.conceptsHint')}</p>${gs.map(g => h`
    <div class="evidence" style="margin-bottom:10px"><div class="row between"><b>${g.concept}</b>${scoreBadge(g.avg)}</div>
    <div class="stack" style="gap:4px;margin-top:6px">${g.questions.map(q => h`<div class="row tiny" style="cursor:pointer" onclick="go('practice/${q.id}')">
      <span class="badge ${q.origin === 'scenario' ? 'info' : q.origin === 'interview' ? 'accent' : ''}">${originLabel(q.origin)}</span>
      <span class="grow" style="flex:1">${q.text.slice(0, 50)}</span>${scoreBadge(q.latest_score)}</div>`)}</div></div>`)}`
    : empty(t('practice.noConceptsTitle'), t('practice.noConceptsHint')));
}

async function loadQuestions() {
  const origin = segVal('q-origin');
  if (origin === 'concept') return loadConcepts();
  const qs = await api('/api/questions?' + [origin && `origin=${origin}`, dq('')].filter(Boolean).join('&'));
  set('#q-list', qs.length ? qs.map(q => h`<div class="item" onclick="go('practice/${q.id}')"><div class="grow">
    <div class="title">${q.text}</div><div class="row tiny" style="margin-top:4px">
    <span class="badge ${q.origin === 'scenario' ? 'info' : q.origin === 'interview' ? 'accent' : ''}">${originLabel(q.origin)}</span>
    ${q.concept ? h`<span class="badge">${q.concept}</span>` : ''}<span class="muted">${t('practice.attemptsCount', { n: q.attempts })}</span></div></div></div>`)
    : empty(t('practice.emptyTitle'), t('practice.emptyHint')));
}

async function createQuestion(btn) {
  if (!val('q-text').trim()) return toast(t('practice.toastEnterQ'), true);
  await busy(btn, async () => {
    const q = await post('/api/questions', { text: val('q-text'), concept: val('q-concept'), kind: val('q-kind'), domain_id: domainId() });
    go('practice/' + q.id);
  });
}

async function practiceDetail(id) {
  const q = S.q = await api('/api/questions/' + id);
  const last = q.attempts[q.attempts.length - 1];
  S.sel = last ? last.id : null; S.cmp = new Set();
  set(main, h`<div class="page-head"><div><a onclick="go('practice')" class="tiny">${t('practice.backBank')}</a></div></div>
  <div class="grid cols-side">
    <div class="stack">
      <div class="card"><div class="row" style="margin-bottom:8px"><span class="badge">${kindLabel(q.kind)}</span>
        <span class="badge ${q.origin === 'scenario' ? 'info' : ''}">${originLabel(q.origin)}</span>
        ${q.concept ? h`<span class="badge accent">${q.concept}</span>` : ''}${q.difficulty ? h`<span class="badge">${t('practice.diffBadge', { d: diffLabel(q.difficulty) })}</span>` : ''}
        <span class="spacer"></span><button class="ghost sm danger" onclick="deleteQuestion(${q.id})">${t('practice.delete')}</button></div>
        <div style="font-size:16px;font-weight:500" class="pre">${q.text}</div>
        ${q.context ? h`<div class="notice info" style="margin-top:10px">${q.context}</div>` : ''}
        ${q.parent ? h`<p class="tiny muted" style="margin-top:10px">${tHtml('practice.fromParent', { link: h`<a onclick="go('practice/${q.parent.id}')">${q.parent.text.slice(0, 40)}</a>` })}</p>` : ''}
        <div class="divider"></div>
        <div class="row"><button onclick="askHint(this)">${t('practice.hintBtn')}</button>
          <span class="spacer"></span><select id="sc-diff" style="width:auto"><option value="更简单">${diffLabel('更简单')}</option><option value="相当" selected>${diffLabel('相当')}</option><option value="更难">${diffLabel('更难')}</option></select>
          <button onclick="makeScenario(this, [])">${t('practice.scenarioBtn')}</button></div>
        <div id="hints"></div></div>
      <div class="card"><h2>${q.attempts.length ? t('practice.explainAgain') : t('practice.explainFirst')}</h2><div class="stack">
        <textarea id="ans" rows="6" placeholder="${t('practice.ansPh')}"></textarea>
        <div class="row">${last ? h`<button class="ghost sm" onclick="document.getElementById('ans').value = S.q.attempts.at(-1).answer">${t('practice.copyLast')}</button>` : ''}
          <label class="btn sm" style="padding:3px 9px">${t('practice.asrBtn')}<input type="file" accept="audio/*" hidden onchange="transcribeInto(this, 'ans')"></label>
          <span class="spacer"></span>
          <details><summary>${t('practice.evalOpts')}</summary><div class="stack" style="padding:8px 0">
            <label class="check"><input type="checkbox" id="opt-hist" checked>${t('practice.useHistory')}</label>
            <label class="field"><span>${t('practice.evLabel')}</span><select id="opt-ev"><option value="weighted">${t('practice.evWeighted')}</option><option value="hybrid">${t('practice.evHybrid')}</option><option value="none">${t('practice.evNone')}</option></select></label></div></details>
          <button class="primary" onclick="submitAnswer(this)">${t('practice.submitBtn')}</button></div></div></div>
      <div class="card" id="eval-card" ${q.attempts.length ? '' : 'hidden'}><div id="eval"></div></div>
    </div>
    <div class="stack">
      <div class="card"><div class="row between"><h2 style="margin:0">${t('practice.historyTitle')}</h2><button class="sm" onclick="compare()">${t('practice.compareBtn')}</button></div>
        <p class="muted tiny" style="margin:4px 0 10px">${t('practice.historyHint')}</p><div id="timeline"></div></div>
      ${q.concept_family.length > 1 ? h`<div class="card"><h2>${t('practice.familyTitle')}</h2><p class="muted tiny">${t('practice.familyHint')}</p>
        <div class="list">${q.concept_family.map(c => h`<div class="item ${c.id === q.id ? 'active' : ''}" onclick="go('practice/${c.id}')"><div class="grow">
        <div class="title">${c.text}</div><div class="row tiny" style="margin-top:3px"><span class="badge ${c.origin === 'scenario' ? 'info' : ''}">${originLabel(c.origin)}</span>
        ${c.difficulty ? h`<span class="badge">${diffLabel(c.difficulty)}</span>` : ''}<span class="muted">${t('practice.attemptsCount', { n: c.attempts })}</span></div></div>${scoreBadge(c.latest_score)}</div>`)}</div></div>` : ''}
      ${q.related.length ? h`<div class="card"><h2>${t('practice.relatedTitle')}</h2><p class="muted tiny">${t('practice.relatedHint')}</p>
        <div class="list">${q.related.map(r => h`<div class="item" onclick="go('practice/${r.id}')"><div class="grow"><div class="title">${r.text}</div>
        <div class="row tiny" style="margin-top:3px"><span class="badge">${originLabel(r.origin)}</span><span class="muted">${t('practice.similarity', { s: r.similarity })}</span></div></div></div>`)}</div></div>` : ''}
      ${q.eval_points ? h`<div class="card sunken"><h2>${t('practice.evalPoints')}</h2><ul class="points">${q.eval_points.map(p => h`<li>${p}</li>`)}</ul></div>` : ''}
    </div>
  </div>`);
  renderHints(); renderTimeline(); showAttempt(S.sel);
}

function renderTimeline() {
  const q = S.q;
  set('#timeline', q.attempts.length ? h`<div class="timeline">${[...q.attempts].reverse().map(a => {
    const ev = a.evaluations.at(-1);
    return h`<div class="tl ${a.id === S.sel ? 'active' : ''}" onclick="showAttempt(${a.id})"><div class="row between">
      <b>v${a.version}</b><span class="row">${ev && ev.status === 'ok' ? h`<span class="badge ok">${avg(ev.scores)}</span>` : ev ? h`<span class="badge warn">${evStatusLabel(ev.status)}</span>` : ''}
      <input type="checkbox" ${S.cmp.has(a.id) ? 'checked' : ''} onclick="event.stopPropagation(); toggleCmp(${a.id}, this.checked)"></span></div>
      <div class="muted tiny">${when(a.created_at)} · ${modeLabel(a.mode)}</div><div class="tiny" style="margin-top:2px">${a.answer.slice(0, 60)}${a.answer.length > 60 ? '…' : ''}</div></div>`;
  })}</div>` : empty(t('practice.noAttemptsTitle'), t('practice.noAttemptsHint')));
}
function toggleCmp(id, on) { on ? S.cmp.add(id) : S.cmp.delete(id); }

function showAttempt(id) {
  S.sel = id; renderTimeline();
  const a = S.q.attempts.find(x => x.id === id);
  if (!a) return;
  $('#eval-card').hidden = false;
  set('#eval', h`<div class="row between"><h2 style="margin:0">${t('practice.evalOfVer', { v: a.version })}</h2><span class="muted tiny">${when(a.created_at)}</span></div>
    <div class="card sunken pre" style="margin:10px 0 14px;padding:12px">${a.answer}</div>${evalView(a.evaluations.at(-1), { questionId: S.q.id })}`);
}

function compare() {
  const picked = S.q.attempts.filter(a => S.cmp.has(a.id));
  if (picked.length !== 2) return toast(t('practice.toastPickTwo'), true);
  const [e1, e2] = picked.map(a => a.evaluations.at(-1) || {});
  const same = ['rubric_version', 'model', 'evidence_mode', 'history_aware'].every(k => e1[k] === e2[k]);
  $('#eval-card').hidden = false;
  set('#eval', h`<div class="row between"><h2 style="margin:0">${t('practice.compareTitle')}</h2><button class="ghost sm" onclick="showAttempt(S.sel)">${t('practice.backSingle')}</button></div>
    ${same ? '' : h`<div class="notice warn" style="margin:8px 0">${t('practice.compareWarn')}</div>`}
    <div class="grid cols-2" style="margin-top:10px">${picked.map(a => h`<div><h3>v${a.version} · ${when(a.created_at)}</h3>
      <div class="card sunken pre" style="padding:12px;margin-bottom:10px">${a.answer}</div>${evalView(a.evaluations.at(-1), { compact: true, questionId: S.q.id })}</div>`)}</div>`);
}

async function submitAnswer(btn) {
  const answer = val('ans').trim();
  if (!answer) return toast(t('practice.toastEnterAns'), true);
  await busy(btn, async () => {
    const r = await post(`/api/questions/${S.q.id}/attempts`, { answer, history_aware: $('#opt-hist').checked, evidence_mode: val('opt-ev') });
    await practiceDetail(S.q.id); showAttempt(r.attempt.id);
    $('#eval-card').scrollIntoView({ behavior: 'smooth' });
  });
}

async function deleteQuestion(id) {
  if (!confirm(t('practice.confirmDelete'))) return;
  await del('/api/questions/' + id); go('practice');
}

// hints (Ext 1)
function renderHints() {
  const hs = [...S.q.hints].reverse();
  set('#hints', hs.length ? h`<div class="stack" style="margin-top:12px">${hs.map(x => h`<div class="evidence">
    <div class="pre">${x.text}</div><div class="row" style="margin-top:8px">
    <span class="muted tiny">${x.personalized ? t('practice.hintPers', { v: x.pref_version }) : t('practice.hintGen')}</span><span class="spacer"></span>
    ${x.rating ? h`<span class="badge">${hintFbLabel(x.rating)}${x.comment ? '：' + x.comment : ''}</span>` : h`
      <input id="hc-${x.id}" placeholder="${t('practice.hintCommentPh')}" style="width:160px;padding:3px 8px;font-size:12.5px">
      ${Object.entries(hintFbMap()).map(([k, v]) => h`<button class="sm" onclick="rateHint(this, ${x.id}, '${k}')">${v}</button>`)}`}</div></div>`)}</div>` : '');
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
    toast(t('practice.toastPrefUpdated', { v: r.prefs.version }));
    S.q.hints = (await api('/api/questions/' + S.q.id)).hints; renderHints();
  });
}

// scenarios (Ext 3)
async function makeScenario(btn, gapIds, qid = S.q && S.q.id) {
  await busy(btn, async () => {
    const r = await post(`/api/questions/${qid}/scenario`, { difficulty: $('#sc-diff') ? val('sc-diff') : '相当', gap_ids: gapIds });
    toast(t('practice.toastScenarioDone')); go('practice/' + r.question_id);
  });
}

async function transcribeInto(input, target) {
  const f = input.files[0]; if (!f) return;
  const fd = new FormData(); fd.append('file', f);
  toast(t('practice.toastAsrStart'));
  const r = await api('/api/speech/transcribe', { method: 'POST', form: fd });
  const el = document.getElementById(target); el.value = (el.value ? el.value + '\n' : '') + r.transcript;
  toast(t('practice.toastAsrDone')); input.value = '';
}

// ── mock interview ────────────────────────────────────────────────────
VIEWS.interview = async id => id ? interviewSession(+id) : interviewHome();

async function interviewHome() {
  const ss = await api('/api/interview/sessions');
  const dObj = S.domain ? S.domains.find(d => d.id == S.domain) : null;
  set(main, h`<div class="page-head"><div><h1>${t('iv.title')}</h1><p>${t('iv.desc')}</p></div></div>
  <div class="grid cols-side">
    <div class="card"><h2>${t('iv.newTitle')}</h2><div class="stack">
      <label class="field"><span>${t('iv.kindLabel')}</span>${seg('iv-kind', kindMap(), 'knowledge')}</label>
      <label class="field"><span>${t('iv.roleLabel')}</span><input id="iv-role" placeholder="${t('iv.rolePh')}"></label>
      <p class="muted tiny">${t('iv.domainLine', { name: dObj ? dObj.name : t('iv.allSidebar') })}</p>
      <div class="row end"><button class="primary" onclick="startInterview(this)">${t('iv.startBtn')}</button></div></div></div>
    <div class="card"><h2>${t('iv.sessionsTitle')}</h2><div class="list">${ss.length ? ss.map(s => h`<div class="item" onclick="go('interview/${s.id}')"><div class="grow">
      <div class="title">${kindLabel(s.kind)}${s.role ? ' · ' + s.role : ''}</div><div class="row tiny muted">${when(s.created_at)} · ${t('iv.answersCount', { n: s.answers })}
      ${s.avg_score != null ? h`<span class="badge ok">${s.avg_score.toFixed(1)}</span>` : ''}${s.finished ? h`<span class="badge">${t('iv.finished')}</span>` : h`<span class="badge accent">${t('iv.ongoing')}</span>`}</div></div></div>`)
      : empty(t('iv.empty'), '')}</div></div>
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
  set(main, h`<div class="page-head"><div><a onclick="go('interview')" class="tiny">${t('iv.back')}</a>
    <h1 style="margin-top:4px">${t('iv.sessionHeading', { kind: kindLabel(s.kind), role: s.role ? ' · ' + s.role : '' })}</h1></div>
    ${s.finished ? h`<span class="badge">${t('iv.finished')}</span>` : h`<button onclick="endInterview(this, ${id})">${t('iv.endBtn')}</button>`}</div>
  <div style="max-width:820px">
    <div class="chat" id="chat">${s.turns.map(x => turnView(x))}</div>
    ${s.finished ? h`<div class="card"><h2>${t('iv.summaryTitle')}</h2><div class="pre">${s.summary}</div>
      ${s.gaps.length ? h`<h3>${t('iv.gapsTitle')}</h3><div class="stack">${s.gaps.map(g => gapRow(g))}</div>` : ''}</div>`
    : h`<div class="composer"><div class="box"><textarea id="iv-ans" placeholder="${t('iv.ansPh')}"></textarea>
      <div class="row"><label class="btn sm ghost" style="padding:3px 9px">${t('practice.asrBtn')}<input type="file" accept="audio/*" hidden onchange="transcribeInto(this, 'iv-ans')"></label>
      <span class="spacer"></span><button class="primary" id="iv-send" onclick="sendAnswer(this, ${id})">${t('iv.sendBtn')}</button></div></div></div>`}
  </div>`);
  const ta = $('#iv-ans');
  if (ta) ta.onkeydown = e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) $('#iv-send').click(); };
  window.scrollTo(0, document.body.scrollHeight);
}

function turnView(turn) {
  if (turn.role === 'interviewer') return h`<div class="msg ai fade"><div class="who">${t('iv.interviewer')}</div><div class="bubble">${turn.content}</div></div>`;
  const ev = turn.evaluation;
  return h`<div class="msg me fade"><div class="who" style="text-align:right">${t('iv.you')}</div><div class="bubble">${turn.content}</div>
    ${ev ? h`<details style="margin-top:4px"><summary>${ev.status === 'ok' ? t('iv.evalOk', { score: avg(ev.scores) }) : ev.status === 'uncertain' ? t('iv.evalUncertain') : t('iv.evalUnavailable')}</summary>
      <div class="card flat" style="margin-top:6px">${evalView(ev, { questionId: turn.question_id })}</div></details>` : ''}</div>`;
}

async function sendAnswer(btn, id) {
  const answer = val('iv-ans').trim(); if (!answer) return;
  await busy(btn, async () => { await post(`/api/interview/${id}/answer`, { answer }); await interviewSession(id); });
}
async function endInterview(btn, id) { await busy(btn, async () => { await post(`/api/interview/${id}/end`); await interviewSession(id); }); }

// ── speech reflection ─────────────────────────────────────────────────
VIEWS.speech = async () => {
  const rs = await api('/api/reflections');
  set(main, h`<div class="page-head"><div><h1>${t('sp.title')}</h1><p>${t('sp.desc')}</p></div></div>
  <div class="grid cols-2">
    <div class="card"><h2>${t('sp.step1')}</h2><div class="stack">
      <label class="btn" style="justify-content:center">${t('sp.pickAudio')}<input type="file" accept="audio/*" hidden onchange="transcribeInto(this, 'sp-text')"></label>
      <textarea id="sp-text" rows="12" placeholder="${t('sp.textPh')}"></textarea>
      <div class="row"><select id="sp-kind" style="width:auto">${Object.entries(kindMap()).map(([k, v]) => h`<option value="${k}">${v}</option>`)}</select>
        <span class="spacer"></span><button class="primary" onclick="analyzeSpeech(this)">${t('sp.analyzeBtn')}</button></div></div></div>
    <div class="card"><h2>${t('sp.step2')}</h2><div id="sp-out">${empty(t('sp.emptyTitle'), t('sp.emptyHint'))}</div></div>
  </div>
  <div class="card" style="margin-top:16px"><h2>${t('sp.savedTitle')}</h2>${rs.length ? rs.map(r => h`<details style="border-bottom:1px solid var(--border);padding:6px 0">
    <summary><b style="color:var(--text)">${r.title}</b>　${when(r.created_at)}</summary><div class="grid cols-2" style="padding:8px 0">
    <div class="pre tiny">${r.transcript}</div><div>${reflectionView(r.analysis)}<button class="ghost sm danger" onclick="delReflection(${r.id})">${t('practice.delete')}</button></div></div></details>`)
    : empty(t('sp.none'), '')}</div>`);
};

function reflectionView(a) {
  const list = (title, xs, cls) => xs && xs.length ? h`<h3>${title}</h3><ul class="points ${cls}">${xs.map(x => h`<li>${x}</li>`)}</ul>` : '';
  return h`<p class="pre">${a.summary}</p>${list(t('sp.keyPoints'), a.key_points, 'ok')}${list(t('sp.weaknesses'), a.weaknesses, 'warn')}${list(t('sp.improvements'), a.improvements)}`;
}

async function analyzeSpeech(btn) {
  const transcript = val('sp-text').trim(); if (!transcript) return toast(t('sp.toastNoText'), true);
  await busy(btn, async () => {
    S.reflection = { transcript, analysis: await post('/api/speech/reflect', { transcript, kind: val('sp-kind') }) };
    set('#sp-out', h`${reflectionView(S.reflection.analysis)}<div class="divider"></div><div class="row">
      <input id="sp-title" placeholder="${t('sp.titlePh')}"><button class="primary" onclick="saveReflection(this)">${t('sp.saveBtn')}</button></div>`);
  });
}
async function saveReflection(btn) {
  await busy(btn, async () => {
    await post('/api/reflections', { ...S.reflection, title: val('sp-title'), domain_id: domainId() });
    toast(t('sp.toastSaved')); VIEWS.speech();
  });
}
async function delReflection(id) { if (confirm(t('sp.confirmDel'))) { await del('/api/reflections/' + id); VIEWS.speech(); } }

// ── flashcards ────────────────────────────────────────────────────────
VIEWS.cards = async () => {
  const st = await api('/api/cards/stats');
  set(main, h`<div class="page-head"><div><h1>${t('fc.title')}</h1><p>${t('fc.desc')}</p></div></div>
  <div class="grid cols-4" style="margin-bottom:16px">${[[t('fc.stat.due'), st.due], [t('fc.stat.learning'), st.learning], [t('fc.stat.retired'), st.retired], [t('fc.stat.total'), st.total], [t('fc.stat.rev7d'), st.reviews_7d]]
    .map(([k, v]) => h`<div class="card stat"><b>${v || 0}</b><span>${k}</span></div>`)}</div>
  <div class="grid cols-side">
    <div class="card"><div id="review"></div></div>
    <div class="card"><div class="row between" style="margin-bottom:12px">${seg('fc-tab', { add: t('fc.tab.add'), ai: t('fc.tab.ai'), io: t('fc.tab.io') }, 'add')}</div><div id="fc-pane"></div></div>
  </div>
  <div class="card" style="margin-top:16px"><div class="row between"><h2 style="margin:0">${t('fc.allCards')}</h2>
    <span class="row"><select id="fc-col" style="width:auto" onchange="loadCardList()"><option value="">${t('fc.allCols')}</option>${st.collections.map(c => h`<option>${c.collection}</option>`)}</select>
    <button class="ghost sm danger" onclick="delCollection()">${t('fc.delCol')}</button></span></div><div id="fc-list" style="margin-top:8px"></div></div>`);
  $('#fc-tab').onchange = cardPane; cardPane(); nextCard(); loadCardList();
};

function cardPane() {
  const tab = segVal('fc-tab');
  if (tab === 'add') set('#fc-pane', h`<div class="stack"><label class="field"><span>${t('fc.q')}</span><textarea id="c-q" rows="2"></textarea></label>
    <label class="field"><span>${t('fc.a')}</span><textarea id="c-a" rows="3"></textarea></label>
    <div class="grid cols-2"><label class="field"><span>${t('fc.col')}</span><input id="c-col" value="General"></label>
    <label class="field"><span>${t('fc.policy')}</span><select id="c-pol"><option value="sm2">SM-2</option><option value="fixed">${t('fc.fixedLabel')}</option></select></label></div>
    <div class="row end"><button class="primary" onclick="addCard(this)">${t('fc.addBtn')}</button></div></div>`);
  if (tab === 'ai') set('#fc-pane', h`<div class="stack"><p class="muted tiny">${t('fc.aiHint')}</p>
    <label class="field"><span>${t('fc.topic')}</span><input id="g-topic" placeholder="${t('fc.topicPh')}"></label>
    <div class="grid cols-2"><label class="field"><span>${t('fc.count')}</span><input id="g-n" type="number" value="5" min="1" max="20"></label>
    <label class="field"><span>${t('fc.col')}</span><input id="g-col" value="${t('fc.defaultAiCol')}"></label></div>
    <div class="row end"><button class="primary" onclick="genCards(this)">${t('fc.genBtn')}</button></div></div>`);
  if (tab === 'io') set('#fc-pane', h`<div class="stack"><p class="muted tiny">${t('fc.csvHint')}</p>
    <input type="file" id="imp" accept=".csv"><div class="row"><button onclick="importCards(this)">${t('fc.importBtn')}</button><span class="spacer"></span>
    <button onclick="exportCards()">${t('fc.exportBtn')}</button></div></div>`);
}

async function nextCard() {
  const due = await api('/api/cards/due');
  if (!due.length) return set('#review', empty(t('fc.noDueTitle'), t('fc.noDueHint')));
  const c = S.card = due[0];
  set('#review', h`<div class="row between"><h2 style="margin:0">${t('fc.review')}</h2><span class="muted tiny">${t('fc.left', { n: due.length })} · ${c.collection} · ${c.policy === 'fixed' ? t('fc.fixedShort') : 'SM-2'}</span></div>
    <div class="flash"><div class="pre">${c.question}</div><div id="flash-a"></div></div>
    <textarea id="my-a" rows="2" placeholder="${t('fc.myAnsPh')}"></textarea>
    <div class="row end" id="flash-btns" style="margin-top:10px"><button class="primary" onclick="reveal()">${t('fc.revealBtn')}</button></div>`);
}
function reveal() {
  set('#flash-a', h`<div class="answer pre">${S.card.answer}</div>`);
  set('#flash-btns', h`${[['again', t('fc.rate.again')], ['hard', t('fc.rate.hard')], ['good', t('fc.rate.good')], ['easy', t('fc.rate.easy')]].map(([k, v]) => h`<button onclick="rateCard('${k}')">${v}</button>`)}
    <span class="spacer"></span><button class="ghost" onclick="rateCard('retire')">${t('fc.retireBtn')}</button>`);
}
async function rateCard(rating) {
  const c = await post(`/api/cards/${S.card.id}/rate`, { rating, user_answer: val('my-a') });
  toast(c.status === 'retired' ? t('fc.toastRetired') : t('fc.toastNext', { t: when(c.due_at) })); VIEWS.cards();
}
async function addCard(btn) {
  await busy(btn, async () => {
    await post('/api/cards', { question: val('c-q'), answer: val('c-a'), collection: val('c-col'), policy: val('c-pol'), domain_id: domainId() });
    toast(t('fc.toastAdded')); VIEWS.cards();
  });
}
async function genCards(btn) {
  await busy(btn, async () => {
    const r = await post('/api/cards/generate', { topic: val('g-topic'), count: +val('g-n'), collection: val('g-col'), domain_id: domainId() });
    toast(t('fc.toastGen', { n: r.length })); VIEWS.cards();
  });
}
async function importCards(btn) {
  const f = $('#imp').files[0]; if (!f) return;
  const fd = new FormData(); fd.append('file', f);
  await busy(btn, async () => { const r = await api('/api/cards/import', { method: 'POST', form: fd }); toast(t('fc.toastImp', { n: r.imported })); VIEWS.cards(); });
}
async function exportCards() {
  const r = await fetch('/api/cards/export', { headers: { 'X-User': S.user } });
  const a = document.createElement('a'); a.href = URL.createObjectURL(await r.blob()); a.download = 'flashcards.csv'; a.click();
}
async function loadCardList() {
  const col = val('fc-col');
  const cs = await api('/api/cards' + (col ? '?collection=' + encodeURIComponent(col) : ''));
  set('#fc-list', cs.length ? h`<table><tr><th>${t('fc.q')}</th><th>${t('fc.a')}</th><th>${t('fc.col')}</th><th>${t('fc.nextCol')}</th><th></th></tr>${cs.map(c => h`<tr>
    <td class="pre">${c.question}</td><td class="pre muted">${c.answer}</td><td><span class="badge">${c.collection}</span>${c.gap_id ? h` <span class="badge warn">${t('fc.gapTag')}</span>` : ''}</td>
    <td class="tiny muted">${c.status === 'retired' ? t('fc.retiredTag') : when(c.due_at)}</td>
    <td><button class="ghost sm" onclick="editCard(${c.id})">${t('fc.edit')}</button><button class="ghost sm danger" onclick="delCard(${c.id})">${t('practice.delete')}</button></td></tr>`)}</table>`
    : empty(t('fc.noCards'), ''));
  S.cards = cs;
}
async function editCard(id) {
  const c = S.cards.find(x => x.id === id);
  const question = prompt(t('fc.q'), c.question); if (question === null) return;
  const answer = prompt(t('fc.a'), c.answer); if (answer === null) return;
  await put('/api/cards/' + id, { question, answer }); loadCardList();
}
async function delCard(id) { if (confirm(t('fc.confirmDel'))) { await del('/api/cards/' + id); VIEWS.cards(); } }
async function delCollection() {
  const col = val('fc-col'); if (!col) return toast(t('fc.toastPickCol'), true);
  if (confirm(t('fc.confirmDelCol', { col }))) { await del('/api/cards/collections/' + encodeURIComponent(col)); VIEWS.cards(); }
}

// ── knowledge base ────────────────────────────────────────────────────
VIEWS.kb = async () => {
  set(main, h`<div class="page-head"><div><h1>${t('kb.title')}</h1><p>${t('kb.desc')}</p></div>
    <button class="primary" onclick="kbEdit()">${t('kb.addBtn')}</button></div>
  <div id="kb-editor"></div>
  <div class="grid cols-side">
    <div class="card"><div class="row"><input id="kb-q" placeholder="${t('kb.searchPh')}" onkeydown="if(event.key==='Enter') kbSearch()">
      <button onclick="kbSearch()">${t('kb.searchBtn')}</button></div>
      <div class="row between" style="margin-top:10px">${seg('kb-mode', { bm25: t('kb.mode.bm25'), dense: t('kb.mode.dense'), hybrid: t('kb.mode.hybrid'), weighted: t('kb.mode.weighted') }, 'weighted')}
      <label class="check"><input type="checkbox" id="kb-rev">${t('kb.reviewedOnly')}</label></div>
      <div id="kb-results" style="margin-top:12px"></div></div>
    <div class="card"><h2>${tHtml('kb.docsHeading', { count: h`<span id="kb-count">0</span>` })}</h2><div id="kb-list" class="list"></div></div>
  </div>`);
  $('#kb-mode').onchange = () => val('kb-q') && kbSearch();
  await kbList();
};

async function kbList() {
  const docs = await api('/api/kb/docs' + dq());
  set('#kb-count', docs.length);
  set('#kb-list', docs.length ? docs.map(d => h`<div class="item" onclick="kbEdit(${d.id})"><div class="grow">
    <div class="title">${d.title}</div><div class="row tiny" style="margin-top:3px">
    <span class="badge ${d.reviewed ? 'ok' : 'warn'}">${d.reviewed ? t('kb.reviewed') : t('kb.unreviewed')}</span><span class="badge">P ${d.priority.toFixed(1)}</span>
    <span class="badge">v${d.version}</span>${d.topic ? h`<span class="badge">${d.topic}</span>` : ''}<span class="muted">${d.source}</span></div></div></div>`)
    : empty(t('kb.emptyTitle'), t('kb.emptyHint')));
}

async function kbEdit(id) {
  const d = id ? await api('/api/kb/docs/' + id) : { title: '', body: '', topic: '', source: t('kb.defaultSource'), priority: 2, reviewed: 0, domain_id: domainId() };
  set('#kb-editor', h`<div class="card fade" style="margin-bottom:16px"><div class="row between"><h2 style="margin:0">${id ? t('kb.editTitle') : t('kb.newTitle')}</h2>
    ${id ? h`<span class="muted tiny">${t('kb.verNote', { v: d.version })}</span>` : ''}</div><div class="stack" style="margin-top:12px">
    <div class="grid cols-2"><label class="field"><span>${t('kb.fTitle')}</span><input id="d-title" value="${d.title}"></label>
    <label class="field"><span>${t('kb.fTopic')}</span><input id="d-topic" value="${d.topic}" placeholder="${t('kb.fTopicPh')}"></label></div>
    <div class="grid cols-4"><label class="field"><span>${t('kb.fSource')}</span><input id="d-source" value="${d.source}"></label>
    <label class="field"><span>${t('kb.fPri')}</span><input id="d-pri" type="number" min="0" max="5" step="0.5" value="${d.priority}"></label>
    <label class="field"><span>${t('kb.fDomain')}</span><select id="d-domain"><option value="">${t('kb.unset')}</option>${S.domains.map(x => h`<option value="${x.id}" ${x.id == d.domain_id ? 'selected' : ''}>${x.name}</option>`)}</select></label>
    <label class="field"><span>${t('kb.fReview')}</span><label class="check" style="padding-top:8px"><input type="checkbox" id="d-rev" ${d.reviewed ? 'checked' : ''}>${t('kb.fReviewCheck')}</label></label></div>
    <label class="field"><span>${t('kb.fBody')}</span><textarea id="d-body" rows="10" placeholder="${t('kb.fBodyPh')}">${d.body}</textarea></label>
    <div class="row">${id ? h`<button class="ghost danger" onclick="kbDelete(${id})">${t('practice.delete')}</button>` : ''}<span class="spacer"></span>
    <button class="ghost" onclick="set('#kb-editor','')">${t('kb.cancel')}</button><button class="primary" onclick="kbSave(this, ${id || 'null'})">${t('kb.save')}</button></div></div></div>`);
  $('#d-title').focus();
}

async function kbSave(btn, id) {
  const body = { title: val('d-title') || t('kb.untitled'), topic: val('d-topic'), source: val('d-source'), priority: +val('d-pri'),
    reviewed: $('#d-rev').checked, domain_id: val('d-domain') ? +val('d-domain') : null, body: val('d-body') };
  await busy(btn, async () => {
    if (id) await put('/api/kb/docs/' + id, body);
    else { const r = await post('/api/kb/docs', body); if (r.auto_structured) toast(t('kb.toastSplit')); }
    set('#kb-editor', ''); toast(t('kb.toastSaved')); kbList();
  });
}
async function kbDelete(id) { if (confirm(t('kb.confirmDel'))) { await del('/api/kb/docs/' + id); set('#kb-editor', ''); kbList(); } }

async function kbSearch() {
  const query = val('kb-q').trim(); if (!query) return;
  set('#kb-results', h`<span class="spin"></span>`);
  const r = await post('/api/kb/search', { query, mode: segVal('kb-mode'), reviewed_only: $('#kb-rev').checked, k: 5, domain_id: domainId() });
  set('#kb-results', h`<p class="muted tiny">${t('kb.searchMeta', { n: r.results.length, ms: r.ms })}</p><div class="stack">${r.results.length ? r.results.map(x => h`<div class="evidence">
    <div class="row between"><span><b>${x.title}</b> <span class="muted tiny">${x.heading}</span></span>
    <span class="row tiny"><span class="badge">base ${x.base_score}</span>${r.mode === 'weighted' ? h`<span class="badge accent">final ${x.final_score}</span>` : ''}
    <span class="badge">P ${x.priority.toFixed(1)}</span>${x.reviewed ? '' : h`<span class="badge warn">${t('kb.unreviewed')}</span>`}</span></div>
    <div class="snippet pre">${x.content}</div><div class="row end"><button class="ghost sm" onclick="kbFeedback(${x.doc_id}, true).then(kbSearch)">${t('eval.helpful')}</button>
    <button class="ghost sm" onclick="kbFeedback(${x.doc_id}, false).then(kbSearch)">${t('eval.unhelpful')}</button></div></div>`) : empty(t('kb.noResults'), '')}</div>`);
}

// ── records: gaps, hint preferences, domains, usage, learner ──────────
VIEWS.records = async () => {
  const [prefs, usage] = await Promise.all([api('/api/prefs'), api('/api/usage')]);
  set(main, h`<div class="page-head"><div><h1>${t('rec.title')}</h1><p>${t('rec.desc')}</p></div></div>
  <div class="grid cols-side">
    <div class="stack">
      <div class="card"><div class="row between" style="margin-bottom:10px"><h2 style="margin:0">${t('rec.gapsTitle')}</h2>${seg('gap-tab', { 0: t('rec.gapPending'), 1: t('rec.gapConfirmed') }, '0')}</div><div id="gaps"></div><div id="gap-draft"></div></div>
      <div class="card"><h2>${t('rec.prefsTitle')} <span class="badge">v${prefs.current.version}</span> <span class="muted tiny">${prefs.current.source}</span></h2>
        <p class="muted tiny">${t('rec.prefsDesc')}</p>
        <textarea id="pref-text" rows="4">${prefs.current.summary}</textarea>
        <div class="row end" style="margin-top:8px"><button class="ghost" onclick="resetPrefs()">${t('rec.reset')}</button><button class="primary" onclick="savePrefs()">${t('rec.save')}</button></div>
        <details style="margin-top:10px"><summary>${t('rec.prefsDetails', { f: prefs.feedback.length, v: prefs.versions.length })}</summary>
          <table style="margin-top:6px">${prefs.feedback.map(f => h`<tr><td class="tiny muted">${when(f.feedback_at)}</td><td><span class="badge">${hintFbLabel(f.rating)}</span></td>
            <td class="tiny">${f.comment}<div class="muted">${f.text.slice(0, 80)}</div></td></tr>`)}</table>
          <table style="margin-top:6px">${prefs.versions.map(v => h`<tr><td>v${v.version}</td><td class="tiny muted">${v.source} · ${when(v.created_at)}</td><td class="pre tiny">${v.summary || t('rec.emptyVal')}</td></tr>`)}</table>
        </details></div>
    </div>
    <div class="stack">
      <div class="card"><h2>${t('rec.domainsTitle')}</h2><p class="muted tiny">${t('rec.domainsDesc')}</p><div id="domains" class="stack"></div>
        <details style="margin-top:8px"><summary>${t('rec.newDomain')}</summary>${domainForm({})}</details></div>
      <div class="card"><h2>${t('rec.usageTitle')}</h2>${usage.length ? h`<table><tr><th>${t('rec.uTask')}</th><th>${t('rec.uCalls')}</th><th>${t('rec.uFail')}</th><th>${t('rec.uTok')}</th><th>${t('rec.uCost')}</th><th>${t('rec.uMs')}</th></tr>
        ${usage.map(u => h`<tr><td>${u.task}</td><td>${u.calls}</td><td>${u.failures}</td><td class="tiny">${u.tokens_in || 0} / ${u.tokens_out || 0}</td><td class="tiny">${u.cost_usd || '—'}</td><td>${u.avg_ms}</td></tr>`)}</table>` : empty(t('rec.noUsage'), '')}</div>
      <div class="card"><h2>${t('rec.learnerTitle')}</h2><div class="row"><input id="who" value="${S.user}"><button onclick="switchUser()">${t('rec.switchBtn')}</button></div>
        <p class="muted tiny" style="margin-top:8px">${t('rec.learnerNote')}</p>
        <button class="danger" onclick="deleteMe()">${t('rec.deleteMe', { user: S.user })}</button></div>
    </div>
  </div>`);
  set('#domains', S.domains.map(d => h`<details><summary><b style="color:var(--text)">${d.name}</b></summary>${domainForm(d)}</details>`));
  $('#gap-tab').onchange = loadGaps; loadGaps();
};

const domainForm = d => h`<div class="stack" style="padding:8px 0"><input id="dn-${d.id || 'new'}" placeholder="${t('rec.dNamePh')}" value="${d.name || ''}">
  <textarea id="dg-${d.id || 'new'}" rows="2" placeholder="${t('rec.dGoalsPh')}">${d.goals || ''}</textarea>
  <textarea id="dc-${d.id || 'new'}" rows="2" placeholder="${t('rec.dCritPh')}">${d.criteria || ''}</textarea>
  <div class="row end">${d.id ? h`<button class="ghost sm danger" onclick="delDomain(${d.id})">${t('practice.delete')}</button>` : ''}<button class="sm primary" onclick="saveDomain(${d.id || 'null'})">${t('rec.save')}</button></div></div>`;

async function saveDomain(id) {
  const k = id || 'new', body = { name: val('dn-' + k), goals: val('dg-' + k), criteria: val('dc-' + k) };
  if (!body.name) return toast(t('rec.toastEnterName'), true);
  id ? await put('/api/domains/' + id, body) : await post('/api/domains', body);
  await loadDomains(); VIEWS.records(); toast(t('rec.toastSaved'));
}
async function delDomain(id) { if (confirm(t('rec.confirmDelDomain'))) { await del('/api/domains/' + id); await loadDomains(); VIEWS.records(); } }

const gapRow = g => h`<div class="evidence row between" id="gap-${g.id}"><div class="grow"><div>${g.text}</div><div class="row tiny muted">
  <span class="badge">${gapOriginLabel(g.origin)}</span>${g.question_id ? h`<a onclick="go('practice/${g.question_id}')">${t('rec.relQ')}</a>` : ''}<span>${when(g.created_at)}</span></div></div>
  <div class="row">${g.confirmed ? h`<button class="sm" onclick="gapPractice(this, ${g.id})">${t('rec.goPractice')}</button><button class="sm" onclick="gapDraft(this, ${g.id})">${t('rec.genCard')}</button>
    ${g.question_id ? h`<button class="sm" onclick="makeScenario(this, [${g.id}], ${g.question_id})">${t('rec.scenario')}</button>` : ''}`
    : h`<button class="sm primary" onclick="gapConfirm(${g.id})">${t('rec.confirm')}</button>`}<button class="ghost sm" onclick="gapDelete(${g.id})">${t('rec.ignore')}</button></div></div>`;

async function loadGaps() {
  const gs = await api('/api/gaps?confirmed=' + (segVal('gap-tab') === '1'));
  set('#gaps', gs.length ? h`<div class="stack">${gs.map(gapRow)}</div>` : empty(t('rec.noGapsTitle'), t('rec.noGapsHint')));
}
async function gapPractice(btn, id) {
  await busy(btn, async () => go('practice/' + (await post(`/api/gaps/${id}/practice`)).question_id));
}
async function gapConfirm(id) { await put('/api/gaps/' + id, { confirmed: true }); $('#gap-' + id)?.remove(); toast(t('rec.toastConfirmed')); }
async function gapDelete(id) { await del('/api/gaps/' + id); document.getElementById('gap-' + id)?.remove(); }
async function gapDraft(btn, id) {
  await busy(btn, async () => {
    const d = S.draft = await post(`/api/gaps/${id}/card-draft`);
    set('#gap-draft', h`<div class="card sunken fade" style="margin-top:12px"><h2>${t('rec.draftTitle')}</h2><div class="stack">
      <textarea id="gd-q" rows="2">${d.question}</textarea><textarea id="gd-a" rows="4">${d.answer}</textarea>
      <div class="row"><input id="gd-col" value="${t('rec.defaultGapCol')}"><button class="primary" onclick="saveDraft(this)">${t('rec.saveCardBtn')}</button></div></div></div>`);
  });
}
async function saveDraft(btn) {
  await busy(btn, async () => {
    await post('/api/cards', { ...S.draft, question: val('gd-q'), answer: val('gd-a'), collection: val('gd-col') });
    set('#gap-draft', ''); toast(t('rec.toastCardQueued'));
  });
}
async function savePrefs() { const p = await put('/api/prefs', { summary: val('pref-text') }); toast(t('rec.toastPrefVer', { v: p.version })); VIEWS.records(); }
async function resetPrefs() { if (confirm(t('rec.confirmResetPrefs'))) { await post('/api/prefs/reset'); VIEWS.records(); } }
function switchUser() { S.user = localStorage.user = val('who').trim() || 'default'; init(); }
async function deleteMe() {
  if (prompt(t('rec.promptDeleteMe', { user: S.user })) !== S.user) return;
  await del('/api/me'); toast(t('rec.toastDeleted')); init();
}

// ── boot ──────────────────────────────────────────────────────────────
async function init() {
  applyChrome();
  await loadDomains();
  route();
  S.health = await api('/api/health').catch(() => null);
  renderHealth();
}
init();
