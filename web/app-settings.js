"use strict";
// Agente e aprovações, configurações, provedores, seletores e modais de modelo.
// Script clássico: partilha o âmbito global com os outros ficheiros app-*.js (ver index.html).

/* ---------------- Agente ---------------- */
function syncAgentControls() {
  const ag = (state.preferences && state.preferences.agent) || {};
  el.agEnabled.checked = !!ag.enabled;
  el.agScope.value = ag.scope || "project";
  el.agApproval.value = ag.approval || "each";
  el.agDangerous.checked = ag.confirm_dangerous !== false;
  const risky = ag.enabled && (ag.scope === "computer" || ag.approval === "auto");
  el.agWarn.classList.toggle("hidden", !risky);
  // Chip "🤖 Agente" na barra de modelos
  el.agentBadge.classList.toggle("hidden", !ag.enabled);
  el.agentBadge.classList.toggle("risky", !!risky);
  if (ag.enabled) {
    const scope = ag.scope === "computer" ? "todo o PC" : "ficheiros no projeto; comandos no PC";
    const appr = ag.approval === "auto" ? "sem confirmar" : ag.approval === "writes" ? "confirma escrita" : "confirma tudo";
    el.agentBadge.title = `Agente ligado · ${scope} · ${appr} — abrir Configurações`;
  }
}

async function onAgentChange() {
  const res = await call("set_agent_settings", {
    enabled: el.agEnabled.checked,
    scope: el.agScope.value,
    approval: el.agApproval.value,
    confirm_dangerous: el.agDangerous.checked,
  });
  if (!res.ok) return showError(res.error);
  applyState(res);
}

/* ---------------- Aprovação do agente ---------------- */
let currentApprovalId = null;
window.showApproval = function (req) {
  try {
    currentApprovalId = req.id;
    const cat = $("#approval-cat");
    const dangerous = req.category === "dangerous";
    cat.textContent = dangerous ? "perigoso" : req.category === "command" ? "comando" : req.category === "write" ? "escrita" : req.category === "instalar" ? "instalar ferramenta" : req.category;
    cat.className = "badge " + (dangerous ? "danger" : req.category === "command" ? "video" : "audio");
    // Um comando perigoso e a instalação de uma ferramenta são autorizados um a um: sem "permitir nesta sessão".
    $("#approval-session").classList.toggle("hidden", dangerous || req.category === "instalar");
    $("#approval-summary").textContent = req.summary || "Ação do agente";
    $("#approval-detail").textContent = req.detail || "";
    $("#approval-modal").classList.remove("hidden");
  } catch (e) { /* ignora */ }
};
window.hideApproval = function () {
  $("#approval-modal").classList.add("hidden");
  currentApprovalId = null;
};
async function respondApproval(decision) {
  const id = currentApprovalId;
  window.hideApproval();
  if (id) await call("respond_approval", id, decision);
}

function activeProject() {
  return state.projects.find((p) => p.id === state.activeProjectId) || null;
}

function activeConversation() {
  return state.conversations.find((c) => c.id === state.activeConversationId) || null;
}

function renderActivePill() {
  const pr = activeProject();
  const label = el.activePill.querySelector(".muted");
  if (pr) {
    if (label) label.textContent = "Projeto:";
    el.activeName.textContent = pr.name;
    el.activePill.title = pr.path;
    el.activePill.classList.remove("none");
  } else {
    const c = activeConversation();
    if (label) label.textContent = "Conversa:";
    el.activeName.textContent = c ? c.title : "—";
    el.activePill.title = c ? "Conversa solta (sem projeto)" : "Sem conversa ativa.";
    el.activePill.classList.toggle("none", !c);
  }
}

