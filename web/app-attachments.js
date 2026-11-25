"use strict";
// Anexos, terminal integrado, browser integrado e galeria.
// Script clássico: partilha o âmbito global com os outros ficheiros app-*.js (ver index.html).

/* ---------------- Anexos ---------------- */
function onFilesChosen(ev) {
  const files = [...(ev.target.files || [])];
  ev.target.value = "";
  addAttachmentFiles(files);
}

function addAttachmentFiles(files) {
  for (const file of files) {
    if (file.size > 50 * 1024 * 1024) {
      showError(`O ficheiro ${file.name} excede o limite de 50 MB por anexo.`);
      continue;
    }
    attachmentReads++;
    el.btnSend.disabled = true;
    const reader = new FileReader();
    reader.onload = () => {
      const dataURL = String(reader.result || "");
      const b64 = dataURL.includes(",") ? dataURL.split(",", 2)[1] : dataURL;
      const isImage = (file.type || "").startsWith("image/");
      pendingAttachments.push({ name: file.name, mime: file.type || "", b64, isImage, previewUrl: isImage ? dataURL : null });
      renderAttachments();
    };
    reader.onerror = () => showError(`Não foi possível ler ${file.name}.`);
    reader.onloadend = () => {
      attachmentReads--;
      el.btnSend.disabled = chatBusy || attachmentReads > 0;
    };
    reader.readAsDataURL(file);
  }
}

function bindFileDrop() {
  const panel = $(".chat-panel");
  const hint = $("#drop-hint");
  let depth = 0;
  const hasFiles = (event) => Array.from(event.dataTransfer?.types || []).includes("Files");
  const reset = () => { depth = 0; hint.classList.add("hidden"); panel.classList.remove("file-dragging"); };
  // Impede o WebView de navegar para um ficheiro largado fora da conversa.
  window.addEventListener("dragover", (event) => { if (hasFiles(event)) event.preventDefault(); });
  window.addEventListener("drop", (event) => { if (hasFiles(event)) event.preventDefault(); reset(); });
  window.addEventListener("blur", reset);
  panel.addEventListener("dragenter", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    depth++;
    hint.classList.remove("hidden");
    panel.classList.add("file-dragging");
  });
  panel.addEventListener("dragover", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  panel.addEventListener("dragleave", () => { if (--depth <= 0) reset(); });
  panel.addEventListener("drop", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    const files = Array.from(event.dataTransfer.files || []);
    reset();
    if (files.length) addAttachmentFiles(files);
    else showError("Arrasta ficheiros individuais; pastas não são suportadas.");
  });
  // Colar (Ctrl+V) ficheiros copiados no Explorador, ou uma captura de ecrã, anexa-os como se fossem arrastados.
  // Se a área de transferência também traz texto (Word, Excel…), cola-se o texto como sempre.
  $("#composer").addEventListener("paste", (event) => {
    const data = event.clipboardData;
    const files = Array.from(data?.files || []);
    if (!files.length || Array.from(data.types || []).includes("text/plain")) return;
    event.preventDefault();
    addAttachmentFiles(files);
  });
}

function toggleTerminal(force) {
  const panel = $("#terminal-panel");
  const open = force === undefined ? panel.classList.contains("hidden") : force;
  panel.classList.toggle("hidden", !open);
  $("#btn-terminal").setAttribute("aria-expanded", String(open));
  if (open) {
    $("#terminal-cwd").textContent = state.outputDir;
    $("#terminal-input").focus();
  }
}

function appendTerminal(text) {
  if (!text) return;
  const output = $("#terminal-output");
  output.textContent = (output.textContent + text).slice(-200000);
  output.scrollTop = output.scrollHeight;
}

function setTerminalBusy(busy) {
  terminalBusy = busy;
  $("#terminal-stop").classList.toggle("hidden", !busy);
  $("#terminal-prompt").textContent = busy ? "↳" : "PS >";
  $("#terminal-run").textContent = busy ? "Enviar" : "Executar";
  $("#terminal-input").placeholder = busy ? "Entrada para o programa em execução…" : "Escreve um comando…";
}

