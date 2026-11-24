"use strict";
// Paleta de comandos, atalhos e menu de comandos /.
// Script clássico: partilha o âmbito global com os outros ficheiros app-*.js (ver index.html).

/* ---------------- Paleta de comandos e atalhos ---------------- */
const SLASH_COMMANDS = [
  { cmd: "/imagem", label: "Imagem", hint: "Gerar uma imagem a partir de uma descrição", insert: "/imagem " },
  { cmd: "/video", label: "Vídeo", hint: "Gerar um vídeo a partir de uma descrição", insert: "/video " },
  { cmd: "/audio", label: "Áudio", hint: "Converter texto em fala", insert: "/audio " },
  { cmd: "/compact", label: "Compactar", hint: "Resumir as mensagens antigas", run: () => compactContext() },
  { cmd: "/nova", label: "Nova conversa", hint: "Começar uma conversa solta", run: () => createConversation() },
  { cmd: "/modelo", label: "Modelo", hint: "Ir para o seletor de modelo", run: () => el.slots.chat.focus() },
  { cmd: "/remote-control", label: "Acesso remoto", hint: "Abrir esta conversa no telemóvel (rede de casa ou VPN)", run: () => window.openRemoteControl && window.openRemoteControl() },
];

function basePaletteItems() {
  const items = [
    { icon: "✦", label: "Nova conversa", hint: "Criar conversa solta", run: () => createConversation() },
    { icon: "📁", label: "Novo projeto", hint: "Criar um projeto", run: () => openCreateProject() },
    { icon: "⚙️", label: "Configurações", hint: "Abrir definições", run: () => openSettings() },
    { icon: "🖼️", label: "Galeria", hint: "Ver ficheiros gerados", run: () => openGallery() },
    { icon: "⌨️", label: "Terminal", hint: "Mostrar/ocultar PowerShell", run: () => toggleTerminal() },
    { icon: "🌐", label: "Browser", hint: "Mostrar/ocultar browser", run: () => toggleBrowser() },
    { icon: "🗜️", label: "Compactar contexto", hint: "Resumir mensagens antigas", run: () => compactContext() },
    { icon: "🧹", label: "Limpar conversa", hint: "Recomeçar neste contexto", run: () => newConversation() },
  ];
  for (const project of state.projects) {
    items.push({ icon: "📁", label: "Projeto: " + (project.name || project.id), hint: project.path, run: () => activateProjectById(project.id) });
  }
  for (const conversation of state.conversations) {
    items.push({ icon: "💬", label: "Conversa: " + (conversation.title || conversation.id), hint: fmtDate(conversation.updated_at), run: () => activateConversationById(conversation.id) });
  }
  for (const provider of state.providers) {
    for (const model of provider.models || []) {
      items.push({
        icon: "🧠",
        label: "Modelo: " + (model.name || model.id),
        hint: (provider.name || provider.id) + " · " + (TYPE_LABEL[model.type] || model.type),
        run: () => selectPaletteModel(provider.id, model),
      });
    }
  }
  return items;
}

function openPalette() {
  $("#palette").classList.remove("hidden");
  const input = $("#palette-input");
  input.value = "";
  paletteIndex = 0;
  renderPalette("");
  input.focus();
}

function closePalette() {
  $("#palette").classList.add("hidden");
  paletteToken += 1;
}

function togglePalette() {
  if ($("#palette").classList.contains("hidden")) openPalette(); else closePalette();
}

async function renderPalette(query) {
  const token = ++paletteToken;
  const search = (query || "").trim().toLowerCase();
  let items = basePaletteItems().filter((item) => !search || (item.label + " " + item.hint).toLowerCase().includes(search));
  if (search.length >= 2) {
    try {
      const result = await call("search_messages", search);
      if (token !== paletteToken) return;
      if (result.ok) {
        for (const hit of result.results || []) {
          items.push({
            icon: "🔎",
            label: hit.snippet,
            hint: hit.context_name + " · mensagem " + (hit.message_index + 1),
            run: () => jumpToSearchResult(hit),
          });
        }
      }
    } catch (error) { /* pesquisa opcional */ }
  }
  if (token !== paletteToken) return;
  paletteItems = items.slice(0, 24);
  paletteIndex = Math.min(paletteIndex, Math.max(0, paletteItems.length - 1));
  renderPaletteList();
}