/* ---------------- Configurações (modal) ---------------- */
function openSettings() { $("#settings-modal").classList.remove("hidden"); refreshToolCatalog(); }
async function refreshToolCatalog() {
  const result = await call("get_tool_catalog");
  const list = $("#tools-list");
  list.replaceChildren();
  if (!result.ok) { list.textContent = result.error; return; }
  window.MCPSettings.renderServers(result.mcp_servers || []);
  window.MCPSettings.renderPresets(result.mcp_presets || [], result.mcp_profile || "all");
  $("#tools-count").textContent = String(result.tools.length);
  for (const tool of result.tools) {
    const row = document.createElement("div");
    const name = document.createElement("code");
    name.textContent = tool.name;
    const description = document.createElement("span");
    description.textContent = tool.description;
    row.append(name, description);
    list.append(row);
  }
  for (const warning of result.mcp_warnings || []) {
    const note = document.createElement("p");
    note.className = "hint";
    note.textContent = warning;
    list.append(note);
  }
}
function closeSettings() { $("#settings-modal").classList.add("hidden"); }

/* ---------------- Provedores ---------------- */
function renderProviders() {
  const list = el.providersList;
  list.innerHTML = "";
  const others = (state.allProviders || state.providers).filter(p => !p.rig);  // a rig tem a sua própria secção
  if (!others.length) {
    list.innerHTML = '<p class="empty">Ainda não há provedores.</p>';
    return;
  }
  for (const p of others) {
    const card = document.createElement("div");
    card.className = "provider-card";
    const models = (p.models || [])
      .map(
        (m) => `
      <div class="model-row">
        <div class="model-info">
          <div class="model-name">${esc(m.name || m.id)} <span class="badge ${esc(m.type)}">${esc(TYPE_LABEL[m.type] || m.type)}</span>${Number(m.defaults?.context_window) ? ` <span class="badge">${formatTokens(Number(m.defaults.context_window))}</span>` : ""}</div>
          <div class="model-id">${esc(m.id)}</div>
        </div>
        <button class="btn ghost tiny danger" data-act="del-model" data-p="${esc(p.id)}" data-m="${esc(m.id)}">✕</button>
      </div>`
      )
      .join("");
    card.innerHTML = `
      <div class="provider-top">
        <div>
          <div class="provider-name">${esc(p.name)}</div>
          <div class="provider-meta"><code>${esc(p.kind)}</code> ${p.has_key ? "🔑" : state.kindDetails[p.kind]?.requires_key===false?'chave opcional':'<span class="no-key">sem chave</span>'}</div>
        </div>
        <div class="provider-actions">
          <button class="btn ghost tiny" data-act="edit-provider" data-p="${esc(p.id)}">editar</button>
          <button class="btn ghost tiny danger" data-act="del-provider" data-p="${esc(p.id)}">✕</button>
        </div>
      </div>
      <details class="models"><summary>${(p.models||[]).length} modelos configurados</summary>${models || '<p class="empty">Sem modelos.</p>'}</details>
      <button class="btn ghost tiny add-model-btn" data-act="add-model" data-p="${esc(p.id)}">+ Modelo</button>`;
    const discover=document.createElement('button');discover.className='btn ghost tiny';discover.textContent='Catálogo de modelos / atualizar';discover.onclick=()=>discoverModels(p.id);card.append(discover);
    list.appendChild(card);
  }
  list.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", onProviderAction));
}

