"use strict";
// Barra lateral: conversas soltas e projetos.
// Script clássico: partilha o âmbito global com os outros ficheiros app-*.js (ver index.html).

/* ---------------- Conversas soltas ---------------- */
function renderConversations() {
  const list = el.conversationsList;
  list.innerHTML = "";
  if (!state.conversations.length) {
    list.innerHTML = '<p class="empty">Sem conversas. Cria uma com <b>+ Nova</b>.</p>';
    return;
  }
  const conversations = state.conversations.filter((conversation) => !sidebarQuery || (conversation.title || "").toLowerCase().includes(sidebarQuery));
  if (!conversations.length) {
    list.innerHTML = '<p class="empty">Sem conversas correspondentes.</p>';
    return;
  }
  const noProject = !state.activeProjectId;
  for (const c of conversations) {
    const active = noProject && c.id === state.activeConversationId;
    const card = document.createElement("div");
    card.className = "conv-card" + (active ? " active" : "");
    card.innerHTML = `
      <button class="conv-main" data-act="activate" data-c="${esc(c.id)}">
        <span class="conv-title">${esc(c.title)}${active ? ' <span class="dot">●</span>' : ""}</span>
        <span class="conv-date">${esc(fmtDate(c.updated_at))}</span>
      </button>
      <div class="conv-actions">
        <button class="btn ghost tiny pin-button ${c.pinned ? "pinned" : ""}" data-act="pin" data-c="${esc(c.id)}" title="${c.pinned ? "Desafixar" : "Fixar"}">${c.pinned ? "★" : "☆"}</button>
        <button class="btn ghost tiny" data-act="rename" data-c="${esc(c.id)}" title="Renomear">✎</button>
        <button class="btn ghost tiny danger" data-act="delete" data-c="${esc(c.id)}" title="Apagar conversa">🗑</button>
      </div>`;
    list.appendChild(card);
  }
  list.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", onConversationAction));
}

async function onConversationAction(ev) {
  const b = ev.currentTarget;
  const { act, c: cid } = b.dataset;
  const conv = state.conversations.find((x) => x.id === cid);
  if (!conv) return;
  if (act === "activate") {
    if (!state.activeProjectId && cid === state.activeConversationId) return;
    const res = await call("set_active_conversation", cid);
    if (!res.ok) return showError(res.error);
    applyState(res);
    mediaCache.clear();
    await loadConversation();
  } else if (act === "rename") {
    openRenameConversation(conv);
  } else if (act === "pin") {
    const res = await call("set_pinned", "conversation", cid, !conv.pinned);
    if (!res.ok) showError(res.error); else applyState(res);
  } else if (act === "delete") {
    openDeleteItem(conv, "conversation");
  }
}

async function createConversation() {
  const res = await call("create_conversation", "");
  if (!res.ok) return showError(res.error);
  applyState(res);
  mediaCache.clear();
  await loadConversation();
}

