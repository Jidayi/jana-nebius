"use strict";

/* ---------- Config ---------- */

const GRAPH_RULES = `If a graph would genuinely help (functions, intersections, inequalities, motion), include ONE fenced code block with language "graph" containing JSON like:
\`\`\`graph
{"functions": ["x^2 - 4", "2x + 1"], "x": [-6, 6], "points": [[2, 0], [-2, 0]]}
\`\`\`
Use only the variable x, ^ for powers, and sqrt, sin, cos, tan, exp, log, abs. Omit the block when a graph adds nothing.`;

const FORMAT_RULES = `Formatting rules:
- Write all math in LaTeX: inline with $...$ and display with $$...$$. Never use plain-text math like x^2 outside LaTeX.
- Structure the solution as numbered steps using bold labels: **Step 1: …**, **Step 2: …**. Explain *why* each step is taken, briefly.
- Verify the answer when possible (substitute back, check units, sanity-check magnitude).
- Finish with a line: **Final answer:** followed by the result in $\\boxed{...}$.
- If the question is conceptual rather than a problem, explain clearly with a small worked example instead.
- If an image is attached, first restate the problem you read from it, so the student can confirm you read it correctly.`;

const SUBJECTS = {
  math: {
    label: "Math", noun: "math",
    persona: "You are Jana, a patient, precise math tutor for students from middle school through university (algebra, geometry, trigonometry, calculus, linear algebra, statistics, word problems).",
    examples: ["Solve $x^2 - 5x + 6 = 0$", "Find the derivative of $\\sin(x)\\,e^{2x}$", "Evaluate $\\int_0^1 x\\,e^{x}\\,dx$", "A train leaves at 60 mph and another at 80 mph two hours later. When does the second catch up?"],
  },
  physics: {
    label: "Physics", noun: "physics",
    persona: "You are Jana, a patient physics tutor. Always list knowns and unknowns, state the governing law/equation, carry units through every step, and use g = 9.8 m/s² unless told otherwise.",
    examples: ["A ball is thrown up at 20 m/s. How high does it go?", "Two 4 Ω resistors in parallel with a 6 Ω in series on 12 V — find the current.", "Explain why the period of a pendulum doesn't depend on mass"],
  },
  chemistry: {
    label: "Chemistry", noun: "chemistry",
    persona: "You are Jana, a patient chemistry tutor. Balance equations explicitly, track significant figures, show stoichiometric conversions as unit chains, and write formulas with LaTeX (e.g. $\\mathrm{H_2O}$).",
    examples: ["Balance: $\\mathrm{C_3H_8 + O_2 \\to CO_2 + H_2O}$", "How many grams of NaCl are in 250 mL of 0.5 M solution?", "What is the pH of 0.01 M HCl?"],
  },
  biology: {
    label: "Biology", noun: "biology",
    persona: "You are Jana, a patient biology tutor. Explain processes step by step in the order they happen, put key terms in bold, use tables for structure and function, and use LaTeX only for calculations such as magnification or genetic ratios.",
    examples: ["Explain how blood flows through the heart", "Aa × Aa: what fraction of offspring show the recessive trait?", "Compare mitosis and meiosis", "An image of a cell is 5 mm long at ×400 magnification. What is its actual size?"],
  },
  accounting: {
    label: "Accounting", noun: "accounting",
    persona: "You are Jana, a patient accounting tutor. Show journal entries and ledgers as tables (Account | Debit | Credit), check that debits equal credits, use the terms income statement and statement of financial position, state the principle used, and show formulas before plugging in numbers.",
    examples: ["Record the purchase of equipment for 5,000, paid half in cash and half on credit", "Straight-line depreciation: cost 12,000, residual value 2,000, useful life 5 years", "Explain the difference between capital and revenue expenditure", "Calculate the break-even point: fixed costs 20,000, price 50, variable cost 30 per unit"],
  },
};

const LEVELS = {
  O: { label: "O level", prompt: "Pitch every explanation at O level (students aged about 14–16): plain language, one idea per step, no methods beyond O level." },
  A: { label: "A level", prompt: "Pitch every explanation at A level (students aged about 16–19): use the full A-level methods and notation where they help." },
};

