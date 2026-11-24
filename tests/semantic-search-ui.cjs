// Interface da pesquisa por significado (secção do painel Contexto / Código), com a ponte simulada.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict'), path = require('node:path'), {pathToFileURL} = require('node:url');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1200, height: 900}}), errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.addInitScript(() => {
      const sem = window.sem = {settings: {enabled: false, provider_id: '', model_id: ''}, index: {state: 'not_indexed', chunks: 0, files: 0}, job: null, calls: [], polls: 0};
      const view = () => ({ok: true, settings: {...sem.settings}, workspace: 'C:/projeto', index: {...sem.index}, job: sem.job && {...sem.job},
        providers: [{id: 'local', name: 'Ollama', kind: 'ollama', local: true, models: ['nomic-embed-text']}, {id: 'nuvem', name: 'OpenAI', kind: 'openai', local: false, models: []}]});
      window.pywebview = {api: {
        get_state: async () => ({ok: true, providers: [], projects: [], conversations: []}),
        get_conversation: async () => ({ok: true, messages: []}),
        get_project_context: async () => ({ok: true, workspace: 'C:/projeto', index: null, search: {results: [], index: null}, symbols: {results: []}, continuity: {decisions: [], tasks: []}}),
        get_semantic_search: async () => {
          if (sem.job && sem.job.state === 'running' && ++sem.polls >= 2) { sem.job = {state: 'done', message: '12 excertos novos; 0 por indexar.'}; sem.index = {state: 'ready', chunks: 12, files: 3, pending: 0}; }
          return view();
        },
        set_semantic_search: async (data) => { sem.calls.push(['set', data]); Object.assign(sem.settings, data); return view(); },
        start_semantic_index: async () => { sem.calls.push(['index']); sem.polls = 0; sem.job = {state: 'running', done: 4, total: 12, message: '4 de 12 excertos'}; return {ok: true, job: sem.job}; },
        cancel_semantic_index: async () => ({ok: true, job: sem.job}),
        clear_semantic_index: async () => { sem.calls.push(['clear']); sem.index = {state: 'not_indexed', chunks: 0, files: 0}; sem.job = null; return view(); },
        search_semantic: async (query) => { sem.calls.push(['search', query]); return {ok: true, results: [
          {path: 'auth.py', line: 1, end_line: 3, score: 0.91, excerpt: 'def verificar_senha(utilizador, senha):', stale: false},
          {path: 'velho.py', line: 5, end_line: 9, score: 0.4, stale: true, message: 'O ficheiro mudou; atualiza o índice de significado.'}]}; },
      }};
    });
    await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
    await page.click('#btn-project-context');
    await page.click('#semantic-search > summary');
    // desligada por omissão: nada editável, nada para pesquisar
    await page.waitForFunction(() => document.querySelector('#sem-status').textContent.includes('Ainda sem índice'));
    assert.equal(await page.isChecked('#sem-enabled'), false);
    assert.equal(await page.isDisabled('#sem-provider'), true);
    assert.equal(await page.isDisabled('#sem-index'), true);
    assert.equal(await page.isDisabled('#sem-query'), true);
    // ligar e escolher um provedor na nuvem: avisa que o código sai do computador
    await page.check('#sem-enabled');
    await page.waitForFunction(() => !document.querySelector('#sem-provider').disabled);
    await page.selectOption('#sem-provider', 'nuvem');
    await page.waitForFunction(() => document.querySelector('#sem-where').textContent.includes('enviados para OpenAI'));
    // provedor local: diz que fica no computador e sugere os modelos do catálogo
    await page.selectOption('#sem-provider', 'local');
    await page.waitForFunction(() => document.querySelector('#sem-where').textContent.includes('não sai deste computador'));
    assert.deepEqual(await page.$$eval('#sem-models option', (options) => options.map((o) => o.value)), ['nomic-embed-text']);
    await page.fill('#sem-model', 'nomic-embed-text');
    // indexar: guarda as definições, mostra o progresso e acaba com a contagem
    await page.click('#sem-index');
    await page.waitForFunction(() => document.querySelector('#sem-status').textContent.includes('A indexar'));
    await page.waitForFunction(() => document.querySelector('#sem-status').textContent.includes('12 excertos de 3 ficheiros'));
    const calls = await page.evaluate(() => window.sem.calls);
    assert.deepEqual(calls.filter((c) => c[0] === 'set').pop()[1], {enabled: true, provider_id: 'local', model_id: 'nomic-embed-text'});
    assert.ok(calls.some((c) => c[0] === 'index'));
    // pesquisar: mostra ficheiro, linhas, proximidade e marca o que está desatualizado
    assert.equal(await page.isDisabled('#sem-query'), false);
    await page.fill('#sem-query', 'onde é feito o login');
    await page.press('#sem-query', 'Enter');
    await page.waitForFunction(() => document.querySelectorAll('#sem-results article').length === 2);
    const text = await page.textContent('#sem-results');
    assert.match(text, /auth\.py:1–3 · proximidade 91%/);
    assert.match(text, /verificar_senha/);
    assert.match(text, /O ficheiro mudou/);
    assert.deepEqual((await page.evaluate(() => window.sem.calls)).filter((c) => c[0] === 'search').pop(), ['search', 'onde é feito o login']);
    // apagar o índice volta ao estado inicial
    await page.click('#sem-clear');
    await page.waitForFunction(() => document.querySelector('#sem-status').textContent.includes('Ainda sem índice'));
    assert.equal(await page.isDisabled('#sem-query'), true);
    assert.deepEqual(errors, []);
    console.log('PASS: semantic search off by default, cloud/local notice, model suggestions, index progress, search results, stale marker, clear, no JS errors');
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exit(1); });
