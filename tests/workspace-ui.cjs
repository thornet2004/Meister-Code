const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.testCalls = [];
      window.pywebview = {api: {
        get_state: async () => ({ok: true, output_dir: 'C:\\Projeto', providers: [], projects: [], conversations: []}),
        get_conversation: async () => ({ok: true, messages: []}),
        get_context_usage: async () => ({ok: true, used: 12000, limit: 128000, percent: 9.4, parts: {sistema: 2000, memoria: 0, resumo: 0, mensagens: 9000, ferramentas: 1000}, series: [{role: 'system', tokens: 2000}, {role: 'user', tokens: 3000}, {role: 'assistant', tokens: 6000}, {role: 'tools', tokens: 1000}], total_messages: 5, older: 0, history_window: 40, compacted: false, summary_chars: 0, limit_source: 'model'}),
        compact_context: async () => { window.testCalls.push(['compact']); return {ok: true, compacted: 3, kept: 12}; },
        set_context_window: async () => ({ok: true}),
        get_tool_catalog: async () => ({ok:true, tools:[{name:'browser_ler',description:'Lê a página atual'},{name:'memoria_consultar',description:'Pesquisa a memória persistente'}]}),
        terminal_execute: async (command) => { window.testCalls.push(['terminal', command]); return {ok: true, output: '42\n', cwd: 'C:\\Projeto'}; },
        // terminal interativo simulado: 'pedir' fica a correr à espera de uma linha; o resto responde 42
        terminal_send: async (text) => {
          window.testCalls.push(['terminal', text]);
          const t = window.term = window.term || {out: '', busy: false};
          if (t.busy) { t.out += 'ola ' + text + '\n'; t.busy = false; return {ok: true, mode: 'input', cursor: 0}; }
          if (text === 'pedir') { t.out += 'nome? '; t.busy = true; } else { t.out += '42\n'; }
          return {ok: true, mode: 'command', cursor: 0};
        },
        terminal_read: async (cursor) => { const t = window.term || {out: '', busy: false}; const output = t.out; t.out = ''; return {ok: true, output, cursor: cursor + output.length, busy: t.busy, alive: true, cwd: 'C:\\Projeto', exit_code: 0}; },
        terminal_stop: async () => { window.testCalls.push(['terminal-stop']); const t = window.term; t.busy = false; t.out += '[interrompido]\n'; return {ok: true, stopped: true, restarted: false}; },
        open_browser: async (url) => { window.testCalls.push(['browser', url]); return {ok: true}; },
        browser_layout: async (rect) => { window.lastBrowserBounds = rect; return {ok: true}; },
        browser_action: async () => ({ok: true}),
        browser_state: async () => ({ok: true, url:'http://localhost:3000', title:'App local', back:false, forward:false}),
        chat: async (text, attachments) => { window.testCalls.push(['chat', text, attachments]); return {ok: true}; },
        create_project: async (name) => { window.testCalls.push(['create_project', name]); return {ok: true}; },
        delete_project: async (id, disk) => { window.testCalls.push(['delete_project', id, disk]); return {ok: true}; },
        delete_conversation: async (id, disk) => { window.testCalls.push(['delete_conversation', id, disk]); return {ok: true}; },
      }};
    });
    await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
    await page.waitForFunction(() => document.querySelector('#chat').children.length > 0);
    await page.waitForFunction(() => document.querySelector('#context-label').textContent.includes('9,4%'));
    await page.click('#context-compact');
    await page.waitForFunction(() => document.querySelector('#toasts').textContent.includes('Contexto compactado'));
    assert.equal(await page.evaluate(() => window.testCalls.some(c => c[0] === 'compact')), true);
    const markdown = await page.evaluate(() => formatText("**negrito**\n\n```js\nconst a = 1;\n```"));
    assert(markdown.includes("<strong>negrito</strong>"));
    assert(markdown.includes("copy-code"));
    await page.keyboard.press("Control+k");
    await page.waitForFunction(() => !document.querySelector('#palette').classList.contains('hidden'));
    await page.keyboard.press("Escape");
    await page.fill('#composer', '/');
    await page.waitForFunction(() => !document.querySelector('#slash-menu').classList.contains('hidden'));
    await page.fill('#composer', '');
    await page.waitForFunction(() => document.querySelector('#slash-menu').classList.contains('hidden'));
    await page.click('#btn-terminal');
    await page.fill('#terminal-input', 'Write-Output 42');
    await page.press('#terminal-input', 'Enter');
    await page.waitForFunction(() => document.querySelector('#terminal-output').textContent.includes('42\n'));
    await page.press('#terminal-input', 'ArrowUp');
    assert.equal(await page.inputValue('#terminal-input'), 'Write-Output 42');
    // interativo: o programa pede dados, a linha seguinte vai para ele, e há botão Parar
    assert.equal(await page.locator('#terminal-stop').isVisible(), false);
    await page.fill('#terminal-input', 'pedir');
    await page.press('#terminal-input', 'Enter');
    await page.waitForFunction(() => document.querySelector('#terminal-output').textContent.includes('nome? '));
    await page.waitForFunction(() => !document.querySelector('#terminal-stop').classList.contains('hidden'));
    assert.equal(await page.locator('#terminal-run').textContent(), 'Enviar');
    await page.fill('#terminal-input', 'Rui');
    await page.press('#terminal-input', 'Enter');
    await page.waitForFunction(() => document.querySelector('#terminal-output').textContent.includes('ola Rui\n'));
    await page.waitForFunction(() => document.querySelector('#terminal-stop').classList.contains('hidden'));
    assert.equal(await page.locator('#terminal-run').textContent(), 'Executar');
    await page.press('#terminal-input', 'ArrowUp');
    assert.equal(await page.inputValue('#terminal-input'), 'pedir', 'a entrada dada ao programa não entra no histórico de comandos');
    await page.press('#terminal-input', 'Enter');
    await page.waitForFunction(() => !document.querySelector('#terminal-stop').classList.contains('hidden'));
    await page.click('#terminal-stop');
    await page.waitForFunction(() => document.querySelector('#terminal-output').textContent.includes('[interrompido]'));
    await page.waitForFunction(() => document.querySelector('#terminal-stop').classList.contains('hidden'));
    assert.ok(await page.evaluate(() => window.testCalls.some(call => call[0] === 'terminal-stop')));
    await page.click('#btn-browser');
    assert.equal(await page.locator('#browser-panel').isVisible(), true);
    const chatBounds = await page.locator('.chat-panel').boundingBox();
    const browserBounds = await page.locator('#browser-panel').boundingBox();
    assert(browserBounds.x >= chatBounds.x + chatBounds.width, 'Browser must be to the right of chat');
    await page.fill('#browser-url', 'http://localhost:3000');
    await page.press('#browser-url', 'Enter');
    await page.waitForFunction(() => window.testCalls.some(c => c[0] === 'browser' && c[1] === 'http://localhost:3000'));
    assert.equal(await page.evaluate(() => window.lastBrowserBounds.visible), true);
    for (const selector of ['#chat', '#composer']) {
      await page.evaluate((selector) => {
        const transfer = new DataTransfer();
        transfer.items.add(new File(['conteudo'], selector === '#chat' ? 'conversa.txt' : 'caixa.txt', {type:'text/plain'}));
        const target = document.querySelector(selector);
        target.dispatchEvent(new DragEvent('dragenter', {bubbles:true, cancelable:true, dataTransfer:transfer}));
        if (document.querySelector('#drop-hint').classList.contains('hidden')) throw new Error('Missing drop hint');
        target.dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer:transfer}));
      }, selector);
    }
    await page.waitForFunction(() => document.querySelectorAll('#attachments .attachment-chip').length === 2 || document.querySelector('#attachments').textContent.includes('caixa.txt'));
    assert.match(await page.textContent('#attachments'), /conversa.txt/);
    assert.match(await page.textContent('#attachments'), /caixa.txt/);
    // colar um ficheiro copiado anexa-o; colar texto continua a escrever na caixa
    const pasted = await page.evaluate(() => {
      const box = document.querySelector('#composer');
      const file = new DataTransfer();file.items.add(new File(['colado'], 'colado.txt', {type:'text/plain'}));
      const first = new ClipboardEvent('paste', {bubbles:true, cancelable:true, clipboardData:file});box.dispatchEvent(first);
      const text = new DataTransfer();text.setData('text/plain', 'só texto');text.items.add(new File(['x'], 'imagem.png', {type:'image/png'}));
      const second = new ClipboardEvent('paste', {bubbles:true, cancelable:true, clipboardData:text});box.dispatchEvent(second);
      return [first.defaultPrevented, second.defaultPrevented];
    });
    assert.deepEqual(pasted, [true, false]);
    await page.waitForFunction(() => document.querySelector('#attachments').textContent.includes('colado.txt'));
    assert.doesNotMatch(await page.textContent('#attachments'), /imagem.png/);
    await page.screenshot({path: 'tests/workspace-tools.png'});
    await page.fill('#composer', 'Analisa estes ficheiros');
    await page.click('#btn-send');
    await page.waitForFunction(() => window.testCalls.some(c => c[0] === 'chat'));
    const sent = await page.evaluate(() => window.testCalls.find(c => c[0] === 'chat'));
    assert.equal(sent[2].length, 3);
    assert.equal(Buffer.from(sent[2].find(a => a.name === 'colado.txt').b64, 'base64').toString(), 'colado');
    assert.equal(Buffer.from(sent[2][0].b64, 'base64').toString(), 'conteudo');
    await page.click('#browser-close');
    assert.equal(await page.locator('#browser-panel').isVisible(), false);
    await page.click('#btn-browser');
    assert.equal(await page.locator('#browser-panel').isVisible(), true);
    page.on('dialog', dialog => dialog.accept());
    for (const type of ['project', 'conversation']) {
      for (const disk of [false, true]) {
        await page.evaluate(type => openDeleteItem({id:'test-id', name:'Projeto', title:'Conversa', path:'C:\\Pasta'}, type), type);
        assert.equal(await page.isChecked('input[name="delete-mode"][value="list"]'), true);
        if (disk) await page.check('#del-files');
        await page.click('#modal-ok');
        const last = await page.evaluate(type => window.testCalls.filter(c => c[0] === 'delete_' + type).at(-1), type);
        assert.deepEqual(last, ['delete_' + type, 'test-id', disk]);
      }
    }
    await page.click('#btn-add-project');
    await page.fill('#pr-name', 'Projeto novo');
    await page.click('#modal-ok');
    assert.deepEqual(await page.evaluate(() => window.testCalls.find(c => c[0] === 'create_project')), ['create_project', 'Projeto novo']);
    await page.click('#btn-settings');
    await page.waitForFunction(() => document.querySelector('#tools-count').textContent === '2');
    assert.match(await page.textContent('#tools-list'), /browser_ler/);
    assert.match(await page.textContent('#tools-list'), /memoria_consultar/);
    await page.click('#settings-close');
    assert.deepEqual(errors, []);
    console.log('PASS: terminal, browser, drops, pasted files, attachment send, managed project creation, both deletion choices for projects/conversations, no JS errors');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