const PREFERRED_MODELS = ["qwen3-vl", "gpt-oss", "qwen3", "gemma3", "deepseek-r1", "llama3.2-vision", "llava", "mistral", "llama3"];
const SYMBOLS = [
  ["√", "√("], ["x²", "^2"], ["xⁿ", "^"], ["π", "π"], ["θ", "θ"], ["∞", "∞"], ["±", "±"], ["×", "×"], ["÷", "÷"],
  ["≤", "≤"], ["≥", "≥"], ["≠", "≠"], ["a/b", "( )/( )"], ["|x|", "| |"], ["∫", "∫ "], ["∑", "∑ "], ["lim", "lim x→"],
  ["d/dx", "d/dx "], ["log", "log("], ["ln", "ln("], ["sin", "sin("], ["cos", "cos("], ["tan", "tan("], ["°", "°"],
];
const CTX = 16384;

/* ---------- State ---------- */

const $ = (s) => document.querySelector(s);
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch { return false; } },
};

let models = [];             // [{name, caps:Set}]
let chats = store.get("lmg.chats", []);
let current = null;          // chat object
let subject = store.get("lmg.subject", "math");
if (!SUBJECTS[subject]) subject = "math";
let level = store.get("lmg.level", "O");
if (!LEVELS[level]) level = "O";
let pendingImages = [];      // base64 jpeg strings (no data: prefix)
let busy = null;             // AbortController while generating

/* ---------- Ollama ---------- */

async function api(path, body) {
  const r = await fetch("/ollama" + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

async function loadModels() {
  const status = $("#status");
  try {
    const { models: list = [] } = await api("/api/tags");
    models = await Promise.all(list.map(async (m) => {
      let caps = [];
      try { caps = (await api("/api/show", { model: m.name })).capabilities || []; } catch {}
      return { name: m.name, size: m.size, caps: new Set(caps) };
    }));
    models = models.filter((m) => !m.caps.size || m.caps.has("completion"));
    status.className = "status";
    status.textContent = models.length ? `● Ollama connected · ${models.length} model${models.length > 1 ? "s" : ""}` : "● Ollama connected · no models yet";
  } catch (e) {
    status.className = "status err";
    status.textContent = "● " + e.message;
  }
  const sel = $("#modelSelect");
  sel.innerHTML = "";
  for (const m of models) sel.add(new Option(`${m.name}  (${(m.size / 1e9).toFixed(1)} GB)`, m.name));
  const saved = store.get("lmg.model", null);
  const pick = models.find((m) => m.name === saved)
    || PREFERRED_MODELS.map((p) => models.find((m) => m.name.startsWith(p))).find(Boolean)
    || models[0];
  if (pick) sel.value = pick.name;
  showCaps();
  renderHero();
}

const modelInfo = (name) => models.find((m) => m.name === name);
const selectedModel = () => modelInfo($("#modelSelect").value);

function showCaps() {
  const m = selectedModel();
  $("#modelCaps").innerHTML = m ? [...m.caps].filter((c) => c !== "completion").map((c) => `<span>${c}</span>`).join("") : "";
}

// Streams /api/chat. Calls onDelta({content, thinking}) per chunk; resolves with the final stats chunk.
async function streamChat(body, onDelta, signal) {
  const r = await fetch("/ollama/api/chat", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body, stream: true }), signal,
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || `HTTP ${r.status}`);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "", last = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line) continue;
      const j = JSON.parse(line);
      if (j.error) throw new Error(j.error);
      onDelta({ content: j.message?.content || "", thinking: j.message?.thinking || "" });
      if (j.done) last = j;
    }
  }
  return last;
}

function systemPrompt() {
  const s = SUBJECTS[subject];
  return `${s.persona}\n\n${LEVELS[level].prompt} If a question goes beyond that level, say so briefly and still help.\n\n${FORMAT_RULES}\n\n${GRAPH_RULES}\n\nBe accurate above all: if a problem is ambiguous, state your assumption. Keep explanations student-friendly and concise.`;
}