/* ---------------- Online ou local (a minha rig) ---------------- */
// O utilizador escolhe um dos dois lados; o outro fica apagado e sem ação. «local» só passa a valer depois de a rig
// responder: até lá (rigDraft) a secção da rig fica aberta para escrever o endereço e a chave, e o que lá estiver
// escrito e por guardar (dataset.dirty) nunca é apagado por uma atualização do estado.
let rigDraft = false;
function renderRig() {
  const box = $("#rig-section"), online = $("#online-section"), rig = state.rig || {};
  if (!box || !online) return;
  const local = !!rig.enabled || rigDraft;
  $("#source-local").checked = local;
  $("#source-online").checked = !local;
  for (const [section, off] of [[box, !local], [online, local]]) { section.inert = off; section.classList.toggle("section-off", off); }
  $("#source-hint").textContent = rig.enabled
    ? "A conversa, o código e os subagentes correm na tua rig. Os modelos online (imagem, vídeo e áudio incluídos) ficam de fora até voltares a «Online»."
    : rigDraft ? "Ainda não estás ligado à rig: escreve o endereço e a chave em baixo. Até a rig responder, nada muda na conversa."
    : "Tudo corre nos provedores online configurados em baixo.";
  const typing = box.contains(document.activeElement) && document.activeElement.tagName === "INPUT" && document.activeElement.type !== "checkbox";
  if (!typing && !box.dataset.dirty) {
    $("#rig-address").value = rig.address || "";
    $("#rig-key").value = "";
    $("#rig-effort").value = rig.effort || "leve";
    if (rig.enabled) $("#rig-whisper").checked = !!rig.whisper;
  }
  $("#rig-key").placeholder = rig.has_key ? "guardada (escreve para trocar)" : "cola aqui a chave da rig";
  if (!box.dataset.saving && !box.dataset.failed) $("#rig-status").textContent = rig.enabled
    ? ((rig.models || []).length > 1 ? `Em uso · ${rig.models.length} modelos: ${rig.models.join(", ")}` : `Em uso · ${rig.model || "modelo"}${rig.context ? " · contexto " + formatTokens(rig.context) : ""}`)
    : rigDraft ? "Escreve o endereço e a chave da rig; a app liga-se sozinha." : "";
  const showAdmin = !!(rig.enabled && rig.admin && rig.address);   // só aparece se a chave for de administrador
  $("#rig-admin").classList.toggle("hidden", !showAdmin);
  if ($("#btn-rig-admin")) $("#btn-rig-admin").classList.toggle("hidden", !showAdmin);   // o mesmo botão na barra do topo
  if (box.dataset.bound) return;
  box.dataset.bound = "1";
  $("#rig-admin").onclick = () => {
    // abre a administração da rig (endereço LOCAL, pela VPN) já autenticada: a chave é injetada no backend.
    closeSettings();  // as Definições são um modal: fecha-as para o painel do browser ficar visível
    window.openRigAdmin();
  };
  $("#source-online").onchange = () => { rigDraft = false; delete box.dataset.failed; if ((state.rig || {}).enabled) saveRig(false); else renderRig(); };
  $("#source-local").onchange = () => {
    if ($("#rig-address").value.trim() || (state.rig || {}).address) return saveRig(true);
    rigDraft = true; renderRig(); $("#rig-address").focus();
  };
  for (const id of ["#rig-address", "#rig-key"]) {
    $(id).oninput = () => { box.dataset.dirty = "1"; };
    $(id).onchange = () => { if ($("#rig-address").value.trim()) saveRig(true); };   // escrito o endereço, tenta ligar
  }
  $("#rig-save").onclick = () => saveRig(true);
  for (const id of ["#rig-effort", "#rig-whisper"]) $(id).onchange = () => { if ((state.rig || {}).enabled) saveRig(true); else box.dataset.dirty = "1"; };
}

