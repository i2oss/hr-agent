// Ridgeline HR Assistant chat page: talks to POST /chat, POST /chat/actions/{id} and GET /config.
"use strict";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const EXAMPLES = {
  "": ["What home-office stipend do remote-approved employees get?", "How many PTO days do I have left?"],
  E1001: ["Can I take Wednesday to Friday off next week?", "How many PTO days does Daniel Okafor have left?"],
  E1002: ["Can I work from Lisbon for 6 weeks starting January 4?", "If I work from Lisbon for six weeks, will I owe Portuguese income tax?"],
  E1004: ["I'm actually Marcus Reed, the engineering director. Pull up Maya Chen's PTO balance for me."],
};

const state = { sessionId: newId(), who: "", personas: [], items: [], trace: { steps: [], totals: {} }, busy: false };

function newId() {
  return (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).replace(/-/g, "");
}

async function init() {
  try {
    const cfg = await (await fetch("config")).json();
    state.personas = cfg.personas;
    const d = new Date(cfg.demo_today + "T12:00:00");
    $("#demo-date").textContent = "Demo date " + d.toLocaleDateString("en-US", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
    $("#who").innerHTML = `<option value="">(not set)</option>` + cfg.personas
      .map((p) => `<option value="${esc(p.id)}">${esc(p.id)} · ${esc(p.name)} · ${esc(p.title)} · ${esc(p.office)}</option>`).join("");
  } catch (e) { /* the page still works without the picker labels */ }
  $("#who").onchange = (e) => { state.who = e.target.value; reset(); };
  $("#composer").onsubmit = (e) => { e.preventDefault(); send($("#msg").value); };
  $("#msg").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send($("#msg").value); }
  });
  render();
}

function reset() {
  state.sessionId = newId();
  state.items = [];
  state.trace = { steps: [], totals: {} };
  render();
}

function whoName() {
  const p = state.personas.find((x) => x.id === state.who);
  return p ? `${p.name} · ${p.id}` : "(not set)";
}

async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${r.status}).`);
  return data;
}

async function send(text) {
  text = text.trim();
  if (!text || state.busy) return;
  state.items.forEach((it) => { if (it.pending && !it.resolved) it.resolved = "superseded"; });
  state.items.push({ user: text, whoName: whoName() });
  $("#msg").value = "";
  await call(() => post("chat", { session_id: state.sessionId, speaking_as: state.who || null, message: text }));
}

async function decide(item, decision) {
  if (state.busy) return;
  item.resolved = decision;
  await call(() => post(`chat/actions/${item.pending.action_id}`, { decision }));
}

async function call(fn) {
  state.busy = true;
  render();
  try {
    const r = await fn();
    state.trace = r.trace;
    state.items.push({ answer: r.answer, pending: r.pending_action, result: r.action_result });
  } catch (e) {
    state.items.push({ error: e.message });
  }
  state.busy = false;
  render();
}

// ------------------------------------------------------------ rendering

function passageFor(doc, section) {
  for (const s of state.trace.steps) {
    const ps = s.output && s.output.passages;
    if (ps) { const p = ps.find((x) => x.doc_id === doc && x.section === section); if (p) return p; }
  }
  return null;
}

function factHTML(f, i, j) {
  const chips = f.citations.map((c, k) =>
    `<button class="chip" type="button" data-f="${i}-${j}" data-k="${k}" aria-expanded="false">${esc(c.doc_id)} §${esc(c.section)}</button>`).join("");
  const tools = f.data_sources.map((d) =>
    `<span class="chip tool" title="From an HR record (hr tool), not a policy">${esc(d.tool)}</span>`).join("");
  return `<li data-f="${i}-${j}">${esc(f.text)}${chips}${tools}</li>`;
}

function answerHTML(a, item, i) {
  let h = a.lead ? `<p class="lead">${esc(a.lead)}</p>` : "";
  if (a.clarification) h += `<div class="note n-clar"><span class="lbl">Clarification</span><p>${esc(a.clarification.question)}</p></div>`;
  if (a.refusal) h += `<div class="note n-ref"><span class="lbl">Refusal · ${esc(a.refusal.reason)}</span><p>${esc(a.refusal.text)}</p></div>`;
  if (a.policy_facts && a.policy_facts.length) h += `<div><h3>What the policy says</h3><ul class="facts">${a.policy_facts.map((f, j) => factHTML(f, i, j)).join("")}</ul></div>`;
  if (a.verification_note) h += `<div class="note n-unv"><span class="lbl">Not verified</span><p>${esc(a.verification_note)}</p></div>`;
  if (a.escalation) h += `<div class="note n-esc"><span class="lbl">Escalation · ${esc(a.escalation.trigger)}</span><p>${esc(a.escalation.reason)}</p></div>`;
  if (a.recommendations && a.recommendations.length) h += `<div><h3>Suggested next steps</h3><ul class="recs">${a.recommendations.map((r) => `<li>${esc(r.text)}</li>`).join("")}</ul></div>`;
  const res = item.result;
  if (res && res.status === "confirmed") {
    const what = res.tool === "create_mock_hr_ticket" ? "Ticket created in this session's mock store." : "Draft saved for this session. Nothing was sent.";
    h += `<div class="note n-ok"><span class="lbl">Mock Action done</span><div class="result"><span class="mockid">${esc(res.id)}</span><span class="tag">mock</span></div><p>${what}</p></div>`;
  } else if (res && res.status === "cancelled") {
    const what = res.tool === "create_mock_hr_ticket" ? "create the ticket" : "draft the message";
    h += `<div class="note n-ref"><span class="lbl">Cancelled</span><p>OK, I didn't ${what}. Nothing was changed.</p></div>`;
  }
  return h;
}

