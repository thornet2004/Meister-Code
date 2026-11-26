"use strict";
// Arranque (init, eventos) e aplicação do estado. Carrega em último lugar.
// Script clássico: partilha o âmbito global com os outros ficheiros app-*.js (ver index.html).

/* ---------------- Arranque ---------------- */
window.addEventListener("pywebviewready", init);
if (window.pywebview && window.pywebview.api) setTimeout(() => init().catch(() => {}), 0);

let inited = false;
async function init() {
  if (inited) return;
  inited = true;
  cacheEls();
  bindEvents();
  await refreshState();
  await loadConversation();
}

function cacheEls() {
  el.projectsList = $("#projects-list");
  el.conversationsList = $("#conversations-list");
  el.sidebarSearch = $("#sidebar-search");
  el.agentBadge = $("#agent-badge");
  el.providersList = $("#providers-list");
  el.slots = { chat: $("#sel-chat"), code: $("#sel-code"), image: $("#sel-image"), video: $("#sel-video"), audio: $("#sel-audio") };
  el.chat = $("#chat");
  el.composer = $("#composer");
  el.attachments = $("#attachments");
  el.fileInput = $("#file-input");
  el.btnSend = $("#btn-send");
  el.btnStop = $("#btn-stop");
  el.status = $("#chat-status");
  el.contextWidget = $("#context-widget");
  el.contextSystem = $("#context-system");
  el.contextMemory = $("#context-memory");
  el.contextSummary = $("#context-summary");
  el.contextMessages = $("#context-messages");
  el.contextTools = $("#context-tools");
  el.contextLabel = $("#context-label");
  el.contextLimit = $("#context-limit");
  el.contextCompact = $("#context-compact");
  el.contextBanner = $("#context-banner");
  el.contextBannerText = $("#context-banner-text");
  el.contextBannerCompact = $("#context-banner-compact");
  el.contextBannerDismiss = $("#context-banner-dismiss");
  el.errorBox = $("#error-box");
  el.activeName = $("#active-name");
  el.activePill = $("#active-pill");
  el.configPath = $("#config-path");
  el.gallery = $("#gallery");
  el.agEnabled = $("#ag-enabled");
  el.agScope = $("#ag-scope");
  el.agApproval = $("#ag-approval");
  el.agWarn = $("#ag-warn");
  el.agDangerous = $("#ag-dangerous");
}

