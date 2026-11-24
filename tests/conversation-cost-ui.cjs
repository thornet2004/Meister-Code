// Interface do custo: por resposta (junto aos tokens) e por conversa (junto ao medidor de contexto).
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict'), path = require('node:path'), {pathToFileURL} = require('node:url');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1300, height: 900}}), errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.addInitScript(() => {
      window.costCase = 'mixed';
      const usage = {prompt_tokens: 1000, completion_tokens: 500, total_tokens: 1500};
      const base = {ok: true, used: 1200, limit: 128000, percent: 0.9, parts: {}, total_messages: 4, older: 0, history_window: 40};
      const costs = {
        mixed: {usd: 0.0053, currency: 'USD', exact: false, turns: 2, unknown_turns: 1, prompt_tokens: 3000, completion_tokens: 1500,
          models: [{model_id: 'barato', usd: 0.0053, tokens: 3000, unknown: 0}, {model_id: 'llama', usd: 0, tokens: 1500, unknown: 1}],
          subagents: {usd: 0.002, tasks: 1}, note: 'Estimativa a partir dos tokens.'},
        exact: {usd: 1.2345, currency: 'USD', exact: true, turns: 3, unknown_turns: 0, prompt_tokens: 9, completion_tokens: 9, models: [], subagents: {usd: 0, tasks: 0}, note: ''},
        unknown: {usd: 0, currency: 'USD', exact: false, turns: 0, unknown_turns: 2, prompt_tokens: 9, completion_tokens: 9, models: [], subagents: {usd: 0, tasks: 0}, note: ''},
        none: {usd: 0, currency: 'USD', exact: false, turns: 0, unknown_turns: 0, prompt_tokens: 0, completion_tokens: 0, models: [], subagents: {usd: 0, tasks: 0}, note: ''},
      };
      window.pywebview = {api: {
        get_state: async () => ({ok: true, providers: [], projects: [], conversations: []}),
        get_conversation: async () => ({ok: true, messages: [
          {role: 'user', text: 'pergunta'},
          {role: 'assistant', text: 'estimada', usage, cost: {usd: 0.002, source: 'catalog'}},
          {role: 'assistant', text: 'do provedor', usage, cost: {usd: 0.0033, source: 'provider'}},
          {role: 'assistant', text: 'sem preço', usage},
        ]}),
        get_context_usage: async () => ({...base, cost: window.costCase === 'missing' ? undefined : costs[window.costCase]}),
      }};
    });
    await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
    // por resposta: estimativa com "≈", valor do provedor sem "≈", e só tokens quando não há preço
    await page.waitForFunction(() => document.querySelectorAll('.msg-usage').length === 3);
    const lines = await page.$$eval('.msg-usage', (nodes) => nodes.map((n) => [n.textContent, n.title]));
    assert.equal(lines[0][0], '≈1,5k tokens · ≈US$ 0,0020');
    assert.match(lines[0][1], /catálogo/);
    assert.equal(lines[1][0], '≈1,5k tokens · US$ 0,0033');
    assert.match(lines[1][1], /indicado pelo provedor/);
    assert.equal(lines[2][0], '≈1,5k tokens');
    // por conversa: total estimado, com aviso de respostas sem preço
    await page.waitForFunction(() => !document.querySelector('#conversation-cost').classList.contains('hidden'));
    assert.equal(await page.textContent('#conversation-cost'), '≈US$ 0,0053 + ?');
    const title = await page.getAttribute('#conversation-cost', 'title');
    assert.match(title, /≈US\$ 0,0053 em 2 resposta/);
    assert.match(title, /1 resposta\(s\) sem preço conhecido — não entram no total/);
    assert.match(title, /barato: US\$ 0,0053/);
    assert.match(title, /llama: sem preço/);
    assert.match(title, /inclui 1 subagente\(s\): US\$ 0,0020/);
    const refresh = async (kind) => { await page.evaluate((k) => { window.costCase = k; return refreshContextUsage(); }, kind); };
    await refresh('exact');
    assert.equal(await page.textContent('#conversation-cost'), 'US$ 1,23', 'tudo indicado pelo provedor: sem "≈"');
    await refresh('unknown');
    assert.equal(await page.textContent('#conversation-cost'), 'custo ?');
    await refresh('none');
    assert.equal(await page.locator('#conversation-cost').isVisible(), false, 'conversa sem respostas: não mostra custo');
    await refresh('missing');
    assert.equal(await page.locator('#conversation-cost').isVisible(), false, 'ponte antiga sem o campo: não parte');
    assert.deepEqual(errors, []);
    console.log('PASS: per-message cost (estimate/provider/unknown), conversation total, unknown turns, per-model and subagent lines, exact total, hidden when empty, no JS errors');
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exit(1); });
