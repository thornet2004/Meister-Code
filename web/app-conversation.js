"use strict";
// Conversa: contexto, rascunhos, mensagens, envio, streaming e estado.
// Script clássico: partilha o âmbito global com os outros ficheiros app-*.js (ver index.html).

async function loadConversation() {
  const res = await call("get_conversation");
  if (!res.ok) return showError(res.error);
  renderConversation(res.messages || []);
  await refreshContextUsage();
}

async function setContextWindow() {
  const current = contextUsage?.limit ?? 128000;
  const value = window.prompt("Janela de contexto (tokens). 0 = sem limite na app; mantém-se a capacidade do fornecedor:", String(current));
  if (value === null) return;
  const res = await call("set_context_window", value);
  if (!res.ok) return showError(res.error);
  applyState(res);
  await refreshContextUsage();
}

async function compactContext() {
  if (chatBusy || compacting) return;
  compacting = true;
  if (el.contextCompact) el.contextCompact.disabled = true;
  try {
    const res = await call("compact_context", "");
    if (!res.ok) return showError(res.error);
    toast(`Contexto compactado: ${res.compacted} mensagens resumidas, ${res.kept} mantidas.`, "success", { label: "Desfazer", run: undoCompaction });
    await loadConversation();
  } finally {
    compacting = false;
    if (el.contextCompact) el.contextCompact.disabled = false;
  }
}

async function undoCompaction() {
  const res = await call("restore_compaction");
  if (!res.ok) return showError(res.error);
  await loadConversation();
  toast("Compactação desfeita.", "success");
}

// Custo em dólares (a moeda dos preços dos provedores), com mais casas nos valores pequenos.
function formatCost(usd) {
  const value = Number(usd) || 0;
  const digits = value >= 1 ? 2 : value >= 0.01 ? 3 : 4;
  return "US$ " + value.toFixed(digits).replace(".", ",");
}

function formatTokens(value) {
  const number = Number(value) || 0;
  if (number >= 1000000) return (number / 1000000).toFixed(2).replace(".", ",") + "M";
  if (number >= 1000) return (number / 1000).toFixed(1).replace(".", ",") + "k";
  return String(number);
}

function draftKey() {
  return state.activeProjectId ? "draft:project:" + state.activeProjectId : "draft:conversation:" + (state.activeConversationId || "default");
}

function restoreDraft() {
  const key = draftKey();
  if (key !== lastDraftKey) {
    lastDraftKey = key;
    contextWarningDismissed = false;
    el.composer.value = "";
    autosize();
  }
  try {
    const value = sessionStorage.getItem(key);
    if (value) {
      el.composer.value = value;
      autosize();
      updateSlashMenu();
    }
  } catch (error) { /* sessionStorage indisponível */ }
}

function saveDraft() {
  try {
    const key = draftKey();
    if (el.composer.value) sessionStorage.setItem(key, el.composer.value);
    else sessionStorage.removeItem(key);
  } catch (error) { /* sessionStorage indisponível */ }
}

function clearDraft() {
  try { sessionStorage.removeItem(draftKey()); } catch (error) { /* sessionStorage indisponível */ }
}

