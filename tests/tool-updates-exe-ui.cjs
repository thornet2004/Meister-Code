// Ensaio REAL do botão «Atualizar ferramentas» no executável empacotado, como se estivesse instalado.
// Fora da suite: descarrega da internet (o núcleo são ~310 MB) e demora vários minutos.
// Não toca nos dados do utilizador: APPDATA e LOCALAPPDATA apontam para uma pasta de ensaio.
//   TOOLS_TRIAL_DIR   pasta de ensaio (por omissão, uma nova na pasta temporária); fica para inspeção
//   TOOLS_TRIAL_KEYS  chaves a escolher, separadas por vírgulas (por omissão CoreLSP,CorePackages,Core7Zip,RTL433)
//   TOOLS_TRIAL_EXE   executável único a ensaiar como instalação antiga (dados em LOCALAPPDATA); sem ela ensaia-se a versão
//                     em pasta que o Setup instala (dist/Meister IA IDE), que guarda tudo dentro de si própria
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os'), net = require('node:net'), assert = require('node:assert/strict');
const { spawn, execFileSync } = require('node:child_process');

const freePort = () => new Promise((resolve) => { const server = net.createServer(); server.listen(0, '127.0.0.1', () => { const { port } = server.address(); server.close(() => resolve(port)); }); });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