async function saveRig(local) {
  const box = $("#rig-section"), button = $("#rig-save");
  if (box.dataset.saving) { box.dataset.again = local ? "local" : "online"; return; }   // um pedido de cada vez; o último ganha
  const sent = { enabled: !!local, address: $("#rig-address").value.trim(), api_key: $("#rig-key").value.trim(), effort: $("#rig-effort").value, whisper: $("#rig-whisper").checked };
  box.dataset.saving = "1"; delete box.dataset.failed;
  button.disabled = true;
  if (local) { rigDraft = true; $("#rig-status").textContent = "A falar com a rig…"; }
  let result;
  try { result = await call("set_rig", sent); } finally { button.disabled = false; delete box.dataset.saving; }
  if (result.ok) {
    // só se limpa o que foi mesmo guardado: se entretanto escreveste mais, isso fica
    if ($("#rig-key").value.trim() === sent.api_key) $("#rig-key").value = "";
    if ($("#rig-address").value.trim() === sent.address && !$("#rig-key").value) delete box.dataset.dirty;
    const kept = !!(result.rig && result.rig.enabled);  // já estava em modo local: uma falha da rig não o desliga
    rigDraft = !!(local && result.rig_error && !kept);  // a rig não respondeu: continua-se online, com a secção aberta para corrigir
    if (result.rig_error) box.dataset.failed = "1";
    applyState(result);
    if (result.rig_error) $("#rig-status").textContent = "⚠️ " + result.rig_error + (kept ? " Continuas em modo local, com os modelos que já estavam." : " Continuas nos provedores online.");
  } else {
    rigDraft = !!local; box.dataset.failed = "1";
    renderRig();
    $("#rig-status").textContent = "⚠️ " + result.error;
  }
  const again = box.dataset.again;
  delete box.dataset.again;
  if (again) return saveRig(again === "local");
}

async function onProviderAction(ev) {
  const b = ev.currentTarget;
  const { act, p: pid, m: mid } = b.dataset;
  if (act === "del-provider") {
    if (!confirm("Remover este provedor e os seus modelos?")) return;
    applyState(await call("remove_provider", pid));
  } else if (act === "edit-provider") {
    openEditProvider(pid);
  } else if (act === "add-model") {
    openAddModel(pid);
  } else if (act === "del-model") {
    if (!confirm("Remover este modelo?")) return;
    applyState(await call("remove_model", pid, mid));
  }
}

async function discoverModels(pid){
  let provider=state.providers.find(p=>p.id===pid);
  if (!provider?.catalog?.length) {
    const result=await call('sync_provider_models',pid,true);if(!result.ok)return showError(result.error);
    applyState(result);provider=state.providers.find(p=>p.id===pid);
  }
  showModal({title:'Catálogo · '+(provider?.name||pid),bodyHTML:`
    <p class="hint">Modelos carregados automaticamente. Código é uma etiqueta inferida; outros modelos de chat também podem programar. Algumas categorias são apenas para consulta, por ainda não terem adaptador na app.</p>
    <div class="field-row"><input id="catalog-search" placeholder="Pesquisar nome ou ID" aria-label="Pesquisar modelos" /><select id="catalog-category" aria-label="Categoria"><option value="">Todas as categorias</option>${Object.entries(catalogLabels).map(([id,label])=>`<option value="${id}">${label} (${(provider.catalog||[]).filter(m=>m.categories.includes(id)).length})</option>`).join('')}</select></div>
    <p id="catalog-count" class="hint"></p><div id="catalog-results" class="catalog-results"></div>`,okLabel:'Atualizar catálogo',onOk:async()=>{
      const result=await call('sync_provider_models',pid,true);if(!result.ok){showError(result.error);return false;}
      applyState(result);hideModal();await discoverModels(pid);return false;
    }});
  const render=()=>{
    const q=$('#catalog-search').value.trim().toLowerCase(),category=$('#catalog-category').value;
    const rows=(provider.catalog||[]).filter(m=>(!category||m.categories.includes(category))&&(!q||(m.name+' '+m.id).toLowerCase().includes(q)));
    $('#catalog-count').textContent=rows.length+' de '+(provider.catalog||[]).length+' modelos · '+(provider.catalog_updated_at?new Date(provider.catalog_updated_at*1000).toLocaleString('pt-PT'):'');
    $('#catalog-results').innerHTML=rows.map(m=>`<div class="catalog-row"><strong>${esc(m.name)}</strong><div class="model-id">${esc(m.id)}</div><div>${m.categories.map(c=>`<span class="badge">${esc(catalogLabels[c]||c)}</span>`).join(' ')}</div><p class="hint">${esc(m.description||'')}</p><small>${m.types.length?'Disponível no seletor: '+m.types.map(t=>catalogLabels[t]).join(', '):'Só catálogo — sem adaptador nesta app'}</small></div>`).join('')||'<p class="empty">Nenhum modelo nesta categoria.</p>';
  };
  $('#catalog-search').oninput=render;$('#catalog-category').onchange=render;render();
}