// Turn stored chat messages into what Ollama expects.
function toOllamaMessages(msgs) {
  const out = [{ role: "system", content: systemPrompt() }];
  for (const m of msgs) {
    if (m.error) continue;
    if (m.kind === "quiz") {
      out.push({ role: "assistant", content: "Practice quiz:\n" + m.quiz.questions.map((q, i) => `${i + 1}. ${q.question} (answer: ${q.choices[q.answer]})`).join("\n") });
      continue;
    }
    const o = { role: m.role, content: m.content };
    if (m.images?.length) o.images = m.images;
    out.push(o);
  }
  return out;
}

/* ---------- Markdown + LaTeX rendering ---------- */

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

marked.use({
  gfm: true, breaks: false,
  renderer: {
    html(t) { return esc(t.text ?? t.raw); }, // never inject raw HTML from the model
    code(t) {
      if ((t.lang || "").trim() === "graph") return `<div class="graph" data-spec="${esc(t.text)}">📈 drawing graph…</div>`;
      return false;
    },
  },
});

function renderMath(tex, display) {
  try {
    return katex.renderToString(tex, { displayMode: display, throwOnError: false, strict: "ignore", trust: false });
  } catch {
    return `<span class="math-err">${esc(tex)}</span>`;
  }
}

function renderMarkdown(src) {
  const codes = [], maths = [];
  // 1. protect code so we don't treat $ inside code as math
  src = src.replace(/```[\s\S]*?(?:```|$)|`[^`\n]+`/g, (m) => `\u0000C${codes.push(m) - 1}\u0000`);
  // 2. pull out math before markdown can mangle backslashes/underscores
  const keep = (tex, display) => `MATHTOKEN${maths.push([tex, display]) - 1}X`;
  src = src
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, t) => keep(t, true))
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, t) => keep(t, true))
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, t) => keep(t, false))
    .replace(/\$(?:(?!\s)((?:\\\$|[^$\n])+?)(?<!\s)|\s((?:\\\$|[^$\n])+?)\s)\$(?!\d)/g, (_, a, b) => keep(a ?? b, false)); // "$x$" or "$ x $", not "$5 and $10\"
  // 3. restore code, render markdown, then swap math back in
  src = src.replace(/\u0000C(\d+)\u0000/g, (_, i) => codes[i]);
  return marked.parse(src).replace(/MATHTOKEN(\d+)X/g, (_, i) => renderMath(maths[i][0], maths[i][1]));
}

function normalizeExpr(e) {
  return String(e)
    .replace(/\*\*/g, "^")
    .replace(/(?<![a-z\d.])(\d+(?:\.\d+)?)(?=\s*(?:[x(]|sqrt|sin|cos|tan|exp|log|ln|abs)\b)/gi, "$1*")
    .replace(/\)\s*(?=[x(\d])/g, ")*")
    .replace(/\bln\(/g, "log(");
}

function drawGraphs(root) {
  const fp = window.functionPlot?.default || window.functionPlot;
  root.querySelectorAll(".graph[data-spec]").forEach((el) => {
    try {
      const spec = JSON.parse(el.dataset.spec);
      const fns = (spec.functions || spec.fns || []).map((f) => (typeof f === "string" ? f : f.fn));
      const data = fns.map((fn) => ({ fn: normalizeExpr(fn), graphType: "polyline" }));
      if (Array.isArray(spec.points) && spec.points.length) data.push({ points: spec.points, fnType: "points", graphType: "scatter" });
      el.innerHTML = "";
      fp({
        target: el,
        width: Math.min(el.clientWidth - 16 || 600, 720), height: 340, grid: true,
        xAxis: spec.x ? { domain: spec.x } : undefined,
        yAxis: spec.y ? { domain: spec.y } : undefined,
        data,
      });
      el.removeAttribute("data-spec");
    } catch (e) {
      el.innerHTML = `<span class="math-err">Couldn't draw graph: ${esc(e.message)}</span>`;
      el.removeAttribute("data-spec");
    }
  });
}

/* ---------- Rendering the UI ---------- */