// Lê a saída enquanto o comando corre; pára quando a consola fica livre.
async function pollTerminal() {
  if (terminalPolling) return;
  terminalPolling = true;
  try {
    while (true) {
      const res = await call("terminal_read", terminalCursor);
      if (!res.ok) { appendTerminal("\n" + res.error + "\n"); setTerminalBusy(false); break; }
      appendTerminal(res.output);
      terminalCursor = res.cursor;
      if (res.cwd) $("#terminal-cwd").textContent = res.cwd;
      if (!res.busy) {
        if (terminalBusy && res.exit_code) appendTerminal(`[código de saída ${res.exit_code}]\n`);
        setTerminalBusy(false);
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
  } finally {
    terminalPolling = false;
  }
}

async function runTerminal(event) {
  event.preventDefault();
  const input = $("#terminal-input");
  // Com um programa a correr, a linha (mesmo vazia) é a entrada desse programa.
  const text = terminalBusy ? input.value : input.value.trim();
  if (!terminalBusy && !text) return;
  input.value = "";
  if (terminalBusy) {
    appendTerminal(text + "\n");
  } else {
    terminalHistory.push(text);
    terminalHistoryIndex = terminalHistory.length;
    appendTerminal(`\nPS > ${text}\n`);
  }
  const res = await call("terminal_send", text);
  if (!res.ok) { appendTerminal(res.error + "\n"); setTerminalBusy(false); return; }
  if (res.mode === "command") {
    terminalCursor = res.cursor;
    setTerminalBusy(true);
  }
  pollTerminal();
  input.focus();
}

async function stopTerminal() {
  const res = await call("terminal_stop");
  if (!res.ok) appendTerminal(res.error + "\n");
  pollTerminal();
}

async function openBrowser() {
  if (browserOpen) { closeBrowser(); return; }
  browserOpen = true;
  $(".layout").classList.add("browser-open");
  $("#browser-panel").classList.remove("hidden");
  $("#btn-browser").setAttribute("aria-expanded", "true");
  const result = await call("open_browser", "");
  if (!result.ok) { closeBrowser(); showError(result.error); return; }
  if (!browserOpen) return;
  syncBrowserBounds();
  browserPoll = setInterval(refreshBrowserState, 500);
  $("#browser-url").focus();
}

function closeBrowser() {
  browserOpen = false;
  clearInterval(browserPoll);
  call("browser_layout", {visible: false});
  $(".layout").classList.remove("browser-open");
  $("#browser-panel").classList.add("hidden");
  $("#btn-browser").setAttribute("aria-expanded", "false");
}

function syncBrowserBounds() {
  if (!browserOpen) return;
  const rect = $("#browser-viewport").getBoundingClientRect();
  // Modais HTML devem continuar à frente do controlo nativo.
  const modalOpen = Array.from(document.querySelectorAll(".modal-overlay, .lightbox")).some(node => !node.classList.contains("hidden"));
  call("browser_layout", {visible: browserNavigated && !modalOpen, x: rect.x, y: rect.y,
    width: rect.width, height: rect.height, viewport: window.innerWidth});
}

async function navigateBrowser() {
  const url = $("#browser-url").value.trim();
  if (!url) return;
  const result = await call("open_browser", url);
  if (!result.ok) { showError(result.error); return; }
  browserNavigated = true;
  $("#browser-welcome").classList.add("hidden");
  syncBrowserBounds();
  refreshBrowserState();
}

window.showBrowserForAgent = async function () {
  if (!browserOpen) await openBrowser();
  if (!browserOpen) return;
  browserNavigated = true;
  $("#browser-welcome").classList.add("hidden");
  syncBrowserBounds();
};

// Abre o painel do browser já num endereço (ex.: o botão «Administração da rig»).
window.openBrowserAt = async function (url) {
  if (!url) return;
  if (!browserOpen) await openBrowser();
  if (!browserOpen) return;
  const result = await call("open_browser", url);
  if (!result.ok) { showError(result.error); return; }
  browserNavigated = true;
  $("#browser-welcome").classList.add("hidden");
  $("#browser-url").value = url;
  syncBrowserBounds();
  refreshBrowserState();
};

// Abre a administração da rig já com a sessão iniciada (a chave é injetada no backend, nunca passa por aqui).
window.openRigAdmin = async function () {
  if (!browserOpen) await openBrowser();
  if (!browserOpen) return;
  const result = await call("open_rig_admin");
  if (!result.ok) { showError(result.error); return; }
  browserNavigated = true;
  $("#browser-welcome").classList.add("hidden");
  if (result.url) $("#browser-url").value = result.url;
  syncBrowserBounds();
  refreshBrowserState();
};

async function refreshBrowserState() {
  if (!browserOpen || browserStateBusy) return;
  browserStateBusy = true;
  try {
    syncBrowserBounds();
    const result = await call("browser_state");
    if (!result.ok) return;
    if (result.url && result.url !== "about:blank" && document.activeElement !== $("#browser-url")) $("#browser-url").value = result.url;
    $("#browser-title").textContent = result.title || "Nova aba";
    $("#browser-back").disabled = !result.back;
    $("#browser-forward").disabled = !result.forward;
    const status = $("#browser-status");
    status.textContent = result.error ? "Não foi possível carregar a página: " + result.error : result.loading ? "A carregar…" : "";
    status.classList.toggle("hidden", !status.textContent);
  } finally { browserStateBusy = false; }
}

function renderAttachments() {
  el.attachments.innerHTML = "";
  pendingAttachments.forEach((a, i) => {
    const chip = document.createElement("div");
    chip.className = "att-chip";
    chip.innerHTML = (a.isImage ? `<img src="${a.previewUrl}" alt="" />` : "📄") + `<span>${esc(a.name)}</span>`;
    const x = document.createElement("button");
    x.textContent = "✕";
    x.addEventListener("click", () => { pendingAttachments.splice(i, 1); renderAttachments(); });
    chip.appendChild(x);
    el.attachments.appendChild(chip);
  });
}

/* ---------------- Galeria ---------------- */
async function openGallery() {
  $("#gallery-modal").classList.remove("hidden");
  const res = await call("get_history");
  el.gallery.innerHTML = "";
  if (!res.ok) return showError(res.error);
  const hist = res.history || [];
  if (!hist.length) {
    el.gallery.innerHTML = '<p class="empty">Sem ficheiros ainda.</p>';
    return;
  }
  for (const entry of hist) {
    const div = document.createElement("div");
    div.className = "thumb";
    const label = `<div class="caption"><div class="p">${esc(entry.prompt) || "(sem prompt)"}</div><div>${esc(entry.model_name || entry.model_id || "")}</div></div>`;
    div.appendChild(mediaEl({ path: entry.path, type: entry.media || "image" }));
    const cap = document.createElement("div");
    cap.innerHTML = label;
    div.appendChild(cap.firstChild);
    el.gallery.appendChild(div);
  }
}

function openLightbox(src) {
  $("#lightbox-img").src = src;
  $("#lightbox").classList.remove("hidden");
}