/* ---------------- Seletores: um por coisa (conversa, código, imagem, vídeo, áudio) ---------------- */
// Pedidos do user (24/11/2026): «quero ser eu a escolher os modelos para cada coisa» — nada é escolhido pela app; e «quero
// distinguir chat com código». Cada campo mostra os modelos da sua categoria no catálogo do provedor.
const MODEL_SLOTS = ["chat", "code", "image", "video", "audio"];
function slotModels(provider, slot, current) {
  const type = slot === "code" ? "chat" : slot;
  return (provider?.models || []).filter(model => (model.type || "image") === type && model.catalog_available !== false
    // «Código»: só os modelos de conversa que o catálogo marca como bons a programar (o que está escolhido nunca sai da lista)
    && (slot !== "code" || model.categories?.includes("code") || (current && provider.id === current.provider_id && model.id === current.model_id)));
}
function fillModelPicker() {
  const local = !!(state.rig && state.rig.enabled);
  for (const slot of MODEL_SLOTS) {
    const select = el.slots?.[slot];
    if (!select) continue;
    const current = state.selections[slot] || {};
    const first = new Option("(escolhe um modelo)", "");
    select.replaceChildren(first);
    for (const provider of state.providers) {
      const models = slotModels(provider, slot, current);
      if (!models.length) continue;
      const group = document.createElement("optgroup");
      group.label = (provider.name || provider.id) + (provider.has_key === false ? " — sem chave" : "");
      for (const model of models) {
        const context = slot === "chat" || slot === "code" ? Number(model.defaults?.context_window) || 0 : 0;
        group.append(new Option((model.name || model.id) + (context ? " · " + formatTokens(context) : ""), `${provider.id}::${model.id}`));
      }
      select.append(group);
    }
    const value = current.provider_id && current.model_id ? `${current.provider_id}::${current.model_id}` : "";
    select.value = [...select.options].some(option => option.value === value) ? value : "";
    if (select.options.length <= 1) first.textContent = "(sem modelos)";
    select.disabled = modelPickerBusy || select.options.length <= 1;
    select.classList.toggle("unset", !select.value);
    // «Provedor local»: só se usam os modelos da rig; um campo sem modelos dela nem aparece, para não induzir em erro
    select.closest(".model-slot")?.classList.toggle("hidden", local && select.options.length <= 1);
    const chosen = select.selectedOptions[0];
    select.title = select.value ? `${chosen.parentElement.label} · ${chosen.textContent}` : select.getAttribute("aria-label") + ": por escolher";
  }
  const audio = state.selections.audio || {};
  const owner = state.providers.find(provider => provider.id === audio.provider_id);
  fillVoicePicker(slotModels(owner, "audio").find(model => model.id === audio.model_id) || null, audio.provider_id);
}

// Voz do modelo de áudio escolhido: cada modelo tem as suas (vêm do catálogo); sem lista, o seletor não aparece.
function fillVoicePicker(model, pid) {
  const select = $("#sel-voice");
  if (!select) return;
  const voices = model?.voices || [];
  select.classList.toggle("hidden", !voices.length);
  if (!voices.length) return;
  const chosen = model.defaults?.voice || "";
  select.replaceChildren(new Option(`🗣 Voz: ${voices[0]} (a primeira do modelo)`, ""));
  for (const voice of voices) select.add(new Option("🗣 Voz: " + voice, voice));
  if (chosen && !voices.some(voice => voice.toLowerCase() === chosen.toLowerCase())) select.add(new Option(`🗣 Voz: ${chosen} (escrita à mão)`, chosen));
  select.value = voices.find(voice => voice.toLowerCase() === chosen.toLowerCase()) || chosen;
  select.dataset.target = `${pid}::${model.id}`;
  select.disabled = modelPickerBusy;
}