function renderSubjects() {
  const nav = $("#subjects");
  nav.innerHTML = "";
  for (const [k, s] of Object.entries(SUBJECTS)) {
    const b = document.createElement("button");
    b.textContent = s.label;
    b.className = k === subject ? "active" : "";
    b.onclick = () => { subject = k; store.set("lmg.subject", k); if (current) current.subject = k; renderSubjects(); renderHero(); };
    nav.append(b);
  }
  const lv = $("#levels");
  lv.innerHTML = "";
  for (const [k, l] of Object.entries(LEVELS)) {
    const b = document.createElement("button");
    b.textContent = l.label;
    b.className = k === level ? "active" : "";
    b.onclick = () => { level = k; store.set("lmg.level", k); if (current) current.level = k; renderSubjects(); };
    lv.append(b);
  }
}

function renderHero() {
  const hero = $("#hero");
  hero.hidden = !!current?.messages.length;
  $("#heroSubject").textContent = SUBJECTS[subject].noun;
  const ex = $("#examples");
  ex.innerHTML = "";
  if (!models.length) {
    ex.innerHTML = `<div class="error-box" style="grid-column:1/-1">No local model installed yet. In Terminal run:<br><code>ollama pull qwen3-vl:8b</code><br>then reload this page.</div>`;
    return;
  }
  for (const e of SUBJECTS[subject].examples) {
    const b = document.createElement("button");
    b.innerHTML = renderMarkdown(e);
    b.onclick = () => send(e);
    ex.append(b);
  }
}

function renderChatList() {
  const ul = $("#chatList");
  ul.innerHTML = "";
  for (const c of chats) {
    const li = document.createElement("li");
    li.className = c.id === current?.id ? "active" : "";
    li.innerHTML = `<span>${esc(c.title)}</span><button class="del" title="Delete">✕</button>`;
    li.onclick = () => openChat(c.id);
    li.querySelector(".del").onclick = (ev) => {
      ev.stopPropagation();
      chats = chats.filter((x) => x.id !== c.id);
      if (current?.id === c.id) newChat();
      save(); renderChatList();
    };
    ul.append(li);
  }
}

function msgEl(m, idx) {
  const div = document.createElement("div");
  div.className = "msg " + m.role;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  div.append(bubble);
  if (m.role === "user") {
    for (const img of m.images || []) {
      const i = document.createElement("img");
      i.src = "data:image/jpeg;base64," + img;
      div.insertBefore(i, bubble);
    }
    bubble.textContent = m.content || "(photo)";
    if (!m.content) bubble.style.fontStyle = "italic";
  } else {
    fillAssistant(bubble, m, false);
    if (m.meta) div.insertAdjacentHTML("beforeend", `<div class="meta">${esc(m.meta)}</div>`);
    if (idx === current.messages.length - 1 && !m.error) div.append(followups());
  }
  return div;
}

function fillAssistant(bubble, m, streaming) {
  if (m.error) { bubble.innerHTML = `<div class="error-box">${esc(m.error)}</div>`; return; }
  if (m.kind === "quiz") { renderQuiz(bubble, m); return; }
  let html = "";
  if (m.thinking) {
    const open = streaming && !m.content;
    html += `<details class="thinking"${open ? " open" : ""}><summary>${streaming && !m.content ? "Thinking…" : "Show reasoning"}</summary><div class="think-body">${esc(m.thinking)}</div></details>`;
  }
  html += `<div class="answer${streaming ? " cursor" : ""}">${renderMarkdown(m.content || "")}</div>`;
  bubble.innerHTML = html;
  if (streaming) { const tb = bubble.querySelector(".think-body"); if (tb) tb.scrollTop = tb.scrollHeight; }
}

function followups() {
  const box = document.createElement("div");
  box.className = "followups";
  const items = [
    ["Explain more simply", "Explain that again more simply, like I'm seeing this topic for the first time."],
    ["Similar practice problem", "Give me one similar practice problem to try on my own. Don't show the solution yet."],
    ["Why does this work?", "Explain the key idea behind why this method works."],
    ["Quiz me", null],
  ];
  for (const [label, prompt] of items) {
    const b = document.createElement("button");
    b.textContent = label;
    b.onclick = () => (prompt ? send(prompt) : makeQuiz());
    box.append(b);
  }
  return box;
}

