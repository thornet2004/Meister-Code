"use strict";
// Painel «Atualizar ferramentas»: instala as ferramentas do tools_manifest.json, uma a uma, pela ponte.
// Tudo dentro de uma função: não acrescenta nomes globais.
(() => {
  const modal = document.querySelector('#tool-updates-modal');
  if (!modal) return;
  const $id = (id) => document.querySelector('#' + id);
  const list = $id('tool-updates-list');
  const selected = new Set();
  let data = { tools: [], groups: {}, job: { state: 'idle', results: [] }, root: '', free_bytes: 0 };
  let timer = null;
  const LABELS = { installed: 'Instalada', missing: 'Por instalar', partial: 'Incompleta', pending: 'Não automática' };
  const RESULT = { installed: 'instalada agora', already: 'já estava instalada', failed: 'falhou', cancelled: 'cancelada', pending: 'não automática' };

  const node = (tag, text, className) => { const n = document.createElement(tag); if (text) n.textContent = text; if (className) n.className = className; return n; };
  const megabytes = (bytes) => bytes >= 1048576 ? Math.round(bytes / 1048576) + ' MB' : bytes > 0 ? '< 1 MB' : 'tamanho não indicado';
  const running = () => data.job.state === 'running';
  const selectable = (tool) => tool.automatic && tool.status !== 'installed';

  async function checked(method, ...args) {
    const result = await call(method, ...args);
    if (!result.ok) throw new Error(result.error);
    return result;
  }

  function render() {
    const tools = data.tools || [];
    const results = Object.fromEntries((data.job.results || []).map((row) => [row.key, row]));
    for (const key of [...selected]) if (!tools.some((tool) => tool.key === key && selectable(tool))) selected.delete(key);
    list.replaceChildren();
    for (const [letter, title] of Object.entries(data.groups || {})) {
      const rows = tools.filter((tool) => tool.group === letter);
      if (!rows.length) continue;
      list.append(node('h4', title));
      for (const tool of rows) {
        const card = node('article', '', 'mcp-card tool-update ' + tool.status);
        card.dataset.toolKey = tool.key;
        const head = node('label', '', 'tools-card-head');
        const box = document.createElement('input');
        box.type = 'checkbox';
        box.checked = selected.has(tool.key);
        box.disabled = running() || !selectable(tool);
        box.onchange = () => { if (box.checked) selected.add(tool.key); else selected.delete(tool.key); summary(); };
        const title = node('span', '', 'tool-update-title');
        title.append(box, node('strong', tool.name + (tool.version ? ' · ' + tool.version : '')));
        head.append(title, node('span', LABELS[tool.status] || tool.status, 'badge ' + (tool.status === 'installed' ? 'tools-ready' : 'tools-pending')));
        card.append(head);
        if (tool.description) card.append(node('p', tool.description, 'tool-update-description'));
        if (tool.status !== 'installed' && tool.automatic) card.append(node('p', 'Download: ' + megabytes(tool.download_bytes) + (tool.installed_mb ? ' · instalada ocupa cerca de ' + tool.installed_mb + ' MB' : ''), 'hint'));
        if (!tool.automatic && tool.pending) card.append(node('p', 'Ainda não se instala sozinha: ' + tool.pending + '.', 'hint'));
        if (tool.requires && tool.requires.length) card.append(node('p', 'Depende de: ' + tool.requires.join(', '), 'hint'));
        if (tool.integrated === false) card.append(node('p', 'Só é descarregada: a app ainda não a usa.', 'hint'));
        if (tool.license) card.append(node('p', 'Licença: ' + tool.license, 'hint'));
        if (tool.note) card.append(node('p', tool.note, 'hint'));
        const result = results[tool.key];
        if (result) card.append(node('p', (RESULT[result.status] || result.status) + ' — ' + result.message, 'notice ' + (result.status === 'failed' ? 'warn' : 'tool-update-result')));
        if (data.job.current === tool.key) card.classList.add('current');
        list.append(card);
      }
    }
    summary();
  }

  function summary() {
    const tools = data.tools || [];
    const count = (status) => tools.filter((tool) => tool.status === status).length;
    const chosen = tools.filter((tool) => selected.has(tool.key));
    const bytes = chosen.reduce((total, tool) => total + (tool.download_bytes || 0), 0);
    $id('tool-updates-summary').textContent = `${count('installed')} instaladas · ${count('missing') + count('partial')} por instalar · ${count('pending')} não automáticas · ` +
      `pasta: ${data.root} · espaço livre: ${megabytes(data.free_bytes)}` + (chosen.length ? ` · selecionadas: ${chosen.length} (${megabytes(bytes)})` : '');
    const busy = running();
    $id('tool-updates-start').disabled = busy || !chosen.length;
    $id('tool-updates-select').disabled = busy;
    $id('tool-updates-cancel').classList.toggle('hidden', !busy);
    const progress = $id('tool-updates-progress');
    const job = data.job;
    progress.classList.toggle('hidden', job.state === 'idle');
    $id('tool-updates-message').textContent = job.message || '';
    $id('tool-updates-bar').style.width = (job.total_bytes ? Math.min(100, (job.done_bytes / job.total_bytes) * 100) : busy ? 5 : 100) + '%';
    progress.classList.toggle('failed', job.state === 'failed');
  }

  async function refresh() {
    data = await checked('get_tool_updates');
    render();
    if (running()) watch();
  }

  function watch() {
    if (timer) return;
    timer = setInterval(async () => {
      try {
        const was = running();
        data = await checked('get_tool_updates');
        render();
        if (!running()) {
          clearInterval(timer);
          timer = null;
          if (was) setStatusMessage('Ferramentas: ' + (data.job.message || 'concluído.'));
        }
      } catch (error) {
        clearInterval(timer);
        timer = null;
        showError(error.message);
      }
    }, 700);
  }

  async function start() {
    const chosen = (data.tools || []).filter((tool) => selected.has(tool.key));
    if (!chosen.length) return;
    // o instalador acrescenta sozinho aquilo de que as escolhidas dependem (núcleo incluído): o total mostrado tem de o contar
    const byKey = Object.fromEntries((data.tools || []).map((tool) => [tool.key, tool]));
    const plan = [];
    const visit = (key) => {
      if (!byKey[key] || plan.includes(key)) return;
      (byKey[key].requires || []).forEach(visit);
      plan.push(key);
    };
    chosen.forEach((tool) => visit(tool.key));
    const todo = plan.map((key) => byKey[key]).filter((tool) => tool.status !== 'installed');
    const extra = todo.filter((tool) => !selected.has(tool.key));
    const bytes = todo.reduce((total, tool) => total + (tool.download_bytes || 0), 0);
    const question = `Descarregar e instalar ${todo.length} ferramenta(s) (${megabytes(bytes)}) em\n${data.root}?\n\n` +
      (extra.length ? 'Inclui o que as escolhidas precisam: ' + extra.map((tool) => tool.name).join(', ') + '.\n\n' : '') +
      (todo.some((tool) => (tool.runs || []).includes('setup-exe')) ? 'Atenção: uma delas executa o instalador oficial do programa (modo silencioso, só para a tua conta).\n\n' : '') +
      'Os ficheiros vêm dos endereços fixos do manifesto e só são usados se o SHA-256 bater certo.';
    if (!window.confirm(question)) return;
    const result = await checked('start_tool_updates', chosen.map((tool) => tool.key));
    data.job = result.job;
    selected.clear();
    render();
    watch();
  }

  const guard = (fn) => () => fn().catch((error) => showError(error.message));
  // a janela «Ferramentas» fecha-se: duas janelas sobrepostas tapavam os cliques desta
  $id('tools-update').onclick = guard(async () => { $id('tools-modal').classList.add('hidden'); modal.classList.remove('hidden'); await refresh(); });
  $id('tool-updates-close').onclick = () => modal.classList.add('hidden');
  modal.addEventListener('click', (event) => { if (event.target === modal) modal.classList.add('hidden'); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !modal.classList.contains('hidden')) modal.classList.add('hidden'); });
  $id('tool-updates-select').onclick = () => { for (const tool of data.tools || []) if (selectable(tool)) selected.add(tool.key); render(); };
  $id('tool-updates-start').onclick = guard(start);
  $id('tool-updates-cancel').onclick = guard(async () => { data.job = (await checked('cancel_tool_updates')).job; summary(); });
})();
