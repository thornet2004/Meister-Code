// Interface do painel «Conhecimento» (base de conhecimento por projeto), com a ponte simulada.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict'), path = require('node:path'), {pathToFileURL} = require('node:url');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1200, height: 900}}), errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.addInitScript(() => {
      const kn = window.kn = {notas: [], seq: 0, calls: []};
      const lista = (q) => kn.notas.filter((n) => !q || (n.titulo + ' ' + n.texto).toLowerCase().includes(q.toLowerCase()))
        .map((n) => ({id: n.id, titulo: n.titulo, tipo: n.tipo, ref: n.ref, etiquetas: n.etiquetas, trecho: n.texto.slice(0, 300)}));
      window.pywebview = {api: {
        get_state: async () => ({ok: true, providers: [], projects: [], conversations: []}),
        get_conversation: async () => ({ok: true, messages: []}),
        get_notes: async (query = '', _limit = 50) => { kn.calls.push(['get', query]); return {ok: true, notas: lista(query)}; },
        read_note: async (id) => { const n = kn.notas.find((x) => x.id === id); return n ? {ok: true, encontrada: true, nota: {...n}} : {ok: true, encontrada: false}; },
        save_note: async (titulo, texto, etiquetas, tipo, ref, id) => {
          kn.calls.push(['save', titulo, id]);
          let n = id != null ? kn.notas.find((x) => x.id === id) : null;
          if (n) { Object.assign(n, {titulo, texto, etiquetas, tipo, ref}); } else { n = {id: ++kn.seq, titulo, texto, etiquetas, tipo, ref}; kn.notas.push(n); }
          return {ok: true, id: n.id, titulo, atualizada: id != null};
        },
        forget_note: async (id) => { kn.calls.push(['forget', id]); kn.notas = kn.notas.filter((x) => x.id !== id); return {ok: true, apagada: true}; },
      }};
    });
    await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
    await page.click('#btn-knowledge');
    // nova nota: abre o formulário, preenche e guarda; aparece na lista
    await page.click('#knowledge-modal button:has-text("Nova nota")');
    await page.fill('#kn-titulo', 'Função de login');
    await page.fill('#kn-texto', 'Fica em 0x401000');
    await page.fill('#kn-etiquetas', 'auth');
    await page.click('#kn-form button:has-text("Guardar nota")');
    await page.waitForFunction(() => document.querySelectorAll('#kn-results article').length === 1);
    assert.match(await page.textContent('#kn-results'), /Função de login/);
    // pesquisar algo que não existe: lista vazia
    await page.fill('#kn-query', 'inexistente');
    await page.press('#kn-query', 'Enter');
    await page.waitForFunction(() => document.querySelector('#kn-results').textContent.includes('Sem notas'));
    // pesquisar pela nota: volta a aparecer
    await page.fill('#kn-query', 'login');
    await page.press('#kn-query', 'Enter');
    await page.waitForFunction(() => document.querySelectorAll('#kn-results article').length === 1);
    // editar: abre o formulário preenchido e guarda a alteração
    await page.click('#kn-results button:has-text("Editar")');
    await page.waitForFunction(() => document.querySelector('#kn-titulo').value === 'Função de login');
    await page.fill('#kn-texto', 'Afinal chama hash_senha');
    await page.click('#kn-form button:has-text("Guardar nota")');
    await page.waitForFunction(() => { const p = document.querySelector('#kn-results pre'); return p && p.textContent.includes('hash_senha'); });
    // apagar: some da lista
    await page.click('#kn-results button:has-text("Apagar")');
    await page.waitForFunction(() => document.querySelector('#kn-results').textContent.includes('Sem notas'));
    const calls = await page.evaluate(() => window.kn.calls);
    assert.ok(calls.some((c) => c[0] === 'save' && c[2] == null), 'gravou uma nota nova');
    assert.ok(calls.some((c) => c[0] === 'save' && c[2] != null), 'atualizou uma nota existente');
    assert.ok(calls.some((c) => c[0] === 'forget'), 'apagou uma nota');
    assert.deepEqual(errors, []);
    console.log('PASS: knowledge panel — nova/listar/pesquisar/editar/apagar notas, sem erros de JS');
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exit(1); });