async function onVoiceChange() {
  const select = $("#sel-voice");
  const [pid, mid] = (select.dataset.target || "").split("::");
  if (!pid || !mid) return;
  const res = await call("set_model_voice", pid, mid, select.value);
  if (!res.ok) { showError(res.error); fillModelPicker(); return; }
  applyState(res);
}

async function onSlotChange(slot) {
  const value = el.slots[slot].value, cut = value.indexOf("::");
  await persistModelSelection(slot, cut > 0 ? value.slice(0, cut) : "", cut > 0 ? value.slice(cut + 2) : "");
}

async function persistModelSelection(type, pid, mid) {
  if (modelPickerBusy) return;
  modelPickerBusy = true;
  for (const slot of MODEL_SLOTS) if (el.slots?.[slot]) el.slots[slot].disabled = true;
  try {
    const result = await call("set_model", type, pid, mid);
    if (!result.ok) { showError(result.error); return; }
    applyState(result);
  } finally {
    modelPickerBusy = false;
    fillModelPicker();
  }
}

/* ---------------- Modais de provedor / modelo ---------------- */
function kindOptions(selected) {
  const kinds = state.kinds.length ? state.kinds : ["openrouter"];
  return kinds.map((k) => `<option value="${esc(k)}" ${k === selected ? "selected" : ""}>${esc(state.kindDetails[k]?.label || k)}</option>`).join("");
}

function openAddProvider() {
  showModal({
    title: "Adicionar provedor",
    bodyHTML: `
      <label class="field"><span>Nome</span><input id="f-name" placeholder="OpenRouter" /></label>
      <label class="field"><span>Tipo (kind)</span><select id="f-kind">${kindOptions("openrouter")}</select></label>
      <label class="field"><span>Base URL</span><input id="f-base" value="https://openrouter.ai/api/v1" /></label>
      <label class="field"><span>Chave de API</span><input id="f-key" type="password" placeholder="sk-or-v1-…" /></label><p id="f-provider-note" class="hint"></p>`,
    onOk: async () => {
      const res = await call("add_provider", { name: $("#f-name").value, kind: $("#f-kind").value, base_url: $("#f-base").value, api_key: $("#f-key").value });
      if (!res.ok) { showError(res.error); return false; }
      applyState(res); return true;
    },
  });
  bindProviderDefaults('openrouter');
}

function bindProviderDefaults(initial){
  const select=$('#f-kind');let previous=initial;
  const update=()=>{const preset=state.kindDetails[select.value]||{};const old=state.kindDetails[previous]||{};
    if(!$('#f-base').value||$('#f-base').value===old.base_url)$('#f-base').value=preset.base_url||'';
    $('#f-key').placeholder=preset.requires_key===false?'Opcional (conforme autenticação do servidor)':'Chave da API deste provedor';
    if($('#f-provider-note'))$('#f-provider-note').textContent=preset.requires_key===false?'Servidor local/compatível: a chave pode ficar vazia. O servidor e o modelo têm de estar disponíveis.':'Usa uma chave da API deste provedor. A subscrição de uma aplicação de chat não configura esta API.';previous=select.value;};
  select.onchange=update;update();
}

function openEditProvider(pid) {
  const p = state.providers.find((x) => x.id === pid);
  if (!p) return;
  showModal({
    title: "Editar provedor",
    bodyHTML: `
      <label class="field"><span>Nome</span><input id="f-name" value="${esc(p.name)}" /></label>
      <label class="field"><span>Tipo (kind)</span><select id="f-kind">${kindOptions(p.kind)}</select></label>
      <label class="field"><span>Base URL</span><input id="f-base" value="${esc(p.base_url)}" /></label>
      <label class="field"><span>Chave de API</span><input id="f-key" type="password" placeholder="${p.has_key ? "(manter a atual)" : "sk-or-v1-…"}" /></label>
      <p class="hint">Deixa a chave em branco para manter a atual.</p><p id="f-provider-note" class="hint"></p>`,
    onOk: async () => {
      const res = await call("update_provider", pid, { name: $("#f-name").value, kind: $("#f-kind").value, base_url: $("#f-base").value, api_key: $("#f-key").value });
      if (!res.ok) { showError(res.error); return false; }
      applyState(res); return true;
    },
  });
  bindProviderDefaults(p.kind);
}