function bindEvents() {
  $('#sel-agent-profile').onchange=async event=>{
    const result=await call('set_preference','agent_profile',event.target.value);
    if(!result.ok){showError(result.error);event.target.value=state.preferences.agent_profile||'build';return;}
    applyState(result);
  };
  window.MCPSettings.init();
  $("#btn-terminal").addEventListener("click", () => toggleTerminal());
  $("#terminal-close").addEventListener("click", () => toggleTerminal(false));
  $("#terminal-clear").addEventListener("click", () => { $("#terminal-output").textContent = ""; });
  $("#terminal-form").addEventListener("submit", runTerminal);
  $("#terminal-stop").addEventListener("click", stopTerminal);
  $("#terminal-input").addEventListener("keydown", (event) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    terminalHistoryIndex = Math.max(0, Math.min(terminalHistory.length,
      terminalHistoryIndex + (event.key === "ArrowUp" ? -1 : 1)));
    event.target.value = terminalHistory[terminalHistoryIndex] || "";
  });
  $("#btn-browser").addEventListener("click", () => openBrowser());
  $("#browser-close").addEventListener("click", closeBrowser);
  $("#browser-form").addEventListener("submit", (event) => { event.preventDefault(); navigateBrowser(); });
  $("#browser-local").addEventListener("click", () => { $("#browser-url").value = "http://localhost:3000"; navigateBrowser(); });
  for (const action of ["back", "forward", "reload"]) {
    $("#browser-" + action).addEventListener("click", () => call("browser_action", action));
  }
  new ResizeObserver(() => syncBrowserBounds()).observe($("#browser-viewport"));
  window.addEventListener("resize", syncBrowserBounds);
  const modalObserver = new MutationObserver(syncBrowserBounds);
  for (const modal of document.querySelectorAll(".modal-overlay, .lightbox")) {
    modalObserver.observe(modal, {attributes: true, attributeFilter: ["class"]});
  }
  bindFileDrop();
  $("#btn-add-project").addEventListener("click", openCreateProject);
  $("#btn-add-conversation").addEventListener("click", createConversation);
  $("#agent-badge").addEventListener("click", openSettings);
  $("#btn-open-dir").addEventListener("click", () => call("open_output_dir"));
  $("#btn-new-chat").addEventListener("click", createConversation);
  $("#btn-rig-admin").addEventListener("click", () => window.openRigAdmin && window.openRigAdmin());
  $("#btn-gallery").addEventListener("click", openGallery);
  $("#gallery-close").addEventListener("click", () => $("#gallery-modal").classList.add("hidden"));

  $("#btn-settings").addEventListener("click", openSettings);
  $("#settings-close").addEventListener("click", closeSettings);
  $("#settings-done").addEventListener("click", closeSettings);
  $("#btn-add-provider").addEventListener("click", openAddProvider);

  el.agEnabled.addEventListener("change", onAgentChange);
  el.agScope.addEventListener("change", onAgentChange);
  el.agApproval.addEventListener("change", onAgentChange);
  el.agDangerous.addEventListener("change", onAgentChange);

  $("#approval-allow").addEventListener("click", () => respondApproval("allow"));
  $("#approval-session").addEventListener("click", () => respondApproval("session"));
  $("#approval-deny").addEventListener("click", () => respondApproval("deny"));

  el.btnSend.addEventListener("click", send);
  el.btnStop.addEventListener("click", async () => {
    el.btnStop.disabled = true;
    try { await call("cancel_chat"); setStatusMessage("A interromper…"); }
    finally { el.btnStop.disabled = false; }
  });
  el.contextCompact.addEventListener("click", compactContext);
  el.contextLimit.addEventListener("click", setContextWindow);
  $("#theme-select").onchange = async () => {
    const result = await call("set_preference", "theme", $("#theme-select").value);
    if (!result.ok) return showError(result.error);
    applyState(result);
  };
  $("#btn-theme-toggle").onclick = async () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    const result = await call("set_preference", "theme", next);
    if (!result.ok) return showError(result.error);
    applyState(result);
  };
  { const field = $("#agent-name-input");
    if (field) field.onchange = async () => {
      const result = await call("set_preference", "agent_name", field.value.trim());
      if (!result.ok) { showError(result.error); return; }
      field.value = result.preferences?.agent_name ?? field.value.trim();
      state.preferences = result.preferences || state.preferences; }; }
  { const field = $("#voice-listen-input");
    if (field) field.onchange = async () => {
      const result = await call("set_preference", "voice_listen_seconds", parseInt(field.value, 10));
      if (!result.ok) { showError(result.error); field.value = state.preferences?.voice_listen_seconds ?? 8; return; }
      field.value = result.preferences?.voice_listen_seconds ?? field.value;
      state.preferences = result.preferences || state.preferences; }; }
  $("#personality-select").onchange = async () => {
    const result = await call("set_preference", "personality", $("#personality-select").value);
    if (!result.ok) return showError(result.error);
    applyState(result);
    setStatusMessage("Personalidade alterada: vale a partir da próxima mensagem.");
  };
  $("#density-select").onchange = async () => {
    const result = await call("set_preference", "density", $("#density-select").value);
    if (!result.ok) return showError(result.error);
    applyState(result);
  };
  $("#auto-compact").onchange = async () => {
    const result = await call("set_preference", "auto_compact", $("#auto-compact").checked);
    if (!result.ok) return showError(result.error);
    applyState(result);
  };
  if (el.contextBannerCompact) el.contextBannerCompact.onclick = compactContext;
  if (el.contextBannerDismiss) el.contextBannerDismiss.onclick = () => {
    contextWarningDismissed = true;
    el.contextBanner.classList.add("hidden");
  };
  window.matchMedia?.("(prefers-color-scheme: dark)")?.addEventListener?.("change", applyTheme);
  for (const slot of MODEL_SLOTS) el.slots[slot].addEventListener("change", () => onSlotChange(slot));
  $("#sel-voice").addEventListener("change", onVoiceChange);
  el.sidebarSearch.addEventListener("input", () => {
    sidebarQuery = el.sidebarSearch.value.trim().toLowerCase();
    renderProjects();
    renderConversations();
  });
  const resizer = $("#side-resizer");
  if (resizer) {
    try {
      const saved = localStorage.getItem("studio-side-width");
      if (saved) document.documentElement.style.setProperty("--side-width", Math.max(220, Math.min(520, Number(saved) || 328)) + "px");
    } catch (error) { /* localStorage indisponível */ }
    resizer.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      const side = document.querySelector(".side");
      if (!side) return;
      const startX = event.clientX;
      const startWidth = side.getBoundingClientRect().width;
      const move = (moveEvent) => {
        const width = Math.max(220, Math.min(520, startWidth + moveEvent.clientX - startX));
        document.documentElement.style.setProperty("--side-width", width + "px");
        if (browserOpen) syncBrowserBounds();
      };
      const stop = () => {
        document.removeEventListener("pointermove", move);
        document.body.classList.remove("resizing");
        try { localStorage.setItem("studio-side-width", String(Math.round(side.getBoundingClientRect().width))); } catch (error) { /* localStorage indisponível */ }
      };
      document.body.classList.add("resizing");
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", stop, { once: true });
    });
  }

  $("#btn-attach").addEventListener("click", () => el.fileInput.click());
  el.fileInput.addEventListener("change", onFilesChosen);

  el.composer.addEventListener("input", autosize);
  el.composer.addEventListener("input", saveDraft);
  el.composer.addEventListener("input", updateSlashMenu);
  $("#palette-input").addEventListener("input", (event) => renderPalette(event.target.value));
  $("#palette-input").addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      paletteIndex = Math.min(paletteIndex + 1, Math.max(0, paletteItems.length - 1));
      renderPaletteList();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      paletteIndex = Math.max(0, paletteIndex - 1);
      renderPaletteList();
    } else if (event.key === "Enter") {
      event.preventDefault();
      runPaletteItem(paletteItems[paletteIndex]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      closePalette();
    }
  });
  $("#palette").addEventListener("click", (event) => {
    if (event.target.id === "palette") closePalette();
  });
  document.addEventListener("keydown", (event) => {
    if (!$("#approval-modal").classList.contains("hidden")) {
      const key = event.key.toLowerCase();
      if (key === "a") { event.preventDefault(); respondApproval("allow"); return; }
      if (key === "d" || event.key === "Escape") { event.preventDefault(); respondApproval("deny"); return; }
      if (key === "s") { event.preventDefault(); respondApproval("session"); return; }
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      togglePalette();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "c") {
      event.preventDefault();
      compactContext();
      return;
    }
    if (event.key === "Escape") {
      if (!$("#palette").classList.contains("hidden")) { closePalette(); return; }
      if (!$("#settings-modal").classList.contains("hidden")) { closeSettings(); return; }
      if (!$("#modal").classList.contains("hidden")) { hideModal(); return; }
    }
    if (event.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName) && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      el.composer.focus();
    }
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest?.("#slash-menu") && event.target !== el.composer) {
      $("#slash-menu").classList.add("hidden");
    }
  });
  document.addEventListener("click", (event) => {
    const button = event.target.closest?.(".copy-code");
    if (button) copyCode(button);
  });
  el.composer.addEventListener("keydown", (e) => {
    if (handleSlashKey(e)) return;
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });

  $("#modal-close").addEventListener("click", hideModal);
  $("#modal-cancel").addEventListener("click", hideModal);
  $("#lightbox").addEventListener("click", () => $("#lightbox").classList.add("hidden"));
}