async function refreshContextUsage() {
  if (!el.contextWidget) return;
  try {
    const res = await call("get_context_usage");
    if (!res.ok) {
      el.contextLabel.textContent = "contexto indisponível";
      return;
    }
    contextUsage = res;
    const limit = Math.max(0, Number(res.limit) || 0);
    const used = Number(res.used) || 0;
    const percent = Number(res.percent) || 0;
    const segment = (node, key) => {
      if (node) node.style.width = (limit ? Math.min(100, ((Number(res.parts?.[key]) || 0) / limit) * 100) : 0) + "%";
    };
    segment(el.contextSystem, "sistema");
    segment(el.contextMemory, "memoria");
    segment(el.contextSummary, "resumo");
    segment(el.contextMessages, "mensagens");
    segment(el.contextTools, "ferramentas");
    el.contextLabel.textContent = limit ? `≈${formatTokens(used)} / ${formatTokens(limit)} · ${percent.toFixed(1).replace(".", ",")}%` : `≈${formatTokens(used)} · sem limite`;
    el.contextWidget.classList.toggle("over", percent >= 100);
    el.contextWidget.classList.toggle("warn", percent >= 80 && percent < 100);
    if (el.contextBanner) {
      const show = percent >= 80 && !res.compacted && !contextWarningDismissed;
      el.contextBanner.classList.toggle("hidden", !show);
      if (show && el.contextBannerText) {
        el.contextBannerText.textContent = `Contexto a ${percent.toFixed(1).replace(".", ",")}% — compactar para libertar espaço?`;
      }
    }
    el.contextWidget.title =
      (limit ? `Janela de contexto estimada: ≈${used} de ${limit} tokens\n` : `≈${used} tokens; sem limite definido na app. O fornecedor mantém a sua capacidade máxima.\n`) +
      `${res.total_messages} mensagens (${res.older} fora da janela de ${res.history_window})\n` +
      `sistema ${res.parts?.sistema || 0} · memória ${res.parts?.memoria || 0} · resumo ${res.parts?.resumo || 0} · ` +
      `mensagens ${res.parts?.mensagens || 0} · ferramentas ${res.parts?.ferramentas || 0}` +
      (res.compacted ? "\nContexto compactado com resumo." : "");
    const costEl = $("#conversation-cost");
    const cost = res.cost;
    if (costEl) {
      const any = !!cost && (cost.turns > 0 || cost.unknown_turns > 0);
      costEl.classList.toggle("hidden", !any);
      if (any) {
        costEl.textContent = cost.turns
          ? (cost.exact ? "" : "≈") + formatCost(cost.usd) + (cost.unknown_turns ? " + ?" : "")
          : "custo ?";
        const lines = [cost.turns
          ? `Custo desta conversa: ${cost.exact ? "" : "≈"}${formatCost(cost.usd)} em ${cost.turns} resposta(s)`
          : "Custo desta conversa: desconhecido"];
        if (cost.unknown_turns) lines.push(`${cost.unknown_turns} resposta(s) sem preço conhecido — não entram no total`);
        lines.push(`tokens: ${cost.prompt_tokens} de entrada · ${cost.completion_tokens} de saída`);
        for (const row of cost.models || []) lines.push(`${row.model_id}: ${row.unknown && !row.usd ? "sem preço" : formatCost(row.usd)} · ${formatTokens(row.tokens)} tokens`);
        if (cost.subagents && cost.subagents.tasks) lines.push(`inclui ${cost.subagents.tasks} subagente(s): ${formatCost(cost.subagents.usd)}`);
        lines.push(cost.note || "");
        costEl.title = lines.filter(Boolean).join("\n");
      }
    }
    if (Array.isArray(res.tasks)) renderAgentTasks(res.tasks);
  } catch (error) {
    if (el.contextLabel) el.contextLabel.textContent = "—";
  }
}

function renderConversation(messages) {
  el.chat.innerHTML = "";
  if (!messages.length) {
    el.chat.innerHTML = `
      <div class="welcome">
        <img class="welcome-logo" src="assets/meistercode.png" alt="MeisterCode" />
        <h2>Olá</h2>
      </div>`;
    return;
  }
  const lastAssistant = messages.reduce((last, message, index) => (message.role === "assistant" ? index : last), -1);
  messages.forEach((message, index) => {
    el.chat.appendChild(renderMessage(message, index, { isLastAssistant: index === lastAssistant }));
  });
  el.chat.scrollTop = el.chat.scrollHeight;
}

function mediaList(m) {
  if (Array.isArray(m.media)) return m.media;
  return (m.images || []).map((p) => ({ path: p, type: "image" }));
}