(async () => {
  const root = path.resolve('.');
  const single = !!process.env.TOOLS_TRIAL_EXE;
  const source = path.resolve(process.env.TOOLS_TRIAL_EXE || path.join(root, 'dist/Meister IA IDE'));
  assert(fs.existsSync(source), 'falta o executável: ' + source);
  const keys = (process.env.TOOLS_TRIAL_KEYS || 'CoreLSP,CorePackages,Core7Zip,RTL433').split(',').map((key) => key.trim()).filter(Boolean);
  const temp = process.env.TOOLS_TRIAL_DIR ? path.resolve(process.env.TOOLS_TRIAL_DIR) : fs.mkdtempSync(path.join(os.tmpdir(), 'meistercode-exe-ferramentas-'));
  const installed = path.join(temp, 'instalada'), appdata = path.join(temp, 'AppData'), local = path.join(temp, 'Local'), wintemp = path.join(temp, 'TempDoWindows');
  for (const folder of [installed, appdata, local, wintemp]) fs.mkdirSync(folder, { recursive: true });
  // TOOLS_TRIAL_INSTALLED: pasta onde o Setup.exe verdadeiro já instalou a app; sem ela, imita-se a instalação
  const real = process.env.TOOLS_TRIAL_INSTALLED ? path.resolve(process.env.TOOLS_TRIAL_INSTALLED) : '';
  const executable = path.join(real || installed, 'Studio de Media.exe');
  if (real) {
    assert(fs.existsSync(executable) && fs.existsSync(path.join(real, 'studio-install.json')), 'a pasta instalada não tem o executável e o studio-install.json: ' + real);
  } else if (!single) {
    // o que o Setup faz: copia a pasta e põe o marcador que manda a app trabalhar só dentro dela
    fs.cpSync(source, installed, { recursive: true });
    fs.copyFileSync(path.join(root, 'installer/portable.json'), path.join(installed, 'meistercode-portable.json'));
  } else {
    fs.copyFileSync(source, executable);
    // o mesmo ficheiro que o instalador Inno Setup põe ao lado do executável: é ele que diz à app que está instalada
    fs.copyFileSync(path.join(root, 'installer/installed.json'), path.join(installed, 'studio-install.json'));
  }
  const inside = !real && !single;
  const expectedRoot = inside ? path.join(installed, 'Ferramentas') : path.join(local, 'Meister IA IDE', 'Ferramentas');
  const port = await freePort();
  const app = spawn(executable, [], { cwd: real || installed, windowsHide: true, stdio: 'ignore', env: { ...process.env, APPDATA: appdata, LOCALAPPDATA: local, TEMP: wintemp, TMP: wintemp, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port} --remote-allow-origins=*` } });
  let browser = null, failure = null;
  try {
    for (let i = 0; i < 150 && !browser; i++) { try { browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`); } catch { await sleep(400); } }
    assert(browser, 'a app empacotada não abriu a janela');
    let page = null;
    for (let i = 0; i < 100 && !page; i++) { page = browser.contexts().flatMap((context) => context.pages()).find((item) => item.url().includes('index.html')); if (!page) await sleep(200); }
    assert(page, 'não encontrei a página da app');
    await page.waitForFunction(() => window.pywebview && window.pywebview.api && window.pywebview.api.get_tool_updates, null, { timeout: 60000 });
    const state = () => page.evaluate(() => window.pywebview.api.get_tool_updates());

    await page.click('#btn-tools');
    await page.click('#tools-update');
    await page.waitForSelector('#tool-updates-list article');
    const before = await state();
    assert.equal(before.ok, true, before.error);
    assert.equal(path.resolve(before.root).toLowerCase(), expectedRoot.toLowerCase(), 'a app instalada tem de instalar na pasta de dados do utilizador');
    if (inside) {
      // primeira abertura: as pastas nascem dentro da pasta da app e nada vai para AppData nem para a Temp do Windows
      for (const name of ['Configuracao', 'Conversas', 'Projectos', 'Ferramentas', 'Temp']) assert(fs.existsSync(path.join(installed, name)), 'falta a pasta ' + name + ' dentro da app');
      for (const [name, folder] of [['APPDATA', appdata], ['LOCALAPPDATA', local], ['TEMP', wintemp]]) assert.deepEqual(fs.readdirSync(folder), [], 'a app escreveu em ' + name + ': ' + fs.readdirSync(folder));
      console.log('primeira abertura: Configuracao, Conversas, Projectos, Ferramentas e Temp criadas dentro da pasta da app; nada em APPDATA, LOCALAPPDATA nem na Temp do Windows');
    }
    assert.equal(await page.locator('#tool-updates-list article').count(), before.tools.length);
    assert(before.tools.length >= 44, 'o manifesto empacotado tem ' + before.tools.length + ' entradas');
    assert.equal(before.tools.filter((tool) => tool.status === 'installed').length, 0, 'numa instalação nova nada vem instalado');
    console.log(`painel: ${before.tools.length} entradas, nenhuma instalada; pasta ${before.root}`);

    for (const key of keys) await page.check(`#tool-updates-list article[data-tool-key="${key}"] input[type=checkbox]`);
    let question = '';
    page.once('dialog', (dialog) => { question = dialog.message(); dialog.accept(); });
    await page.click('#tool-updates-start');
    for (let i = 0; i < 50 && !question; i++) await sleep(100);
    assert(question.includes(before.root), 'a confirmação mostra a pasta: ' + question);
    console.log('confirmação: ' + question.split('\n')[0]);

    const started = Date.now();
    let last = '', job = null;
    for (;;) {
      await sleep(3000);
      job = (await state()).job;
      const line = `${job.current || '-'}: ${job.message || ''}`;
      if (line !== last) { console.log(`  [${Math.round((Date.now() - started) / 1000)} s] ${line}`); last = line; }
      if (job.state !== 'running') break;
      assert(Date.now() - started < 60 * 60 * 1000, 'a instalação passou de uma hora');
    }
    const after = await state();
    for (const row of job.results) console.log(`  ${row.key}: ${row.status} — ${row.message}`);
    assert.deepEqual(job.results.filter((row) => !['installed', 'already'].includes(row.status)), [], 'houve entradas que não ficaram instaladas');
    const byKey = Object.fromEntries(after.tools.map((tool) => [tool.key, tool]));
    const expected = new Set(keys);
    const visit = (key) => (byKey[key].requires || []).forEach((dep) => { expected.add(dep); visit(dep); });
    keys.forEach(visit);
    for (const key of expected) assert.equal(byKey[key].status, 'installed', key + ' ficou ' + byKey[key].status);
    // o painel atualiza-se sozinho pouco depois de a instalação acabar
    for (const key of expected) await page.waitForFunction((k) => document.querySelector(`#tool-updates-list article[data-tool-key="${k}"] .badge`).textContent.trim() === 'Instalada', key, {timeout: 10000});
    // sem ferramenta.json a app não descobre a ferramenta: o pacote tem de o trazer e o instalador de o pôr na pasta
    if (expected.has('RTL433')) assert.equal(fs.existsSync(path.join(expectedRoot, 'RTL433', 'ferramenta.json')), true, 'falta o ferramenta.json da ferramenta instalada');
    // o que mais entrou no pacote: ditado, acesso remoto e a página do telemóvel
    const extras = await page.evaluate(async () => ({voiceButton: !!document.querySelector('#btn-voice'), voice: await window.pywebview.api.get_voice_input(),
      remote: await window.pywebview.api.get_remote_control(), remoteCommand: typeof window.openRemoteControl === 'function'}));
    assert.equal(extras.voiceButton && extras.voice.ok && extras.voice.ready === false && extras.remote.ok && extras.remote.running === false && extras.remoteCommand, true, JSON.stringify(extras));
    console.log('ferramenta.json presente; ditado e acesso remoto respondem (sem o Whisper instalado nesta pasta de ensaio; acesso remoto desligado)');
    if (inside) for (const [name, folder] of [['APPDATA', appdata], ['LOCALAPPDATA', local], ['TEMP', wintemp]]) assert.deepEqual(fs.readdirSync(folder), [], 'depois de instalar, a app escreveu em ' + name + ': ' + fs.readdirSync(folder));
    console.log(`PASS: ${expected.size} entradas instaladas pelo botão na app empacotada (${[...expected].join(', ')}), em ${Math.round((Date.now() - started) / 1000)} s. Pasta de ensaio: ${temp}`);
  } catch (error) {
    failure = error;
  } finally {
    if (browser) await browser.close().catch(() => {});
    try { execFileSync('taskkill', ['/PID', String(app.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' }); } catch { /* já tinha fechado */ }
  }
  if (failure) { console.error('FALHOU: ' + failure.message + '\nPasta de ensaio: ' + temp); process.exit(1); }
})();
