// Botão de ditado: grava de um microfone simulado pelo browser, envia um WAV mono/16 bits/16 kHz pela ponte (simulada)
// e põe o texto na caixa de mensagem sem o enviar.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict'), path = require('node:path'), {pathToFileURL} = require('node:url');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']});
  try {
    const context = await browser.newContext({viewport: {width: 1300, height: 900}});
    const page = await context.newPage(), errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.addInitScript(() => {
      window.voice = {ready: false, calls: [], reply: {ok: true, text: 'Cria um <b>ficheiro</b> novo.', duration: 1.2, seconds: 0.4}, sent: 0};
      window.pywebview = {api: {
        get_state: async () => ({ok: true, providers: [], projects: [], conversations: []}),
        get_conversation: async () => ({ok: true, messages: []}),
        get_context_usage: async () => ({ok: true, used: 0, limit: 128000, percent: 0, parts: {}, total_messages: 0, older: 0, history_window: 40}),
        get_voice_input: async () => window.voice.ready ? {ok: true, ready: true, reason: '', model: 'ggml-small-q5_1.bin', max_seconds: 300, sample_rate: 16000}
          : {ok: true, ready: false, reason: 'Falta o Whisper: instala «Whisper (voz para texto, local)» em Ferramentas.'},
        transcribe_voice: async (audio, language) => { window.voice.calls.push({audio, language}); return window.voice.reply; },
        send_message: async () => { window.voice.sent++; return {ok: true}; },
      }};
    });
    await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
    await page.waitForFunction(() => document.querySelector('#context-label').textContent !== '—');
    const button = page.locator('#btn-voice');
    assert.equal(await button.textContent(), '🎤');
    assert.match(await button.getAttribute('title'), /o áudio não sai do PC/);

    // sem o Whisper instalado: diz o que falta e não liga o microfone
    await button.click();
    await page.waitForSelector('#error-box:not(.hidden)');
    assert.match(await page.textContent('#error-box'), /Falta o Whisper/);
    assert.equal(await button.getAttribute('aria-pressed'), 'false');
    await page.evaluate(() => { document.querySelector('#error-box').classList.add('hidden'); window.voice.ready = true; });

    // gravar, parar, transcrever
    await page.fill('#composer', 'Antes');
    await button.click();
    await page.waitForFunction(() => document.querySelector('#btn-voice').classList.contains('recording'));
    assert.equal(await button.textContent(), '■');
    assert.equal(await button.getAttribute('aria-pressed'), 'true');
    await page.waitForTimeout(1300);
    await button.click();
    await page.waitForFunction(() => window.voice.calls.length === 1 && !document.querySelector('#btn-voice').disabled);
    const sent = await page.evaluate(() => {
      const {audio, language} = window.voice.calls[0];
      const bytes = Uint8Array.from(atob(audio), (c) => c.charCodeAt(0)), view = new DataView(bytes.buffer);
      const text = (at) => String.fromCharCode(...bytes.subarray(at, at + 4));
      let peak = 0;
      for (let i = 44; i + 1 < bytes.length; i += 2) peak = Math.max(peak, Math.abs(view.getInt16(i, true)));
      return {language, riff: text(0), wave: text(8), format: view.getUint16(20, true), channels: view.getUint16(22, true), rate: view.getUint32(24, true), bits: view.getUint16(34, true),
              declared: view.getUint32(40, true), actual: bytes.length - 44, peak};
    });
    assert.deepEqual([sent.riff, sent.wave, sent.format, sent.channels, sent.rate, sent.bits, sent.language], ['RIFF', 'WAVE', 1, 1, 16000, 16, 'pt']);
    assert.equal(sent.declared, sent.actual, 'o cabeçalho do WAV diz o tamanho certo');
    const seconds = sent.actual / 2 / 16000;
    assert(seconds > 0.8 && seconds < 4, 'duração plausível: ' + seconds);
    assert(sent.peak > 250, 'o microfone simulado apita: o áudio não pode ser silêncio (pico ' + sent.peak + ')');
    assert.equal(await page.inputValue('#composer'), 'Antes Cria um <b>ficheiro</b> novo.', 'o texto junta-se ao que lá estava, como texto');
    assert.equal(await page.evaluate(() => window.voice.sent), 0, 'o ditado não envia a mensagem: o utilizador revê primeiro');
    assert.equal(await button.textContent(), '🎤');
    assert.match(await page.textContent('#chat-status'), /Revê o texto antes de enviar/);

    // erro da transcrição: aparece e o botão volta ao normal
    await page.evaluate(() => { window.voice.reply = {ok: false, error: 'Não ouvi nada: confirma que o microfone está ligado.'}; });
    await button.click();
    await page.waitForFunction(() => document.querySelector('#btn-voice').classList.contains('recording'));
    await page.waitForTimeout(500);
    await button.click();
    await page.waitForSelector('#error-box:not(.hidden)');
    assert.match(await page.textContent('#error-box'), /Não ouvi nada/);
    assert.equal(await button.textContent(), '🎤');
    assert.equal(await page.inputValue('#composer'), 'Antes Cria um <b>ficheiro</b> novo.');
    assert.deepEqual(errors, []);
    console.log(`PASS: missing engine message, record/stop, WAV mono 16-bit 16 kHz (${seconds.toFixed(1)} s, peak ${sent.peak}), text inserted not sent, error path, no JS errors`);
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