function openRenameConversation(conv) {
  showModal({
    title: "Renomear conversa",
    okLabel: "Guardar",
    bodyHTML: `<label class="field"><span>Título</span><input id="cv-title" value="${esc(conv.title)}" /></label>`,
    onOk: async () => {
      const title = $("#cv-title").value.trim();
      if (!title) { showError("A conversa precisa de um título."); return false; }
      const res = await call("rename_conversation", conv.id, title);
      if (!res.ok) { showError(res.error); return false; }
      applyState(res);
      return true;
    },
  });
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/* ---------------- Projetos ---------------- */
function renderProjects() {
  const list = el.projectsList;
  list.innerHTML = "";
  if (!state.projects.length) {
    list.innerHTML = '<p class="empty">Ainda não há projetos. Cria o primeiro com <b>+ Novo</b>.</p>';
    return;
  }
  const projects = state.projects.filter((project) => !sidebarQuery || (project.name + " " + project.path).toLowerCase().includes(sidebarQuery));
  if (!projects.length) {
    list.innerHTML = '<p class="empty">Sem projetos correspondentes.</p>';
    return;
  }
  for (const p of projects) {
    const active = p.id === state.activeProjectId;
    const card = document.createElement("div");
    card.className = "project-card" + (active ? " active" : "") + (p.exists ? "" : " missing");
    card.innerHTML = `
      <button class="project-main" data-act="activate" data-p="${esc(p.id)}">
        <span class="project-name">${esc(p.name)}${active ? ' <span class="dot">●</span>' : ""}</span>
        <span class="project-path">${esc(p.path)}${p.exists ? "" : "  ⚠️ pasta em falta"}</span>
      </button>
      <div class="project-actions">
        <button class="btn ghost tiny pin-button ${p.pinned ? "pinned" : ""}" data-act="pin" data-p="${esc(p.id)}" title="${p.pinned ? "Desafixar" : "Fixar"}">${p.pinned ? "★" : "☆"}</button>
        <button class="btn ghost tiny" data-act="open" data-p="${esc(p.id)}" title="Abrir pasta">📂</button>
        <button class="btn ghost tiny" data-act="rename" data-p="${esc(p.id)}" title="Renomear">✎</button>
        <button class="btn ghost tiny danger" data-act="delete" data-p="${esc(p.id)}" title="Apagar projeto">🗑</button>
      </div>`;
    list.appendChild(card);
  }
  list.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", onProjectAction));
}

async function onProjectAction(ev) {
  const b = ev.currentTarget;
  const { act, p: pid } = b.dataset;
  const pr = state.projects.find((x) => x.id === pid);
  if (!pr) return;
  if (act === "activate") {
    if (pid === state.activeProjectId) return;
    const res = await call("set_active_project", pid);
    if (!res.ok) return showError(res.error);
    applyState(res);
    mediaCache.clear();
    await loadConversation();
  } else if (act === "open") {
    const res = await call("open_project_folder", pid);
    if (!res.ok) showError(res.error);
  } else if (act === "pin") {
    const res = await call("set_pinned", "project", pid, !pr.pinned);
    if (!res.ok) showError(res.error); else applyState(res);
  } else if (act === "rename") {
    openRenameProject(pr);
  } else if (act === "delete") {
    openDeleteProject(pr);
  }
}

function baseName(p) {
  const s = String(p || "").replace(/[\\/]+$/, "");
  const i = Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\"));
  return i >= 0 ? s.slice(i + 1) : s;
}

function openCreateProject() {
  showModal({
    title: "Novo projeto",
    okLabel: "Criar",
    bodyHTML: `
      <label class="field"><span>Nome</span><input id="pr-name" placeholder="O meu projeto" /></label>
      <p class="hint">Será criada uma subpasta própria dentro de <b>Projectos</b>, com os ficheiros, conversa, anexos e histórico.</p>
      <p class="hint path-box">${esc(state.projectsRoot)}</p>`,
    onOk: async () => {
      const name = $("#pr-name").value.trim();
      if (!name) { showError("Dá um nome ao projeto."); return false; }
      const res = await call("create_project", name);
      if (!res.ok) { showError(res.error); return false; }
      applyState(res);
      mediaCache.clear();
      await loadConversation();
      return true;
    },
  });
}

function openRenameProject(pr) {
  showModal({
    title: "Renomear projeto",
    okLabel: "Guardar",
    bodyHTML: `<label class="field"><span>Nome</span><input id="pr-name" value="${esc(pr.name)}" /></label>`,
    onOk: async () => {
      const name = $("#pr-name").value.trim();
      if (!name) { showError("O projeto precisa de um nome."); return false; }
      const res = await call("rename_project", pr.id, name);
      if (!res.ok) { showError(res.error); return false; }
      applyState(res);
      return true;
    },
  });
}

function openDeleteProject(pr) {
  openDeleteItem(pr, "project");
}

function openDeleteItem(item, type) {
  if (chatBusy) { showError("Espera que a resposta termine antes de remover este item."); return; }
  const isProject = type === "project";
  const label = isProject ? "projeto" : "conversa";
  const name = item.name || item.title;
  showModal({
    title: isProject ? "Remover projeto" : "Remover conversa",
    okLabel: "Confirmar",
    danger: true,
    bodyHTML: `
      <p>Como queres remover <b>${esc(name)}</b>?</p>
      <label class="check"><input type="radio" name="delete-mode" value="list" checked /> <span><b>Só da lista da app</b> — manter todos os ficheiros no disco</span></label>
      <label class="check"><input type="radio" name="delete-mode" id="del-files" value="disk" /> <span><b>Da lista e do disco</b> — enviar a subpasta e todo o conteúdo para a Reciclagem</span></label>
      <p class="hint path-box">${esc(item.path || "")}</p>`,
    onOk: async () => {
      const delFiles = $("#del-files").checked;
      if (delFiles) {
        const sure = confirm(
          "Enviar esta pasta e todo o conteúdo para a Reciclagem?\n\n" + item.path
        );
        if (!sure) return false;
      }
      const res = await call(isProject ? "delete_project" : "delete_conversation", item.id, delFiles);
      if (!res.ok) { showError(res.error); return false; }
      applyState(res);
      mediaCache.clear();
      await loadConversation();
      if (delFiles) {
        const how = res.deleted_files === "trash" ? "enviada para a Reciclagem"
          : res.deleted_files === "permanent" ? "apagada definitivamente" : "removida";
        setStatusMessage(`${isProject ? "Projeto" : "Conversa"} removido. Pasta ${how}.`);
      } else {
        setStatusMessage(`${label} removido só da lista. Os ficheiros foram mantidos.`);
      }
      return true;
    },
  });
}
