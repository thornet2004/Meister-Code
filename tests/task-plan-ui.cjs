// Lista de tarefas do agente por cima da caixa de mensagem: aparece, atualiza em direto, e o utilizador pode mexer nela.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict'), path = require('node:path'), {pathToFileURL} = require('node:url');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1300, height: 900}}), errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.addInitScript(() => {
      window.taskStore = [];
      window.taskCalls = [];
      window.taskFail = false;
      const base = {ok: true, used: 1200, limit: 128000, percent: 0.9, parts: {}, total_messages: 0, older: 0, history_window: 40};
      window.pywebview = {api: {
        get_state: async () => ({ok: true, providers: [], projects: [], conversations: []}),
        get_conversation: async () => ({ok: true, messages: []}),
        get_context_usage: async () => (window.taskStore === null ? base : {...base, tasks: window.taskStore}),
        update_context_record: async (kind, text, id, state) => {
          window.taskCalls.push([kind, text, id, state]);
          if (window.taskFail) return {ok: false, error: 'Seleciona Implementar para atualizar os registos persistentes.'};
          if (kind === 'remove') window.taskStore = window.taskStore.filter((t) => t.id !== id);
          else window.taskStore = window.taskStore.map((t) => t.id === id ? {...t, state} : t);
          return {ok: true, continuity: {decisions: [], tasks: window.taskStore}};
        },
      }};
    });
    await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
    await page.waitForFunction(() => typeof window.showAgentTasks === 'function' && document.querySelector('#context-label').textContent !== '—');
    const box = page.locator('#task-plan');
    assert.equal(await box.isVisible(), false, 'sem tarefas: o painel não aparece');

    // o Python chama window.showAgentTasks a meio da resposta
    const tasks = [
      {id: 'a', text: 'Ler o código', state: 'done'},
      {id: 'b', text: '<img src=x onerror="window.pwned=1"> Escrever testes', state: 'doing'},
      {id: 'c', text: 'Correr a suite', state: 'open'},
    ];
    await page.evaluate((rows) => { window.taskStore = rows; window.showAgentTasks(rows); }, tasks);
    assert.equal(await box.isVisible(), true);
    assert.equal(await box.evaluate((n) => n.open), true, 'abre sozinho quando há trabalho por fazer');
    assert.match(await page.textContent('#task-plan-summary'), /Tarefas 1\/3 · em curso: <img/);
    const rows = await page.$$eval('#task-plan-list li', (nodes) => nodes.map((n) => [n.className, n.querySelector('.task-mark').textContent, n.querySelector('.task-text').textContent]));
    assert.deepEqual(rows.map((r) => r.slice(0, 2)), [['done', '☑'], ['doing', '▶'], ['open', '☐']]);
    assert.equal(rows[2][2], 'Correr a suite');
    assert.equal(await page.evaluate(() => window.pwned), undefined, 'o texto da tarefa é tratado como texto');
    assert.equal(await page.locator('#task-plan-list img').count(), 0);

    // o utilizador fecha o painel: uma atualização não o volta a abrir
    await page.evaluate(() => { document.querySelector('#task-plan').open = false; });
    await page.evaluate((rows) => window.showAgentTasks(rows), tasks);
    assert.equal(await box.evaluate((n) => n.open), false);
    await page.evaluate(() => { document.querySelector('#task-plan').open = true; });

    // clicar numa tarefa marca-a como concluída; clicar numa concluída reabre-a
    await page.click('#task-plan-list li:nth-child(3)');
    await page.waitForFunction(() => document.querySelector('#task-plan-list li:nth-child(3)').className === 'done');
    await page.click('#task-plan-list li:nth-child(1)');
    await page.waitForFunction(() => document.querySelector('#task-plan-list li:nth-child(1)').className === 'open');
    assert.deepEqual(await page.evaluate(() => window.taskCalls), [['task', 'Correr a suite', 'c', 'done'], ['task', 'Ler o código', 'a', 'open']]);
    assert.match(await page.textContent('#task-plan-summary'), /Tarefas 1\/3/);

    // limpar concluídas remove só essas
    assert.equal(await page.locator('#task-plan-clear').isVisible(), true);
    await page.click('#task-plan-clear');
    await page.waitForFunction(() => document.querySelectorAll('#task-plan-list li').length === 2);
    assert.deepEqual(await page.evaluate(() => window.taskStore.map((t) => t.id)), ['a', 'b']);
    assert.equal(await page.locator('#task-plan-clear').isVisible(), false);

    // recusa da ponte (modo de leitura): mostra o erro e não altera a lista
    await page.evaluate(() => { window.taskFail = true; });
    await page.click('#task-plan-list li:nth-child(1)');
    await page.waitForFunction(() => !document.querySelector('#error-box').classList.contains('hidden'));
    assert.match(await page.textContent('#error-box'), /Seleciona Implementar/);
    assert.equal(await page.locator('#task-plan-list li').count(), 2);
    await page.evaluate(() => { window.taskFail = false; });

    // tudo concluído, lista vazia, e ponte antiga sem o campo
    await page.evaluate(() => window.showAgentTasks([{id: 'a', text: 'Única', state: 'done'}]));
    assert.match(await page.textContent('#task-plan-summary'), /Tarefas 1\/1 · tudo concluído/);
    await page.evaluate(() => { window.taskStore = []; return refreshContextUsage(); });
    assert.equal(await box.isVisible(), false, 'lista vazia: o painel some');
    await page.evaluate((rows) => window.showAgentTasks(rows), tasks);
    await page.evaluate(() => { window.taskStore = null; return refreshContextUsage(); });
    assert.equal(await box.isVisible(), true, 'resposta sem o campo "tasks": não mexe no que está no ecrã');
    assert.deepEqual(errors, []);
    console.log('PASS: hidden when empty, live update, states and marks, text not HTML, respects user collapse, toggle done/reopen, clear done, bridge refusal shown, all-done summary, no JS errors');
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exit(1); });