function renderMessage(m, index = null, options = {}) {
  const wrap = document.createElement("div");
  const isSummary = m.role === "summary";
  wrap.className = "msg " + (isSummary ? "assistant summary-msg" : m.role === "user" ? "user" : "assistant");
  if (index != null) wrap.dataset.index = String(index);

  const head = document.createElement("div");
  head.className = "msg-head";
  head.innerHTML = `<span class="avatar">${isSummary ? "🗜️" : m.role === "user" ? "🧑" : "🤖"}</span><span class="role">${isSummary ? "Resumo" : m.role === "user" ? "Tu" : "Assistente"}</span>`;
  wrap.appendChild(head);

  if (m.text) {
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = formatText(m.text);
    renderMath(bubble);
    wrap.appendChild(bubble);
  }

  const files = (m.files || []).filter((f) => f.kind === "text" || f.kind === "other");
  if (files.length) {
    const fr = document.createElement("div");
    fr.className = "msg-files";
    for (const f of files) {
      const chip = document.createElement("span");
      chip.className = "file-chip";
      chip.textContent = "📄 " + (f.name || "ficheiro");
      fr.appendChild(chip);
    }
    wrap.appendChild(fr);
  }

  const media = mediaList(m);
  if (media.length) {
    const mr = document.createElement("div");
    mr.className = "msg-media";
    for (const item of media) mr.appendChild(mediaEl(item));
    wrap.appendChild(mr);
  }

  if (Array.isArray(m.steps) && m.steps.length) {
    wrap.appendChild(renderSteps(m.steps));
  }
  // O pedido parou antes de acabar (limite, verificação por resolver, modelo calado): diz-se no fim, onde a pessoa está a olhar.
  if (m.role === "assistant" && m.stop_reason && options.isLastAssistant) {
    const stopped = document.createElement("div");
    stopped.className = "notice warn msg-stopped";
    const why = document.createElement("span");
    why.textContent = "⏸ O pedido parou antes de terminar: " + m.stop_reason.replace(/[.\s]+$/, "") + ". Queres que continue?";
    const go = document.createElement("button");
    go.type = "button"; go.className = "btn small"; go.textContent = "Continuar";
    go.onclick = () => continueStoppedTurn();
    stopped.append(why, go);
    wrap.appendChild(stopped);
  }
  if (m.role === "assistant" && m.usage?.total_tokens) {
    const usage = document.createElement("div");
    usage.className = "msg-usage";
    usage.textContent = `≈${formatTokens(m.usage.total_tokens)} tokens`;
    if (m.cost && Number.isFinite(Number(m.cost.usd))) {
      const exact = m.cost.source === "provider";
      usage.textContent += ` · ${exact ? "" : "≈"}${formatCost(m.cost.usd)}`;
      usage.title = exact ? "Custo indicado pelo provedor."
        : m.cost.source === "manual" ? "Estimativa: tokens × os preços que definiste nos limites de execução."
        : "Estimativa: tokens × o preço do catálogo do provedor.";
    }
    wrap.appendChild(usage);
  }
  if (index != null) {
    const actions = document.createElement("div");
    actions.className = "msg-actions";
    addMessageAction(actions, "copiar", "Copiar o texto desta mensagem", () => copyText(m.text || "", "Mensagem copiada."));
    if (m.role === "user") {
      addMessageAction(actions, "editar", "Editar e reenviar esta mensagem", () => openEditMessage(index, m));
    }
    if (m.role === "assistant" && options.isLastAssistant) {
      addMessageAction(actions, "regenerar", "Gerar outra resposta para o último pedido", () => regenerateMessage());
    }
    addMessageAction(actions, "ramificar", "Criar uma conversa nova a partir daqui", () => branchMessage(index));
    wrap.appendChild(actions);
  }
  return wrap;
}

// «Continuar»: manda o pedido de continuação sem estragar o que a pessoa já tinha escrito na caixa.
function continueStoppedTurn() {
  if (chatBusy) return;
  const draft = el.composer.value;
  el.composer.value = "Continua o trabalho a partir de onde ficaste.";
  send();
  el.composer.value = draft;
  autosize();
}

function addMessageAction(bar, label, title, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn ghost tiny";
  button.textContent = label;
  button.title = title;
  button.onclick = async () => {
    button.disabled = true;
    try { await handler(); } finally { button.disabled = false; }
  };
  bar.appendChild(button);
}

async function copyText(text, message = "Copiado.") {
  try {
    await navigator.clipboard.writeText(text);
    toast(message, "success");
  } catch (error) {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    toast(message, "success");
  }
}