/* ---------------- Estado / render ---------------- */
async function refreshState() {
  applyState(await call("get_state"));
}

function applyState(res) {
  if (!res.ok) return showError(res.error);
  clearError();
  const modelOrder = new Intl.Collator('pt-PT', { sensitivity: 'base', numeric: true });
  const compareModels = (a, b) => modelOrder.compare(a.name || a.id || '', b.name || b.id || '') || modelOrder.compare(a.id || '', b.id || '');
  state.providers = (res.providers || []).map(provider => ({
    ...provider,
    models: [...(provider.models || [])].sort(compareModels),
    catalog: [...(provider.catalog || [])].sort(compareModels),
  }));
  state.projects = res.projects || [];
  state.activeProjectId = res.active_project_id || "";
  state.conversations = res.conversations || [];
  state.activeConversationId = res.active_conversation_id || "";
  if (res.kinds) state.kinds = res.kinds;
  if (res.kind_caps) state.kindCaps = res.kind_caps;
  if (res.kind_details) state.kindDetails = res.kind_details;
  state.selections = res.selections || state.selections;
  if (res.preferences) state.preferences = res.preferences;
  if (res.rig) state.rig = res.rig;
  // Online ou local: em modo local só se veem os modelos da rig — os online (conversa, imagem, vídeo e áudio) nem
  // aparecem, para não induzir em erro (pedido do user, 24/11/2026). As Configurações listam sempre os online (allProviders).
  state.allProviders = state.providers;
  state.providers = state.rig && state.rig.enabled
    ? state.providers.filter(provider => provider.rig)
    : state.providers.filter(provider => !provider.rig);
  if($('#sel-agent-profile'))$('#sel-agent-profile').value=state.preferences.agent_profile||'build';
  {const selection=state.preferences.agent_models?.[state.preferences.agent_profile||'build'],note=$('#agent-model-override');
   if(note){const p=state.providers.find(p=>p.id===selection?.provider_id),m=p?.models?.find(m=>m.id===selection?.model_id);note.textContent=selection?.model_id?'Modelo efetivo deste perfil: '+(p?.name||selection.provider_id)+' · '+(m?.name||selection.model_id):'';note.classList.toggle('hidden',!selection?.model_id);}}
  state.outputDir = res.output_dir || "";
  state.projectsRoot = res.projects_root || state.projectsRoot;
  state.conversationsRoot = res.conversations_root || state.conversationsRoot;
  if (res.config_path) state.configPath = res.config_path;

  renderActivePill();
  renderProjects();
  renderConversations();
  renderProviders();
  renderRig();
  fillModelPicker();
  syncAgentControls();
  if (!$("#settings-modal").classList.contains("hidden")) refreshToolCatalog();
  if (el.configPath) el.configPath.textContent = state.configPath || "config.json";
  applyTheme();
  restoreDraft();
  refreshContextUsage();
  syncCatalogsAutomatically();
}

