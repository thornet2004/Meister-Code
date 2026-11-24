"use strict";
// Pesquisa de código por significado (embeddings): secção do painel "Contexto / Código".
// Bloco fechado: não acrescenta nomes ao âmbito global.
(() => {
  const body = document.querySelector('#project-context-modal .modal-body');
  const launch = document.querySelector('#btn-project-context');
  if (!body || !launch) return;
  const el = (tag, text = '', cls = '') => { const node = document.createElement(tag); node.textContent = text; node.className = cls; return node; };
  const api = async (name, ...args) => { const r = await call(name, ...args); if (!r.ok) throw Error(r.error); return r; };

  const section = el('details'); section.id = 'semantic-search';
  section.append(el('summary', 'Pesquisa por significado (embeddings)'));
  const intro = el('p', 'Encontra código pelo sentido da pergunta, mesmo sem palavras iguais. Para isso, os excertos do código deste projeto são enviados ao provedor de embeddings que escolheres. Vem desligada.', 'hint');
  const enabled = el('input'); enabled.type = 'checkbox'; enabled.id = 'sem-enabled';
  const enabledLabel = el('label', '', 'check'); enabledLabel.append(enabled, el('span', 'Ligar a pesquisa por significado neste computador'));
  const provider = el('select'); provider.id = 'sem-provider'; provider.setAttribute('aria-label', 'Provedor de embeddings');
  const model = el('input'); model.id = 'sem-model'; model.placeholder = 'Modelo de embeddings (ex.: nomic-embed-text, text-embedding-3-small)'; model.setAttribute('aria-label', 'Modelo de embeddings'); model.setAttribute('list', 'sem-models');
  const models = el('datalist'); models.id = 'sem-models';
  const where = el('p', '', 'hint'); where.id = 'sem-where';
  const status = el('p', '', 'hint'); status.id = 'sem-status';
  const actions = el('div', '', 'sem-actions');
  const query = el('input'); query.id = 'sem-query'; query.placeholder = 'Descreve o que procuras (ex.: onde se valida a sessão do utilizador)'; query.setAttribute('aria-label', 'Pesquisar por significado');
  const results = el('div'); results.id = 'sem-results';
  section.append(intro, enabledLabel, provider, model, models, where, actions, status, query, results);
  body.insertBefore(section, body.querySelector('details'));

  let known = null;      // última resposta de get_semantic_search
  let polling = false;

  function button(label, id, action) {
    const b = el('button', label, 'btn ghost small'); b.type = 'button'; b.id = id;
    b.onclick = async () => { b.disabled = true; try { await action(); } catch (e) { status.textContent = e.message; } finally { b.disabled = false; } };
    actions.append(b); return b;
  }

  function describe(r) {
    known = r;
    const running = r.job && r.job.state === 'running';
    enabled.checked = !!r.settings.enabled;
    const current = r.settings.provider_id;
    provider.replaceChildren(new Option(r.providers.length ? 'Escolhe o provedor…' : 'Sem provedores compatíveis (OpenRouter, OpenAI, Ollama, LM Studio)', ''));
    for (const p of r.providers) provider.add(new Option(p.name + (p.local ? ' · local' : ' · nuvem'), p.id));
    provider.value = r.providers.some((p) => p.id === current) ? current : '';
    if (document.activeElement !== model) model.value = r.settings.model_id;
    const chosen = r.providers.find((p) => p.id === provider.value);
    models.replaceChildren(...(chosen ? chosen.models : []).map((id) => new Option(id, id)));
    where.textContent = !chosen ? '' : chosen.local
      ? 'Provedor local: o código não sai deste computador.'
      : 'Provedor na nuvem: os excertos do código são enviados para ' + chosen.name + ' e a indexação gasta créditos.';
    const index = r.index || {};
    const indexed = index.state === 'ready'
      ? index.chunks + ' excertos de ' + index.files + ' ficheiros indexados' + (index.pending ? ' · ' + index.pending + ' por indexar' : '')
      : 'Ainda sem índice de significado para ' + r.workspace + '.';
    status.textContent = running ? 'A indexar… ' + r.job.message
      : (r.job && r.job.state === 'error' ? 'A indexação falhou: ' + r.job.message + ' · ' : '') + indexed;
    for (const node of [provider, model]) node.disabled = !enabled.checked;
    document.querySelector('#sem-index').disabled = !enabled.checked || running;
    document.querySelector('#sem-cancel').classList.toggle('hidden', !running);
    document.querySelector('#sem-search').disabled = !enabled.checked || index.state !== 'ready';
    query.disabled = !enabled.checked || index.state !== 'ready';
    if (running) poll();
  }

  async function load() { describe(await api('get_semantic_search')); }
  async function save() { describe(await api('set_semantic_search', { enabled: enabled.checked, provider_id: provider.value, model_id: model.value.trim() })); }

  async function poll() {
    if (polling) return;
    polling = true;
    try {
      while (true) {
        await new Promise((resolve) => setTimeout(resolve, 400));
        const r = await api('get_semantic_search');
        const running = r.job && r.job.state === 'running';
        if (!running) { polling = false; describe(r); return; }
        status.textContent = 'A indexar… ' + r.job.message;
      }
    } catch (e) { status.textContent = e.message; } finally { polling = false; }
  }

  async function search() {
    const r = await api('search_semantic', query.value, 8);
    results.replaceChildren();
    if (!r.results.length) results.append(el('p', 'Nada encontrado.', 'hint'));
    for (const row of r.results) {
      const card = el('article', '', 'mcp-card');
      card.append(el('strong', row.path + ':' + row.line + '–' + row.end_line + ' · proximidade ' + Math.round(row.score * 100) + '%'));
      card.append(el('pre', row.stale ? row.message : row.excerpt, 'step-body'));
      results.append(card);
    }
  }

  button('Indexar / atualizar', 'sem-index', async () => { await save(); await api('start_semantic_index'); await load(); });
  button('Cancelar indexação', 'sem-cancel', async () => { await api('cancel_semantic_index'); }).classList.add('hidden');
  button('Apagar índice', 'sem-clear', async () => { describe(await api('clear_semantic_index')); results.replaceChildren(); });
  button('Pesquisar por significado', 'sem-search', search);
  const guarded = (fn) => () => fn().catch((e) => { status.textContent = e.message; });
  enabled.onchange = guarded(save);
  provider.onchange = guarded(save);
  model.onchange = guarded(save);
  query.onkeydown = (e) => { if (e.key === 'Enter') guarded(search)(); };
  launch.addEventListener('click', guarded(load));
  section.addEventListener('toggle', () => { if (section.open) guarded(load)(); });
})();