function openEditMessage(index, message) {
  showModal({
    title: "Editar mensagem",
    okLabel: "Guardar e reenviar",
    bodyHTML: `<label class="field"><span>Mensagem</span><textarea id="edit-message" rows="6">${esc(message.text || "")}</textarea></label>
      <p class="hint">As mensagens seguintes serão removidas e o modelo responde de novo. Os anexos desta mensagem são mantidos.</p>`,
    onOk: async () => {
      const text = $("#edit-message").value;
      setBusy(true);
      showTyping(true);
      try {
        const result = await call("edit_resend", index, text);
        if (!result.ok) { showError(result.error); return false; }
        await loadConversation();
        return true;
      } finally {
        showTyping(false);
        setBusy(false);
      }
    },
  });
}

async function regenerateMessage() {
  if (chatBusy) return;
  setBusy(true);
  showTyping(true);
  try {
    const result = await call("regenerate");
    if (!result.ok) showError(result.error);
    await loadConversation();
  } finally {
    showTyping(false);
    setBusy(false);
  }
}

async function branchMessage(index) {
  const result = await call("branch_conversation", index);
  if (!result.ok) return showError(result.error);
  applyState(result);
  mediaCache.clear();
  await loadConversation();
  toast("Conversa ramificada.", "success");
}

function scrollToMessage(index) {
  const target = el.chat.querySelector(`[data-index="${Number(index)}"]`);
  if (!target) return;
  target.scrollIntoView({ block: "center", behavior: "smooth" });
  target.classList.add("highlight-message");
  setTimeout(() => target.classList.remove("highlight-message"), 1600);
}

// Lista de tarefas do agente: o Python chama window.showAgentTasks sempre que o modelo a altera.
function renderAgentTasks(tasks) {
  const box = $("#task-plan");
  const list = $("#task-plan-list");
  if (!box || !list) return;
  const rows = Array.isArray(tasks) ? tasks : [];
  const done = rows.filter((task) => task.state === "done").length;
  const doing = rows.find((task) => task.state === "doing");
  box.classList.toggle("hidden", !rows.length);
  $("#task-plan-summary").textContent = !rows.length ? "" :
    `📋 Tarefas ${done}/${rows.length}` + (doing ? ` · em curso: ${doing.text}` : done === rows.length ? " · tudo concluído" : "");
  // abre sozinha quando nasce uma lista com trabalho por fazer; depois respeita o que o utilizador escolher
  const pending = rows.length > done;
  if (pending && box.dataset.pending !== "1") box.open = true;
  box.dataset.pending = pending ? "1" : "0";
  const apply = async (...args) => {
    const res = await call("update_context_record", ...args);
    if (!res.ok) return showError(res.error);
    renderAgentTasks(res.continuity?.tasks || []);
  };
  const marks = { open: "☐", doing: "▶", done: "☑" };
  const labels = { open: "pendente", doing: "em curso", done: "concluída" };
  list.replaceChildren();
  for (const task of rows) {
    const item = document.createElement("li");
    item.className = task.state;
    item.title = `${labels[task.state] || task.state} — clica para ${task.state === "done" ? "reabrir" : "marcar como concluída"}`;
    const mark = document.createElement("span");
    mark.className = "task-mark";
    mark.textContent = marks[task.state] || "•";
    const text = document.createElement("span");
    text.className = "task-text";
    text.textContent = task.text;
    item.append(mark, text);
    item.onclick = () => apply("task", task.text, task.id, task.state === "done" ? "open" : "done");
    list.appendChild(item);
  }
  const clear = $("#task-plan-clear");
  if (clear) {
    clear.classList.toggle("hidden", !done);
    clear.onclick = async () => {
      for (const task of rows.filter((row) => row.state === "done")) await apply("remove", "", task.id);
    };
  }
}
window.showAgentTasks = renderAgentTasks;