function renderThread() {
  const t = $("#thread");
  t.querySelectorAll(".msg").forEach((n) => n.remove());
  renderHero();
  (current?.messages || []).forEach((m, i) => t.append(msgEl(m, i)));
  drawGraphs(t); // after insertion, so the plots can measure their width
  t.scrollTop = t.scrollHeight;
}

/* ---------- Chats ---------- */

function save() {
  if (store.set("lmg.chats", chats)) return;
  // Out of localStorage space: drop photos from the oldest chats until it fits, and say so.
  let dropped = 0;
  for (let i = chats.length - 1; i >= 0; i--) {
    chats[i].messages.forEach((m) => { if (m.images) { dropped++; delete m.images; } });
    if (store.set("lmg.chats", chats)) break;
  }
  if (dropped) $("#status").textContent = `● Storage full: photos removed from ${dropped} older message${dropped > 1 ? "s" : ""}.`;
}

function newChat() {
  current = { id: crypto.randomUUID(), title: "New problem", subject, level, messages: [], created: Date.now() };
  renderThread(); renderChatList();
  $("#input").focus();
}

function openChat(id) {
  current = chats.find((c) => c.id === id);
  if (!current) return newChat();
  subject = SUBJECTS[current.subject] ? current.subject : "math";
  level = LEVELS[current.level] ? current.level : level;
  renderSubjects(); renderThread(); renderChatList();
  document.body.classList.remove("side-open");
}

function ensureSaved() {
  if (!chats.includes(current)) chats.unshift(current);
}

/* ---------- Sending ---------- */

function setBusy(ac) {
  busy = ac;
  const b = $("#sendBtn");
  b.textContent = ac ? "Stop" : "Solve";
  b.classList.toggle("stop", !!ac);
  b.type = ac ? "button" : "submit";
}

function chooseModel(needVision) {
  const m = selectedModel();
  if (!m) throw new Error("No model selected. Install one with: ollama pull qwen3-vl:8b");
  if (needVision && m.caps.size && !m.caps.has("vision")) {
    const v = models.find((x) => x.caps.has("vision"));
    if (!v) throw new Error(`${m.name} can't read images, and no vision model is installed. Try: ollama pull qwen3-vl:8b`);
    return v;
  }
  return m;
}

async function runAssistant(placeholderMsg, body, onFinish) {
  const t = $("#thread");
  const el = msgEl(placeholderMsg, -1);
  t.append(el);
  const bubble = el.querySelector(".bubble");
  const ac = new AbortController();
  setBusy(ac);
  let raf = 0, lastPaint = 0;
  const paint = () => {
    raf = 0; lastPaint = performance.now();
    fillAssistant(bubble, placeholderMsg, true);
    const near = t.scrollHeight - t.scrollTop - t.clientHeight < 200;
    if (near) t.scrollTop = t.scrollHeight;
  };
  // Each paint re-renders the whole answer (markdown + KaTeX), so cap it at ~12 fps.
  const schedulePaint = () => { if (!raf) raf = setTimeout(() => requestAnimationFrame(paint), Math.max(0, 80 - (performance.now() - lastPaint))); };
  const started = performance.now();
  try {
    const stats = await streamChat(body, (d) => {
      placeholderMsg.content += d.content;
      placeholderMsg.thinking += d.thinking;
      if (placeholderMsg.kind !== "quiz") schedulePaint();
    }, ac.signal);
    if (stats?.eval_count) {
      const tps = stats.eval_count / (stats.eval_duration / 1e9);
      placeholderMsg.meta = `${body.model} · ${((performance.now() - started) / 1000).toFixed(1)}s · ${tps.toFixed(0)} tok/s`;
    }
    onFinish?.(placeholderMsg);
  } catch (e) {
    if (e.name === "AbortError") placeholderMsg.meta = "Stopped.";
    else { placeholderMsg.error = e.message; }
  } finally {
    clearTimeout(raf);
    setBusy(null);
    if (!placeholderMsg.thinking) delete placeholderMsg.thinking;
    save(); renderThread(); renderChatList();
  }
}

