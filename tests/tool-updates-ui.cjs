// Painel «Atualizar ferramentas»: lista do manifesto, seleção, confirmação, progresso, cancelar e resultados.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict'), path = require('node:path'), {pathToFileURL} = require('node:url');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1300, height: 950}}), errors = [], dialogs = [];
    page.on('pageerror', (e) => errors.push(e.message));
    let accept = false;
    page.on('dialog', async (dialog) => { dialogs.push(dialog.message()); if (accept) await dialog.accept(); else await dialog.dismiss(); });
    await page.addInitScript(() => {
      const tool = (key, group, status, extra = {}) => ({key, name: 'Nome ' + key, group, version: '1.0', repo: 'https://github.com/x/' + key, automatic: status !== 'pending',
        pending: status === 'pending' ? 'precisa do 7-Zip do núcleo' : '', status, requires: [], download_bytes: 3 * 1048576, installed_mb: 10, note: '', integrated: true, license: '', ...extra});
      window.updates = {
        calls: [],
        tools: [tool('Pronta', 'A', 'installed'), tool('Falta', 'A', 'missing', {requires: ['Pronta']}), tool('Meia', 'A', 'partial'),
          tool('Manual', 'B', 'pending'), tool('Nova', 'E', 'missing', {integrated: false, license: 'MIT', requires: ['Meia'], runs: ['setup-exe'], note: '<img src=x onerror="window.pwned=1"> nota', description: 'Faz <b>placas</b>. Serve para ensaiar.'})],
        job: {state: 'idle', current: '', message: '', done_bytes: 0, total_bytes: 0, results: []},
      };
      window.pywebview = {api: {
        get_state: async () => ({ok: true, providers: [], projects: [], conversations: []}),
        get_conversation: async () => ({ok: true, messages: []}),
        get_tools_inventory: async () => ({ok: true, bench: [], folder_tools: [], mcp_servers: [], language_servers: [], tools: []}),
        get_tool_updates: async () => ({ok: true, tools: window.updates.tools, groups: {A: 'Arquivos portáteis', B: 'Site oficial', E: 'A pedido'}, job: window.updates.job, root: 'C:/app/Ferramentas', free_bytes: 50 * 1073741824}),
        start_tool_updates: async (keys) => {
          window.updates.calls.push(['start', keys]);
          if (window.updates.refuse) return {ok: false, error: 'Já há uma instalação em curso.'};
          window.updates.job = {state: 'running', current: keys[0], message: 'A descarregar…', done_bytes: 1048576, total_bytes: 4 * 1048576, results: []};
          return {ok: true, job: window.updates.job};
        },
        cancel_tool_updates: async () => { window.updates.calls.push(['cancel']); window.updates.job = {...window.updates.job, message: 'A cancelar…'}; return {ok: true, job: window.updates.job}; },
      }};
    });
    await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
    await page.click('#btn-tools');
    await page.click('#tools-update');
    await page.waitForSelector('#tool-updates-list .tool-update');
    assert.equal(await page.locator('#tool-updates-list .tool-update').count(), 5);
    assert.deepEqual(await page.$$eval('#tool-updates-list h4', (n) => n.map((x) => x.textContent)), ['Arquivos portáteis', 'Site oficial', 'A pedido']);
    assert.match(await page.textContent('#tool-updates-summary'), /1 instaladas · 3 por instalar · 1 não automáticas · pasta: C:\/app\/Ferramentas · espaço livre: 51200 MB/);
    // só se pode escolher o que é automático e ainda não está instalado
    const boxes = await page.$$eval('#tool-updates-list .tool-update', (cards) => cards.map((c) => [c.dataset.toolKey, c.querySelector('input').disabled, c.querySelector('.badge').textContent]));
    assert.deepEqual(boxes, [['Pronta', true, 'Instalada'], ['Falta', false, 'Por instalar'], ['Meia', false, 'Incompleta'], ['Manual', true, 'Não automática'], ['Nova', false, 'Por instalar']]);
    assert.match(await page.textContent('[data-tool-key="Manual"]'), /Ainda não se instala sozinha: precisa do 7-Zip do núcleo\./);
    assert.match(await page.textContent('[data-tool-key="Falta"]'), /Depende de: Pronta/);
    assert.equal(await page.textContent('[data-tool-key="Nova"] .tool-update-description'), 'Faz <b>placas</b>. Serve para ensaiar.', 'a descrição aparece, como texto');
    assert.equal(await page.locator('[data-tool-key="Falta"] .tool-update-description').count(), 0);
    assert.match(await page.textContent('[data-tool-key="Nova"]'), /Só é descarregada: a app ainda não a usa\..*Licença: MIT/s);
    assert.equal(await page.evaluate(() => window.pwned), undefined, 'a nota é tratada como texto');
    assert.equal(await page.isDisabled('#tool-updates-start'), true, 'sem seleção não há botão de instalar');
    // selecionar as que faltam
    await page.click('#tool-updates-select');
    assert.match(await page.textContent('#tool-updates-summary'), /selecionadas: 3 \(9 MB\)/);
    await page.uncheck('[data-tool-key="Meia"] input');
    assert.match(await page.textContent('#tool-updates-summary'), /selecionadas: 2 \(6 MB\)/);
    // recusar a confirmação não instala nada
    await page.click('#tool-updates-start');
    assert.equal(dialogs.length, 1);
    assert.match(dialogs[0], /Descarregar e instalar 3 ferramenta\(s\) \(9 MB\) em\nC:\/app\/Ferramentas\?/, 'o total conta as dependências que o instalador acrescenta');
    assert.match(dialogs[0], /Inclui o que as escolhidas precisam: Nome Meia\./);
    assert.match(dialogs[0], /executa o instalador oficial/);
    assert.match(dialogs[0], /SHA-256/);
    assert.deepEqual(await page.evaluate(() => window.updates.calls), []);
    // aceitar: arranca, mostra progresso, tranca a lista e oferece cancelar
    accept = true;
    await page.click('#tool-updates-start');
    await page.waitForFunction(() => !document.querySelector('#tool-updates-cancel').classList.contains('hidden'));
    assert.deepEqual(await page.evaluate(() => window.updates.calls), [['start', ['Falta', 'Nova']]]);
    assert.equal(await page.textContent('#tool-updates-message'), 'A descarregar…');
    assert.equal(await page.$eval('#tool-updates-bar', (n) => n.style.width), '25%');
    assert.equal(await page.locator('#tool-updates-list input:not([disabled])').count(), 0);
    assert.equal(await page.$eval('[data-tool-key="Falta"]', (n) => n.classList.contains('current')), true);
    assert.equal(await page.isDisabled('#tool-updates-start'), true);
    await page.click('#tool-updates-cancel');
    assert.equal(await page.textContent('#tool-updates-message'), 'A cancelar…');
    // o trabalho acaba: resultados por ferramenta e estado atualizado pelo temporizador
    await page.evaluate(() => {
      window.updates.tools = window.updates.tools.map((t) => t.key === 'Nova' ? {...t, status: 'installed'} : t);
      window.updates.job = {state: 'done', current: '', message: '1 instalada(s), 0 já estava(m), 0 por fazer à mão, 1 com erro.', done_bytes: 4 * 1048576, total_bytes: 4 * 1048576,
        results: [{key: 'Falta', status: 'failed', message: 'SHA-256 diferente do registado'}, {key: 'Nova', status: 'installed', message: 'Instalada (versão 1.0).'}]};
    });
    await page.waitForFunction(() => document.querySelector('#tool-updates-cancel').classList.contains('hidden') && document.querySelector('[data-tool-key="Nova"] .badge').textContent === 'Instalada');
    assert.match(await page.textContent('[data-tool-key="Falta"] .notice.warn'), /falhou — SHA-256 diferente do registado/);
    assert.match(await page.textContent('[data-tool-key="Nova"] .tool-update-result'), /instalada agora — Instalada/);
    assert.match(await page.textContent('#tool-updates-message'), /1 com erro/);
    assert.equal(await page.isDisabled('[data-tool-key="Nova"] input'), true);
    // recusa da ponte aparece como erro
    await page.evaluate(() => { window.updates.refuse = true; });
    await page.check('[data-tool-key="Falta"] input');
    await page.click('#tool-updates-start');
    await page.waitForFunction(() => !document.querySelector('#error-box').classList.contains('hidden'));
    assert.match(await page.textContent('#error-box'), /Já há uma instalação em curso/);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#tool-updates-modal').isVisible(), false);
    assert.deepEqual(errors, []);
    console.log('PASS: manifest list by group, only installable rows selectable, confirm with size and folder, start/progress/cancel, per-tool results, bridge refusal, text not HTML, no JS errors');
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exit(1); });