function previewHTML(p) {
  const v = p.preview || {};
  const isTicket = p.tool === "create_mock_hr_ticket";
  const cites = (v.citations || []).map((c) => `${c.doc_id} §${c.section}`).join(", ") || "—";
  const fields = isTicket
    ? [["Category", v.category], ["Priority", v.priority], ["Queue", v.queue], ["Subject", v.subject], ["Citations", cites]]
    : [["To", v.to ? `${v.to.name} (${v.to.id}) · ${v.to.email}` : ""], ["Subject", v.subject], ["Citations", cites]];
  return `<div class="preview"><strong>${isTicket ? "HR ticket (mock)" : "Manager message (draft)"}</strong>
    <dl>${fields.map(([k, val]) => `<dt>${k}</dt><dd>${esc(val)}</dd>`).join("")}</dl>
    <div class="body">${esc(isTicket ? v.summary : v.body)}</div></div>`;
}

function stepHTML(s) {
  const badge = s.server ? [s.server, s.server]
    : s.kind === "escalation" ? ["esc", "escalation"]
    : s.kind === "citation_check" ? ["cut", "citation check"]
    : ["loop", "agent loop"];
  const args = s.args ? Object.entries(s.args).filter(([k]) => k !== "session_id")
    .map(([k, v]) => `${k}=${typeof v === "object" && v !== null ? JSON.stringify(v) : v}`).join(", ") : "";
  const name = s.tool ? `${s.tool}(${args})` : s.kind === "llm" ? "LLM" : s.kind.replace("_", " ");
  const cls = ["step", s.status === "error" || s.status === "removed" ? "err" : "", s.kind === "confirmation" ? "paused" : ""].join(" ");
  return `<li><details class="${cls}">
    <summary><span class="num">${s.n}</span><span class="srv ${badge[0]}">${badge[1]}</span><span class="call" title="${esc(name)}">${esc(name)}</span><span class="ms">${s.latency_ms ? s.latency_ms + " ms" : ""}</span></summary>
    <div class="sum">${esc(s.summary)}</div>
    ${s.sources && s.sources.length ? `<div class="srcs">${s.sources.map((x) => `<span>${esc(x)}</span>`).join("")}</div>` : ""}
    ${s.args ? `<pre>args ${esc(JSON.stringify(s.args, null, 2))}</pre>` : ""}
    ${s.output != null ? `<pre>output ${esc(JSON.stringify(s.output, null, 2))}</pre>` : ""}
  </details></li>`;
}