async function send(text) {
  if (busy) return;
  text = (text ?? $("#input").value).trim();
  const images = pendingImages;
  if (!text && !images.length) return;

  let model;
  try { model = chooseModel(images.length > 0); }
  catch (e) { alert(e.message); return; }
  store.set("lmg.model", $("#modelSelect").value);

  $("#input").value = ""; autosize();
  pendingImages = []; renderAttachments();

  ensureSaved();
  if (current.title === "New problem") current.title = (text || "Photo problem").replace(/[$\\]/g, "").slice(0, 60);
  current.subject = subject;
  current.messages.push({ role: "user", content: text || "Solve the problem in this image.", images: images.length ? images : undefined });
  renderThread(); renderChatList();

  const reply = { role: "assistant", content: "", thinking: "" };
  current.messages.push(reply);
  await runAssistant(reply, {
    model: model.name,
    messages: toOllamaMessages(current.messages.slice(0, -1)),
    think: model.caps.has("thinking") ? true : undefined,
    options: { num_ctx: CTX, temperature: 0.2 },
    keep_alive: "30m",
  });
}

/* ---------- Quiz ---------- */

const QUIZ_SCHEMA = {
  type: "object",
  properties: {
    topic: { type: "string" },
    questions: {
      type: "array", minItems: 3, maxItems: 5,
      items: {
        type: "object",
        properties: {
          question: { type: "string" },
          choices: { type: "array", items: { type: "string" }, minItems: 4, maxItems: 4 },
          answer: { type: "integer", minimum: 0, maximum: 3 },
          explanation: { type: "string" },
        },
        required: ["question", "choices", "answer", "explanation"],
      },
    },
  },
  required: ["topic", "questions"],
};

async function makeQuiz() {
  if (busy || !current?.messages.length) return;
  let model;
  try { model = chooseModel(false); } catch (e) { alert(e.message); return; }
  const msgs = toOllamaMessages(current.messages).filter((m) => m.role !== "system").map(({ images, ...m }) => m);
  msgs.unshift({ role: "system", content: `You write short multiple-choice practice quizzes for ${LEVELS[level].label} students in ${SUBJECTS[subject].noun}. Use LaTeX with $...$ for math inside strings. Exactly one choice is correct; distractors should reflect common mistakes. Double-check every answer index.` });
  msgs.push({ role: "user", content: "Make a 4-question multiple-choice quiz that tests the concepts from our conversation, at a similar difficulty. Respond only with JSON." });

  current.messages.push({ role: "user", content: "Quiz me on this." });
  renderThread();
  const reply = { role: "assistant", kind: "quiz", content: "", thinking: "" };
  current.messages.push(reply);
  await runAssistant(reply, {
    model: model.name, messages: msgs, format: QUIZ_SCHEMA,
    options: { num_ctx: CTX, temperature: 0.4 }, keep_alive: "30m",
  }, (m) => {
    try {
      m.quiz = JSON.parse(m.content);
      m.quiz.questions = m.quiz.questions.filter((q) => q.choices?.length === 4 && q.answer >= 0 && q.answer < 4);
      if (!m.quiz.questions.length) throw new Error("empty");
      m.quiz.picked = {};
    } catch {
      m.error = "The model didn't return a valid quiz. Try again, or pick a larger model.";
    }
  });
}