function renderPaletteList() {
  const list = $("#palette-list");
  list.replaceChildren();
  if (!paletteItems.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "Sem resultados.";
    list.append(empty);
    return;
  }
  paletteItems.forEach((item, index) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "palette-item" + (index === paletteIndex ? " selected" : "");
    row.innerHTML = `<span class="p-icon">${esc(item.icon || "•")}</span><span class="p-label">${esc(item.label)}</span><span class="p-hint">${esc(item.hint || "")}</span>`;
    row.onclick = () => runPaletteItem(item);
    list.append(row);
  });
  list.querySelector(".selected")?.scrollIntoView({ block: "nearest" });
}

function runPaletteItem(item) {
  if (!item) return;
  closePalette();
  try { item.run(); } catch (error) { showError(error.message); }
}

async function activateProjectById(projectId) {
  const result = await call("set_active_project", projectId);
  if (!result.ok) return showError(result.error);
  applyState(result);
  mediaCache.clear();
  await loadConversation();
}

async function activateConversationById(conversationId) {
  const result = await call("set_active_conversation", conversationId);
  if (!result.ok) return showError(result.error);
  applyState(result);
  mediaCache.clear();
  await loadConversation();
}

async function selectPaletteModel(providerId, model) {
  const result = await call("set_model", model.type || "chat", providerId, model.id);
  if (!result.ok) return showError(result.error);
  applyState(result);
}

async function jumpToSearchResult(hit) {
  const result = hit.kind === "project" ? await call("set_active_project", hit.id) : await call("set_active_conversation", hit.id);
  if (!result.ok) return showError(result.error);
  applyState(result);
  mediaCache.clear();
  await loadConversation();
  setTimeout(() => scrollToMessage(hit.message_index), 120);
}

function updateSlashMenu() {
  const menu = $("#slash-menu");
  const match = el.composer.value.match(/^\/([^\s]*)$/);
  if (!match) {
    slashItems = [];
    menu.classList.add("hidden");
    return;
  }
  const query = match[1].toLowerCase();
  slashItems = SLASH_COMMANDS.filter((item) => item.cmd.slice(1).startsWith(query));
  if (!slashItems.length) {
    menu.classList.add("hidden");
    return;
  }
  slashIndex = Math.min(slashIndex, slashItems.length - 1);
  menu.replaceChildren();
  slashItems.forEach((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "slash-item" + (index === slashIndex ? " selected" : "");
    button.innerHTML = `<code>${esc(item.cmd)}</code><strong>${esc(item.label)}</strong><span>${esc(item.hint)}</span>`;
    button.onclick = () => selectSlashItem(item);
    menu.append(button);
  });
  menu.classList.remove("hidden");
}

function selectSlashItem(item) {
  $("#slash-menu").classList.add("hidden");
  if (item.run) { item.run(); return; }
  el.composer.value = item.insert || item.cmd + " ";
  autosize();
  el.composer.focus();
}

function handleSlashKey(event) {
  if ($("#slash-menu").classList.contains("hidden") || !slashItems.length) return false;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    slashIndex = (slashIndex + 1) % slashItems.length;
    updateSlashMenu();
    return true;
  }
  if (event.key === "ArrowUp") {
    event.preventDefault();
    slashIndex = (slashIndex - 1 + slashItems.length) % slashItems.length;
    updateSlashMenu();
    return true;
  }
  if (event.key === "Enter" || event.key === "Tab") {
    event.preventDefault();
    selectSlashItem(slashItems[slashIndex]);
    return true;
  }
  if (event.key === "Escape") {
    $("#slash-menu").classList.add("hidden");
    return true;
  }
  return false;
}