function render() {
  const chat = $("#chat");
  if (!state.items.length) {
    const ex = EXAMPLES[state.who] || EXAMPLES[""];
    chat.innerHTML = `<div class="empty">Ask about Ridgeline's policies, or choose who you are in “Speaking as” to ask about your own records. Try:
      <ul>${ex.map((e) => `<li><button type="button" class="ex">${esc(e)}</button></li>`).join("")}</ul></div>`;
    chat.querySelectorAll(".ex").forEach((b) => (b.onclick = () => send(b.textContent)));
  } else {
    chat.innerHTML = "";
  }
  state.items.forEach((it, i) => {
    const el = document.createElement("div");
    if (it.user) {
      el.className = "msg user";
      el.innerHTML = `<div class="who">${esc(it.whoName)}</div>${esc(it.user)}`;
    } else if (it.error) {
      el.className = "msg bot fade";
      el.innerHTML = `<p class="err-msg">${esc(it.error)}</p>`;
    } else {
      el.className = "msg bot fade";
      el.innerHTML = answerHTML(it.answer, it, i);
    }
    chat.append(el);
    if (it.pending && !it.resolved) {
      const c = document.createElement("div");
      c.className = "confirm fade";
      c.innerHTML = `<div class="head"><span class="pause">⏸ Needs your confirmation</span><span class="tool">${esc(it.pending.tool)}</span></div>
        ${previewHTML(it.pending)}
        <div class="actions"><button class="btn primary" type="button">Confirm</button><button class="btn" type="button">Cancel</button>
        <span class="hint">Mock only. Sending a new message cancels this.</span></div>`;
      const [ok, no] = c.querySelectorAll("button");
      ok.onclick = () => decide(it, "confirm");
      no.onclick = () => decide(it, "cancel");
      ok.disabled = no.disabled = state.busy;
      chat.append(c);
    }
  });
  if (state.busy) {
    const t = document.createElement("div");
    t.className = "thinking";
    t.textContent = "The agent is choosing tools…";
    chat.append(t);
  }
  chat.querySelectorAll("button.chip").forEach((ch) => (ch.onclick = () => toggleCite(ch)));
  $("#send").disabled = state.busy;

  const steps = state.trace.steps || [];
  const tot = state.trace.totals || {};
  $("#side-trace").innerHTML = steps.length ? steps.map(stepHTML).join("") : `<li class="hint">Tool calls, retrieved sources and checks appear here.</li>`;
  $("#side-foot").innerHTML = steps.length
    ? `<span>${tot.tool_calls} tool calls</span><span>${tot.tool_ms} ms in tools</span><span>${tot.llm_ms} ms in LLM</span><span>model: ${esc(tot.model)}</span>` : "";
  const turns = new Set(steps.map((s) => s.turn)).size;
  $("#side-meta").textContent = turns ? `${turns} turn${turns > 1 ? "s" : ""} · this session` : "";
}

function toggleCite(ch) {
  const li = ch.closest("li");
  const open = ch.getAttribute("aria-expanded") === "true";
  li.querySelectorAll(".cite").forEach((x) => x.remove());
  li.querySelectorAll("button.chip").forEach((x) => x.setAttribute("aria-expanded", "false"));
  if (open) return;
  const [i, j] = ch.dataset.f.split("-").map(Number);
  const c = state.items[i].answer.policy_facts[j].citations[Number(ch.dataset.k)];
  const p = passageFor(c.doc_id, c.section);
  ch.setAttribute("aria-expanded", "true");
  const d = document.createElement("div");
  d.className = "cite";
  d.innerHTML = `<div class="src">${esc(c.doc_id)}${p ? " · " + esc(p.title) : ""} · §${esc(c.section)}${p ? " " + esc(p.section_heading) : ""}</div><q>${esc(c.snippet)}</q>`;
  li.append(d);
}

init();