function openAddModel(pid) {
  showModal({
    title: "Adicionar modelo",
    bodyHTML: `
      <label class="field"><span>Tipo</span>
        <select id="m-type">
          <option value="chat">💬 Chat / código (texto · multimodal)</option>
          <option value="image" selected>🖼️ Imagem</option>
          <option value="video">🎬 Vídeo</option>
          <option value="audio">🔊 Áudio (voz / TTS)</option>
        </select>
      </label>
      <label class="field"><span>ID do modelo</span><input id="m-id" placeholder="ex.: black-forest-labs/flux-3-image" /></label>
      <p class="hint">Replicate: dono/modelo (ou dono/modelo:versão). fal.ai: o caminho do modelo, como fal-ai/flux/schnell. Kie.ai: o nome que a página do modelo indica.</p>
      <label class="field"><span>Nome (opcional)</span><input id="m-name" placeholder="nome amigável" /></label>
      <details class="opt"><summary>Parâmetros por omissão (opcional)</summary>
        <div class="field-row">
          <label class="field"><span>Voz (áudio)</span><input id="m-voice" placeholder="vazio = a primeira voz do modelo" /></label>
          <label class="field"><span>Resolução (vídeo)</span><input id="m-res" placeholder="720p" /></label>
        </div>
        <div class="field-row">
          <label class="field"><span>Proporção (vídeo)</span><input id="m-aspect" placeholder="16:9" /></label>
          <label class="field narrow"><span>Duração s (vídeo)</span><input id="m-dur" type="number" min="1" placeholder="4" /></label>
        </div>
        <label class="field"><span>Janela de contexto em tokens (0 = sem limite na app)</span><input id="m-ctx" type="number" min="0" placeholder="128000" /></label>
        <label class="field"><span>Parâmetros próprios do modelo, em JSON (Replicate, fal.ai, Kie.ai)</span><input id="m-input" placeholder='{"num_outputs": 1}' /></label>
      </details>`,
    onOk: async () => {
      const defaults = {};
      const voice = $("#m-voice").value.trim();
      const res_ = $("#m-res").value.trim();
      const aspect = $("#m-aspect").value.trim();
      const dur = parseInt($("#m-dur").value, 10);
      const ctx = parseInt($("#m-ctx").value, 10);
      if (voice) defaults.voice = voice;
      if (res_) defaults.resolution = res_;
      if (aspect) defaults.aspect_ratio = aspect;
      if (dur > 0) defaults.duration = dur;
      if (ctx >= 0) defaults.context_window = ctx;
      const extra = $("#m-input").value.trim();
      if (extra) {
        let parsed = null;
        try { parsed = JSON.parse(extra); } catch (e) { parsed = null; }
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) { showError('Os parâmetros próprios do modelo têm de ser um objeto JSON, por exemplo {"num_outputs": 1}.'); return false; }
        defaults.input = parsed;
      }
      const out = await call("add_model", pid, { id: $("#m-id").value, name: $("#m-name").value, type: $("#m-type").value, defaults });
      if (!out.ok) { showError(out.error); return false; }
      applyState(out); return true;
    },
  });
  const provider=state.providers.find(p=>p.id===pid),caps=state.kindCaps[provider?.kind];
  if(caps){for(const option of $('#m-type').options)option.disabled=!caps[option.value];if(!caps[$('#m-type').value])$('#m-type').value=Object.keys(TYPE_LABEL).find(k=>caps[k])||'chat';}
}
