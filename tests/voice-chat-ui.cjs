// Conversa por voz: com um microfone simulado (um tom que o ensaio liga e desliga), a app percebe sozinha o fim da fala,
// transcreve em modo rápido, envia a mensagem sem carregar em nada e manda dizer a resposta frase a frase, sem ler código.
// A ponte é simulada: nem o Whisper nem o Piper verdadeiros correm aqui.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict'), path = require('node:path'), {pathToFileURL} = require('node:url');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required']});
  try {
    const context = await browser.newContext({viewport: {width: 1300, height: 900}});
    const page = await context.newPage(), errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.addInitScript(() => {
      // WAV mínimo e válido (0,05 s de silêncio a 8 kHz) para a resposta falada
      const quiet = (n) => {
        const bytes = new Uint8Array(44 + n * 2), view = new DataView(bytes.buffer), text = (at, v) => { for (let i = 0; i < v.length; i++) bytes[at + i] = v.charCodeAt(i); };
        text(0, 'RIFF'); view.setUint32(4, 36 + n * 2, true); text(8, 'WAVE'); text(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
        view.setUint32(24, 8000, true); view.setUint32(28, 16000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true); text(36, 'data'); view.setUint32(40, n * 2, true);
        let binary = '';
        for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
        return btoa(binary);
      };
      const silence = quiet(400), long = quiet(8000);   // 0,05 s e 1 s
      window.voice = {chosen: 'pt_PT-miro-medium', speech: false, heard: [], chats: [], said: [], prefs: [], cancelled: 0, tone: null, slow: false, replies: []};
      // microfone de ensaio: um tom com volume comandado pelo ensaio (o do browser apita sem parar e a fala nunca acabaria)
      navigator.mediaDevices.getUserMedia = async () => {
        const audio = new AudioContext(), source = audio.createOscillator(), volume = audio.createGain(), out = audio.createMediaStreamDestination();
        volume.gain.value = 0; source.frequency.value = 300; source.connect(volume); volume.connect(out); source.start();
        window.voice.tone = volume.gain;
        return out.stream;
      };
      window.pywebview = {api: {
        get_state: async () => ({ok: true, providers: [], projects: [], conversations: []}),
        get_conversation: async () => ({ok: true, messages: []}),
        get_context_usage: async () => ({ok: true, used: 0, limit: 128000, percent: 0, parts: {}, total_messages: 0, older: 0, history_window: 40}),
        get_voice_input: async () => ({ok: true, ready: true, reason: '', model: 'ggml-small-q5_1.bin', max_seconds: 300, sample_rate: 16000,
          speech: window.voice.speech ? {ready: true, reason: '', voice: window.voice.chosen, voices: ['pt_PT-miro-medium', 'pt_PT-tugao-medium']} : {ready: false, reason: 'Falta a voz: instala «Piper (texto para voz, local)» em Ferramentas.'}}),
        set_preference: async (key, value) => { window.voice.prefs.push([key, value]); if (key === 'voice_name') window.voice.chosen = value; return {ok: true, providers: [], projects: [], conversations: [], preferences: {voice_name: window.voice.chosen}}; },
        transcribe_voice: async (audio, language, fast) => { window.voice.heard.push({size: audio.length, language, fast}); return window.voice.replies.shift() || {ok: true, text: 'Que horas são?', duration: 1, seconds: 0.2}; },
        chat: async (text) => {
          window.voice.chats.push(text);
          window.startStream();
          if (window.voice.slow) {   // resposta comprida, que pára quando é cancelada
            const turn = window.voice.chats.length, cancelled = window.voice.cancelled;
            for (let k = 1; k <= 5 && window.voice.cancelled === cancelled; k++) { window.appendStream('Resposta ' + turn + ' frase ' + k + '. '); await new Promise((r) => setTimeout(r, 450)); }
            window.endStream();
            return {ok: true};
          }
          for (const piece of ['São três da tar', 'de. Queres que eu veja mais alguma coisa?\n```js\nconsole.log(1)\n```\nDiz', '-me quando quiseres']) { window.appendStream(piece); await new Promise((r) => setTimeout(r, 30)); }
          window.endStream();
          return {ok: true};
        },
        speak_text: async (text) => { window.voice.said.push(text); return {ok: true, audio: window.voice.slow ? long : silence, text, seconds: 0.1, voice: 'pt_PT-tugao-medium'}; },
        cancel_chat: async () => { window.voice.cancelled++; return {ok: true}; },
      }};
    });
    await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
    await page.waitForFunction(() => document.querySelector('#context-label').textContent !== '—');
    const button = page.locator('#btn-voice-chat');
    assert.match(await button.getAttribute('title'), /Conversa por voz/);

    // sem a voz instalada: diz o que falta e não liga o microfone
    await button.click();
    await page.waitForSelector('#error-box:not(.hidden)');
    assert.match(await page.textContent('#error-box'), /Falta a voz/);
    assert.equal(await button.getAttribute('aria-pressed'), 'false');
    await page.evaluate(() => { document.querySelector('#error-box').classList.add('hidden'); window.voice.speech = true; });

    // ligada: escuta; um segundo de «fala» seguido de silêncio conta como uma frase que acaba sozinha
    await button.click();
    await page.waitForFunction(() => document.querySelector('#btn-voice-chat').getAttribute('aria-pressed') === 'true');
    assert.equal(await page.locator('#btn-voice').isDisabled(), true, 'o ditado fica desligado durante a conversa');
    assert.deepEqual(await page.evaluate(() => window.voice.prefs[0]), ['voice_reply', true]);
    assert.equal(await button.getAttribute('data-mode'), 'listening');
    await page.waitForTimeout(600);
    assert.equal(await page.evaluate(() => window.voice.heard.length), 0, 'em silêncio não transcreve nada');
    await page.evaluate(() => { window.voice.tone.value = 0.5; });
    await page.waitForFunction(() => document.querySelector('#btn-voice-chat').dataset.mode === 'hearing');
    await page.waitForTimeout(900);
    assert.equal(await page.evaluate(() => window.voice.heard.length), 0, 'enquanto falas não corta a frase');
    await page.evaluate(() => { window.voice.tone.value = 0; });
    await page.waitForFunction(() => window.voice.chats.length >= 1, null, {timeout: 20000});
    const heard = await page.evaluate(() => window.voice.heard[0]);
    assert.equal(heard.fast, true, 'a conversa usa a transcrição rápida');
    assert.equal(heard.language, 'pt');
    assert.ok(heard.size > 2000, 'chegou áudio');
    assert.equal(await page.evaluate(() => window.voice.chats[0]), 'Que horas são?', 'a frase é enviada sem carregar em nada');

    // confirma logo e repete o pedido, e a seguir a resposta é dita frase a frase, pela ordem, sem ler o bloco de código
    await page.waitForFunction(() => window.voice.said.length >= 4, null, {timeout: 20000});
    const said = await page.evaluate(() => window.voice.said.slice(0, 4));
    assert.deepEqual(said, ['Percebido. Que horas são?', 'São três da tarde.', 'Queres que eu veja mais alguma coisa?', 'Diz-me quando quiseres']);

    // --- falar por cima da resposta ---
    const mode = () => page.evaluate(() => document.querySelector('#btn-voice-chat').dataset.mode);
    const speak = async (ms) => { await page.evaluate(() => { window.voice.tone.value = 0.5; }); await page.waitForTimeout(ms); await page.evaluate(() => { window.voice.tone.value = 0; }); };
    await page.waitForFunction(() => document.querySelector('#btn-voice-chat').dataset.mode === 'listening', null, {timeout: 20000});
    await page.evaluate(() => { window.voice.slow = true; });

    // 1) ruído por cima (não se percebe frase nenhuma): a voz pára para ouvir e depois continua; nada é cancelado
    await page.evaluate(() => { window.voice.replies = [{ok: true, text: 'Conta-me uma história.'}, {ok: false, error: 'Não percebi fala nenhuma na gravação.'}]; });
    let turn = await page.evaluate(() => window.voice.chats.length) + 1;
    await speak(900);
    await page.waitForFunction((n) => window.voice.chats.length === n, turn, {timeout: 20000});
    await page.waitForFunction(() => document.querySelector('#btn-voice-chat').dataset.mode === 'speaking', null, {timeout: 20000});
    await speak(700);
    await page.waitForFunction(() => document.querySelector('#btn-voice-chat').dataset.mode === 'speaking' && window.voice.heard.length >= 3, null, {timeout: 20000});
    assert.equal(await page.evaluate(() => window.voice.cancelled), 0, 'ruído não cancela a resposta');
    assert.equal(await page.evaluate(() => window.voice.chats.length), turn, 'nem envia mensagem nenhuma');
    await page.waitForFunction((n) => window.voice.said.filter((text) => text.startsWith('Resposta ' + n + ' ')).length === 5, turn, {timeout: 20000});
    await page.waitForFunction(() => document.querySelector('#btn-voice-chat').dataset.mode === 'listening', null, {timeout: 30000});

    // 2) interrupção a sério (percebe-se a frase): cala-se, cancela o que estava a gerar e responde ao que foi dito
    await page.evaluate(() => { window.voice.replies = [{ok: true, text: 'Outra história.'}, {ok: true, text: 'Espera, muda de assunto.'}]; });
    turn = await page.evaluate(() => window.voice.chats.length) + 1;
    await speak(900);
    await page.waitForFunction((n) => window.voice.chats.length === n, turn, {timeout: 20000});
    await page.waitForFunction(() => document.querySelector('#btn-voice-chat').dataset.mode === 'speaking', null, {timeout: 20000});
    await speak(700);
    await page.waitForFunction((n) => window.voice.chats.length === n + 1, turn, {timeout: 20000});
    assert.equal(await page.evaluate(() => window.voice.chats.at(-1)), 'Espera, muda de assunto.', 'a tua frase segue como mensagem nova');
    assert.equal(await page.evaluate(() => window.voice.cancelled), 1, 'a resposta que estava a ser gerada foi cancelada');
    assert.ok(await page.evaluate((n) => window.voice.said.filter((text) => text.startsWith('Resposta ' + n + ' ')).length, turn) < 5, 'a resposta interrompida não é lida até ao fim');
    await page.waitForFunction((n) => window.voice.said.filter((text) => text.startsWith('Resposta ' + (n + 1) + ' ')).length === 5, turn, {timeout: 20000});
    await page.waitForFunction(() => document.querySelector('#btn-voice-chat').dataset.mode === 'listening', null, {timeout: 30000});
    assert.equal(await mode(), 'listening');
    await page.evaluate(() => { window.voice.slow = false; });

    // --- só responde quando é chamado pelo nome (Configurações → «Nome na conversa por voz») ---
    await page.evaluate(() => { state.preferences = Object.assign(state.preferences || {}, { agent_name: 'Zé' }); });
    // alguém a falar à volta, sem o nome: ouve-se, mas não se envia nada
    await page.evaluate(() => { window.voice.replies = [{ ok: true, text: 'o jantar está pronto' }]; });
    let kept = await page.evaluate(() => window.voice.chats.length);
    let heardBefore = await page.evaluate(() => window.voice.heard.length);
    await speak(900);
    await page.waitForFunction((n) => window.voice.heard.length > n, heardBefore, { timeout: 20000 });
    await page.waitForFunction(() => document.querySelector('#btn-voice-chat').dataset.mode === 'listening', null, { timeout: 20000 });
    assert.equal(await page.evaluate(() => window.voice.chats.length), kept, 'sem o nome, o que se ouve é ignorado');
    // chamado pelo nome (sem acento nem vírgula): responde, e a mensagem vai sem o nome
    await page.evaluate(() => { window.voice.replies = [{ ok: true, text: 'ze que horas sao' }]; });
    kept = await page.evaluate(() => window.voice.chats.length);
    await speak(900);
    await page.waitForFunction((n) => window.voice.chats.length === n + 1, kept, { timeout: 20000 });
    assert.equal(await page.evaluate(() => window.voice.chats.at(-1)), 'que horas sao', 'o nome é tirado antes de enviar');
    await page.waitForFunction(() => document.querySelector('#btn-voice-chat').dataset.mode === 'listening', null, { timeout: 20000 });
    // chamado só pelo nome e com pausa: fica à escuta e a frase seguinte (já sem o nome) conta como pergunta
    await page.evaluate(() => { state.preferences.voice_listen_seconds = 8; window.voice.replies = [{ ok: true, text: 'ze' }, { ok: true, text: 'estou a ouvir musica' }]; });
    kept = await page.evaluate(() => window.voice.chats.length);
    heardBefore = await page.evaluate(() => window.voice.heard.length);
    await speak(900);   // só «Zé»
    await page.waitForFunction((n) => window.voice.heard.length > n, heardBefore, { timeout: 20000 });
    await page.waitForFunction(() => document.querySelector('#chat-status').textContent.includes('Diz a tua pergunta'), null, { timeout: 20000 });
    assert.equal(await page.evaluate(() => window.voice.chats.length), kept, 'só o nome não envia nada; fica à escuta');
    await speak(900);   // a pergunta, sem repetir o nome
    await page.waitForFunction((n) => window.voice.chats.length === n + 1, kept, { timeout: 20000 });
    assert.equal(await page.evaluate(() => window.voice.chats.at(-1)), 'estou a ouvir musica', 'dentro da janela de escuta, a pergunta é enviada sem o nome');
    await page.waitForFunction(() => document.querySelector('#btn-voice-chat').dataset.mode === 'listening', null, { timeout: 20000 });
    await page.evaluate(() => { state.preferences.agent_name = ''; });

    // desligar: liberta o microfone e o modelo deixa de estar em modo voz
    await button.click();
    await page.waitForFunction(() => document.querySelector('#btn-voice-chat').getAttribute('aria-pressed') === 'false');
    assert.equal(await page.locator('#btn-voice').isDisabled(), false);
    assert.deepEqual(await page.evaluate(() => window.voice.prefs.at(-1)), ['voice_reply', false]);
    const chats = await page.evaluate(() => window.voice.chats.length);
    await page.evaluate(() => { window.voice.tone.value = 0.5; });
    await page.waitForTimeout(2000);
    assert.equal(await page.evaluate(() => window.voice.chats.length), chats, 'desligada, não envia mais nada');
    // Configurações: escolher a voz entre as instaladas diz uma frase de exemplo com a voz nova
    await page.click('#btn-settings');
    await page.waitForFunction(() => document.querySelectorAll('#voice-name-select option').length === 2);
    assert.deepEqual(await page.locator('#voice-name-select option').allTextContents(), ['miro (Portugal)', 'tugao (Portugal)']);
    assert.equal(await page.inputValue('#voice-name-select'), 'pt_PT-miro-medium');
    const before = await page.evaluate(() => window.voice.said.length);
    await page.selectOption('#voice-name-select', 'pt_PT-tugao-medium');
    await page.waitForFunction((count) => window.voice.said.length > count, before);
    assert.deepEqual(await page.evaluate(() => window.voice.prefs.at(-1)), ['voice_name', 'pt_PT-tugao-medium']);
    assert.match(await page.evaluate(() => window.voice.said.at(-1)), /Esta é a voz/);
    await page.selectOption('#voice-tone-select', 'profunda');
    await page.waitForFunction(() => window.voice.prefs.at(-1)[0] === 'voice_tone');
    assert.deepEqual(errors, []);
    console.log('PASS: voice chat — missing voice, hands-free turn, fast transcription, sentence-by-sentence speech without code, noise does not cancel the answer, a real interruption cancels and answers, wake word, listening window after the name, stop, voice and tone pickers');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