function renderSteps(steps) {
  const det = document.createElement("details");
  det.className = "agent-steps";
  const sum = document.createElement("summary");
  const nOk = steps.filter((s) => s.ok).length;
  const nBad = steps.length - nOk;
  const totalMs = steps.reduce((total, step) => total + (Number(step.duration_ms) || 0), 0);
  sum.textContent = `🔧 ${steps.length} ação(ões) do agente · ${nOk} ok` + (nBad ? ` · ${nBad} com erro` : "") + (totalMs ? ` · ${totalMs} ms` : "");
  det.appendChild(sum);
  // Fica recolhido para a conversa acabar na última palavra do agente (pedido do user, 24/11/2026); abre-se num clique.
  det.open = false;
  if (nBad) det.classList.add("has-bad");
  const icons = { mcp: "🔌", browser: "🌐", tool: "🧰", cmd: "⌨️", write: "✎", read: "👁", list: "📁", error: "⚠️", tasks: "📋" };
  for (const s of steps) {
    const row = document.createElement("div");
    row.className = "step " + (s.ok ? "ok" : "bad");
    const t = document.createElement("div");
    t.className = "step-title";
    const duration = Number(s.duration_ms) || 0;
    t.textContent = (s.ok ? "✓ " : "✕ ") + (icons[s.kind] || "•") + " " + (s.title || s.kind || "ação") + (duration ? ` · ${duration} ms` : "");
    row.appendChild(t);
    if (s.body) {
      const b = document.createElement("pre");
      b.className = "step-body";
      b.textContent = s.body;
      row.appendChild(b);
    }
    if (s.diff) {
      const diff = document.createElement("pre");
      diff.className = "step-diff";
      for (const line of String(s.diff).split("\n")) {
        const span = document.createElement("span");
        span.className = line.startsWith("+") ? "d-add" : line.startsWith("-") ? "d-del" : "d-ctx";
        span.textContent = line + "\n";
        diff.appendChild(span);
      }
      row.appendChild(diff);
    }
    det.appendChild(row);
  }
  return det;
}

function mediaEl(item) {
  const type = item.type || "image";
  if (type === "video") {
    const v = document.createElement("video");
    v.controls = true; v.preload = "metadata"; v.className = "m-video";
    loadMedia(item.path).then((s) => { if (s) v.src = s; });
    return v;
  }
  if (type === "audio") {
    const box = document.createElement("div");
    box.className = "m-audio";
    const a = document.createElement("audio");
    a.controls = true; a.preload = "metadata";
    loadMedia(item.path).then((s) => { if (s) a.src = s; });
    box.appendChild(a);
    return box;
  }
  const img = document.createElement("img");
  img.className = "m-image";
  img.addEventListener("click", () => { if (img.src) openLightbox(img.src); });
  if (item.previewUrl) img.src = item.previewUrl;           // mensagem otimista
  else loadMedia(item.path).then((s) => { if (s) img.src = s; });
  return img;
}

async function loadMedia(path) {
  if (mediaCache.has(path)) return mediaCache.get(path);
  const res = await call("get_media", path);
  if (res.ok && res.b64) {
    const src = "data:" + (res.mime || "application/octet-stream") + ";base64," + res.b64;
    mediaCache.set(path, src);
    return src;
  }
  return null;
}

async function send() {
  if (chatBusy || attachmentReads) return;
  const text = el.composer.value.trim();
  if (!text && pendingAttachments.length === 0) return;
  clearError();

  const pend = pendingAttachments.slice();
  const attachments = pend.map((a) => ({ name: a.name, mime: a.mime, b64: a.b64 }));

  // Mostra já a mensagem do utilizador no chat (antes de o modelo responder).
  appendOptimisticUser(text, pend);

  el.composer.value = "";
  autosize();
  clearDraft();
  pendingAttachments = [];
  renderAttachments();

  setBusy(true);
  showTyping(true);
  const res = await call("chat", text, attachments);
  showTyping(false);
  setBusy(false);
  if (!res.ok) showError(res.error);
  await loadConversation();
  if (res.ok && res.compacted !== undefined) {
    toast(`Contexto compactado: ${res.compacted} mensagens resumidas, ${res.kept} mantidas.`, "success", { label: "Desfazer", run: undoCompaction });
  }
}