async function syncCatalogsAutomatically() {
  for (const provider of state.providers) {
    if (provider.kind !== 'openrouter' || !provider.has_key || catalogSyncAttempted.has(provider.id)) continue;
    catalogSyncAttempted.add(provider.id);
    const result = await call('sync_provider_models', provider.id, false);
    if (result.ok) applyState(result);
    else showError('Não foi possível atualizar o catálogo de '+provider.name+': '+result.error+' Os modelos guardados continuam disponíveis.');
  }
}

function applyTheme() {
  const preferences = state.preferences || {};
  const theme = preferences.theme || "system";
  const systemDark = window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ?? true;
  const resolved = theme === "system" ? (systemDark ? "dark" : "light") : theme;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.classList.toggle("density-compact", (preferences.density || "comfortable") === "compact");
  const link = document.getElementById("hljs-theme");
  if (link) link.href = resolved === "light" ? "vendor/highlight-light.min.css" : "vendor/highlight-dark.min.css";
  const themeSelect = $("#theme-select");
  if (themeSelect) themeSelect.value = theme;
  const themeToggle = $("#btn-theme-toggle");
  if (themeToggle) {
    themeToggle.textContent = resolved === "dark" ? "☀️ Claro" : "🌙 Escuro";
    themeToggle.setAttribute("aria-label", resolved === "dark" ? "Ativar tema claro" : "Ativar tema escuro");
    themeToggle.title = themeToggle.getAttribute("aria-label");
  }
  const densitySelect = $("#density-select");
  if (densitySelect) densitySelect.value = preferences.density || "comfortable";
  const personality = $("#personality-select");
  if (personality) personality.value = preferences.personality || "neutra";
  const voiceTone = $("#voice-tone-select");
  if (voiceTone) voiceTone.value = preferences.voice_tone || "normal";
  const autoCompact = $("#auto-compact");
  if (autoCompact) autoCompact.checked = !!preferences.auto_compact;
  const agentName = $("#agent-name-input");
  if (agentName && document.activeElement !== agentName) agentName.value = preferences.agent_name || "";
  const voiceListen = $("#voice-listen-input");
  if (voiceListen && document.activeElement !== voiceListen) voiceListen.value = preferences.voice_listen_seconds || 8;
}