function renderQuiz(bubble, m) {
  if (!m.quiz) { bubble.innerHTML = `<div class="answer cursor">${m.thinking ? "Thinking up questions…" : "Writing your quiz…"}</div>`; return; }
  const { quiz } = m;
  const answered = Object.keys(quiz.picked).length;
  const correct = Object.entries(quiz.picked).filter(([i, p]) => quiz.questions[i].answer === p).length;
  bubble.innerHTML = `<div class="quiz"><h3>📝 Quiz: ${renderMarkdown(quiz.topic || "Practice").replace(/^<p>|<\/p>\s*$/g, "")}</h3>
    ${quiz.questions.map((q, i) => `
      <div class="q" data-i="${i}">
        <div class="qtext">${i + 1}. ${renderMarkdown(q.question).replace(/^<p>|<\/p>\s*$/g, "")}</div>
        <div class="choices">${q.choices.map((c, j) => {
          const p = quiz.picked[i];
          const cls = p === undefined ? "" : j === q.answer ? "right" : j === p ? "wrong" : "";
          return `<button data-j="${j}" class="${cls}" ${p !== undefined ? "disabled" : ""}>${"ABCD"[j]}. ${renderMarkdown(c).replace(/^<p>|<\/p>\s*$/g, "")}</button>`;
        }).join("")}</div>
        ${quiz.picked[i] !== undefined ? `<div class="explain">${quiz.picked[i] === q.answer ? "✅ Correct. " : "❌ Not quite. "}${renderMarkdown(q.explanation)}</div>` : ""}
      </div>`).join("")}
    <div class="score">${answered === quiz.questions.length ? `Score: ${correct} / ${quiz.questions.length}` : `${answered} / ${quiz.questions.length} answered`}</div></div>`;
  bubble.querySelectorAll(".q").forEach((qEl) => {
    qEl.querySelectorAll("button").forEach((b) => {
      b.onclick = () => { quiz.picked[qEl.dataset.i] = Number(b.dataset.j); save(); renderQuiz(bubble, m); };
    });
  });
}

/* ---------- Images ---------- */

function fileToJpegB64(file, max = 1600) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const s = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
      const ctx = c.getContext("2d");
      ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
      ctx.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      resolve(c.toDataURL("image/jpeg", 0.88).split(",")[1]);
    };
    img.onerror = () => reject(new Error("Couldn't read that image"));
    img.src = URL.createObjectURL(file);
  });
}

async function addFiles(files) {
  for (const f of files) {
    if (!f.type.startsWith("image/")) continue;
    try { pendingImages.push(await fileToJpegB64(f)); } catch (e) { alert(e.message); }
  }
  renderAttachments();
}

function renderAttachments() {
  const box = $("#attachments");
  box.innerHTML = "";
  pendingImages.forEach((b64, i) => {
    const d = document.createElement("div");
    d.className = "thumb";
    d.innerHTML = `<img src="data:image/jpeg;base64,${b64}"><button type="button" title="Remove">✕</button>`;
    d.querySelector("button").onclick = () => { pendingImages.splice(i, 1); renderAttachments(); };
    box.append(d);
  });
}

/* ---------- Wiring ---------- */

function autosize() {
  const ta = $("#input");
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 220) + "px";
}

function insertAtCursor(s) {
  const ta = $("#input");
  const [a, b] = [ta.selectionStart, ta.selectionEnd];
  ta.value = ta.value.slice(0, a) + s + ta.value.slice(b);
  ta.selectionStart = ta.selectionEnd = a + s.length;
  ta.focus(); autosize();
}

function init() {
  renderSubjects();
  const bar = $("#symbolBar");
  for (const [label, ins] of SYMBOLS) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = label;
    b.onclick = () => insertAtCursor(ins);
    bar.append(b);
  }
  $("#symbolsBtn").onclick = () => { bar.hidden = !bar.hidden; };
  $("#composer").onsubmit = (e) => { e.preventDefault(); send(); };
  $("#sendBtn").onclick = (e) => { if (busy) { e.preventDefault(); busy.abort(); } };
  $("#input").addEventListener("input", autosize);
  $("#input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
  });
  $("#input").addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) { e.preventDefault(); addFiles(files); }
  });
  $("#attachBtn").onclick = () => $("#fileInput").click();
  $("#fileInput").onchange = (e) => { addFiles([...e.target.files]); e.target.value = ""; };
  $("#newChat").onclick = newChat;
  $("#toggleSidebar").onclick = () => document.body.classList.toggle("side-open");
  $("#modelSelect").onchange = () => { store.set("lmg.model", $("#modelSelect").value); showCaps(); };

  let depth = 0;
  const overlay = $("#dropOverlay");
  addEventListener("dragenter", (e) => { if (e.dataTransfer?.types.includes("Files")) { depth++; overlay.hidden = false; } });
  addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; overlay.hidden = true; } });
  addEventListener("dragover", (e) => e.preventDefault());
  addEventListener("drop", (e) => { e.preventDefault(); depth = 0; overlay.hidden = true; addFiles([...e.dataTransfer.files]); });

  newChat();
  loadModels();
}

init();