function appendOptimisticUser(text, attachments) {
  const welcome = el.chat.querySelector(".welcome");
  if (welcome) el.chat.innerHTML = "";
  const msg = {
    role: "user",
    text,
    media: attachments.filter((a) => a.isImage).map((a) => ({ type: "image", previewUrl: a.previewUrl })),
    files: attachments.filter((a) => !a.isImage).map((a) => ({ name: a.name, kind: "other" })),
  };
  el.chat.appendChild(renderMessage(msg));
  el.chat.scrollTop = el.chat.scrollHeight;
}

function showTyping(on) {
  let t = document.getElementById("typing");
  if (on) {
    if (!t) {
      t = document.createElement("div");
      t.id = "typing";
      t.className = "msg assistant";
      t.innerHTML = `<div class="msg-head"><span class="avatar">🤖</span><span class="role">Assistente</span></div>` +
        `<div class="bubble typing-bubble"><span></span><span></span><span></span></div>`;
      el.chat.appendChild(t);
      el.chat.scrollTop = el.chat.scrollHeight;
    }
  } else if (t) {
    t.remove();
  }
}

window.startStream = function () {
  if (chatStreamEl) return;
  const wrap = document.createElement("div");
  wrap.className = "msg assistant streaming-msg";
  wrap.style.display = "none";
  const head = document.createElement("div");
  head.className = "msg-head";
  head.innerHTML = `<span class="avatar">🤖</span><span class="role">Assistente</span>`;
  const bubble = document.createElement("div");
  bubble.className = "bubble streaming-bubble";
  wrap.append(head, bubble);
  el.chat.appendChild(wrap);
  chatStreamEl = wrap;
  chatStreamText = "";
};

window.appendStream = function (text) {
  if (!chatStreamEl) window.startStream();
  if (!chatStreamEl || !text) return;
  showTyping(false);
  chatStreamEl.style.display = "";
  chatStreamText += text;
  const bubble = chatStreamEl.querySelector(".bubble");
  if (bubble) bubble.textContent = chatStreamText;
  el.chat.scrollTop = el.chat.scrollHeight;
};

window.endStream = function () {
  if (!chatStreamEl) return;
  chatStreamEl.remove();
  chatStreamEl = null;
  chatStreamText = "";
};

async function newConversation() {
  if (!confirm("Começar uma conversa nova? A atual deixa de aparecer.")) return;
  const res = await call("new_conversation");
  if (!res.ok) return showError(res.error);
  renderConversation([]);
  refreshContextUsage();
}

function setBusy(busy) {
  chatBusy = busy;
  if($('#sel-agent-profile'))$('#sel-agent-profile').disabled=busy;
  el.btnSend.disabled = busy || attachmentReads > 0;
  if (el.btnStop) {
    el.btnStop.classList.toggle("hidden", !busy);
    el.btnStop.disabled = false;
  }
  if (el.btnSend) el.btnSend.classList.toggle("hidden", busy);
  el.composer.disabled = busy;
  el.status.className = "status" + (busy ? " busy" : "");
  el.status.textContent = busy ? "A trabalhar…  (vídeo pode demorar 1–3 min)" : "";
}

function setStatusMessage(msg) {
  el.status.className = "status";
  el.status.textContent = msg || "";
  if (msg) setTimeout(() => { if (el.status.textContent === msg) el.status.textContent = ""; }, 5000);
}

function toast(message, type = "info", action = null) {
  const box = $("#toasts");
  if (!box) return;
  const item = document.createElement("div");
  item.className = "toast " + type;
  const text = document.createElement("span");
  text.textContent = message;
  item.appendChild(text);
  if (action) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn ghost tiny";
    button.textContent = action.label;
    button.onclick = async () => {
      item.remove();
      try { await action.run(); } catch (error) { showError(error.message); }
    };
    item.appendChild(button);
  }
  const close = document.createElement("button");
  close.type = "button";
  close.className = "btn ghost tiny";
  close.textContent = "×";
  close.onclick = () => item.remove();
  item.appendChild(close);
  box.appendChild(item);
  setTimeout(() => item.remove(), 6000);
}
