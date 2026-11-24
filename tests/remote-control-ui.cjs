// Página do acesso remoto num ecrã de telemóvel, contra o servidor verdadeiro com uma Api de faz-de-conta
// (tests/remote_control_fake.py): emparelhar, ver a conversa, enviar, acompanhar a resposta, responder a uma aprovação.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict'), {spawn} = require('node:child_process'), readline = require('node:readline');
(async () => {
  const server = spawn('python', ['tests/remote_control_fake.py'], {stdio: ['pipe', 'pipe', 'inherit'], env: {...process.env, PYTHONUTF8: '1'}});
  const lines = readline.createInterface({input: server.stdout})[Symbol.asyncIterator]();
  const next = async () => JSON.parse((await lines.next()).value);
  const currentCode = async () => { server.stdin.write('codigo\n'); return (await next()).code; };
  const {url, code} = await next();
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 390, height: 780}, isMobile: true, hasTouch: true});
    const page = await context.newPage(), errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(url);

    // sem emparelhar: só o pedido do código
    await page.waitForSelector('#pair:not(.hidden)');
    assert.equal(await page.locator('#messages .msg').count(), 0);
    await page.fill('#code', 'AAAA-AAAA');
    await page.click('#pair-ok');
    await page.waitForFunction(() => document.querySelector('#pair-error').textContent !== '');
    assert.equal(await page.textContent('#pair-error'), 'Código errado.');
    await page.fill('#code', code.toLowerCase());
    await page.click('#pair-ok');
    await page.waitForSelector('#pair', {state: 'hidden'});
    await page.waitForFunction(() => document.querySelectorAll('#messages .msg').length === 2);

    // a conversa aparece como texto, sem dados privados
    const second = page.locator('#messages .msg').nth(1);
    assert.match(await second.textContent(), /Olá! <b>não é HTML<\/b>/);
    assert.equal(await second.locator('b').count(), 0, 'o texto do servidor nunca vira HTML');
    assert.match(await second.textContent(), /\[image gerado: vê no PC\]/);
    assert.match(await second.textContent(), /✓ ler_ficheiro/);
    assert.equal((await page.content()).includes('C:/Users/alguem'), false);
    assert.deepEqual(await page.$$eval('#context optgroup', (groups) => groups.map((g) => [g.label, g.children.length])), [['Projetos', 1], ['Conversas', 2]]);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, 'cabe no ecrã do telemóvel sem deslizar para o lado');

    // enviar e ver a resposta a chegar
    await page.fill('#text', 'conta-me uma coisa');
    await page.click('#send');
    await page.waitForSelector('#stop:not(.hidden)');
    assert.equal(await page.inputValue('#text'), '');
    await page.waitForFunction(() => [...document.querySelectorAll('#messages .msg.assistant')].some((n) => n.textContent === 'Respos'), null, {timeout: 10000});
    await page.waitForSelector('#send:not(.hidden)', {timeout: 15000});
    const texts = await page.$$eval('#messages .msg', (nodes) => nodes.map((n) => [n.classList.contains('user') ? 'user' : 'assistant', n.textContent]));
    assert.deepEqual(texts.slice(-2), [['user', 'conta-me uma coisa'], ['assistant', 'Resposta a: conta-me uma coisa']]);
    assert.equal(texts.length, 4, 'no fim fica a conversa guardada, sem bolhas repetidas');

    // cartão de aprovação: aparece no telemóvel e a resposta chega ao agente
    await page.fill('#text', 'corre um comando');
    await page.click('#send');
    await page.waitForSelector('#approval:not(.hidden)', {timeout: 10000});
    assert.equal(await page.textContent('#approval-category'), 'perigoso');
    assert.equal(await page.textContent('#approval-detail'), 'Remove-Item -Recurse C:\\tudo');
    await page.click('#approval-deny');
    await page.waitForSelector('#approval', {state: 'hidden'});
    await page.waitForFunction(() => [...document.querySelectorAll('#messages .msg.assistant')].pop().textContent === 'Comando recusado.', null, {timeout: 15000});

    // erro do provedor
    await page.fill('#text', 'isto falha');
    await page.click('#send');
    await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('Falhou: O provedor recusou.'), null, {timeout: 10000});
    assert.equal(await page.locator('#send').isVisible(), true);

    // mudar de conversa e criar uma nova
    await page.selectOption('#context', 'conversation:c2');
    await page.waitForFunction(() => document.querySelector('#messages .empty') && document.querySelector('#messages .empty').textContent === 'Conversa vazia.');
    await page.click('#new');
    await page.waitForFunction(() => document.querySelectorAll('#context optgroup')[1].children.length === 3);

    // outro dispositivo: sem cookie não vê nada; o código antigo já não serve
    const other = await (await browser.newContext({viewport: {width: 390, height: 780}})).newPage();
    await other.goto(url);
    await other.waitForSelector('#pair:not(.hidden)');
    await other.fill('#code', code);
    await other.click('#pair-ok');
    await other.waitForFunction(() => document.querySelector('#pair-error').textContent !== '');
    assert.equal(await other.locator('#messages .msg').count(), 0);
    await other.fill('#code', await currentCode());
    await other.click('#pair-ok');
    await other.waitForSelector('#pair', {state: 'hidden'});

    // recarregar a página mantém a sessão (cookie)
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#context').options.length === 4);
    assert.equal(await page.locator('#pair').isVisible(), false);
    assert.deepEqual(errors, []);
    console.log('PASS: pairing (wrong, right, single-use), conversation as text, send + live answer, approval from the phone, provider error, switch/new, second device, reload keeps session, fits a phone screen, no JS errors');
  } finally {
    await browser.close();
    server.stdin.write('fim\n');
    server.kill();
  }
})().catch((error) => { console.error(error); process.exit(1); });
