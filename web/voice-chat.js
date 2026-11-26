"use strict";
// Conversa por voz: o microfone fica aberto, a app percebe sozinha quando acabaste de falar, transcreve (Whisper local),
// envia a mensagem e lê a resposta em voz alta frase a frase (Piper local). Falar por cima interrompe a resposta:
// primeiro a voz só pára para te ouvir; se disseste alguma coisa que se perceba, a resposta em curso é cancelada e a tua
// frase segue como mensagem nova; se foi ruído (ou o eco das colunas), a resposta continua de onde ia.
// Se houver um nome definido (Configurações → Aparência → «Nome na conversa por voz»), o agente só responde quando é
// chamado por ele no início da frase («Zé, verifica isto»); o resto do que ouve é ignorado, para não se baralhar com
// outras pessoas a falar à volta. Sem nome, responde a tudo (como antes). Se só disseres o nome e fizeres uma pausa,
// fica à escuta uns segundos (Configurações → «Escuta após o nome») à espera da pergunta — a frase seguinte conta como
// pergunta sem teres de repetir o nome.
// Nada sai do PC além do texto que já ia para o modelo de chat. Tudo dentro de uma função: não acrescenta nomes globais.
(() => {
  const button = document.querySelector('#btn-voice-chat');
  const composer = document.querySelector('#composer');
  const dictation = document.querySelector('#btn-voice');
  if (!button || !composer) return;
  const RATE = 16000, FRAME = 2048;
  const QUIET_END = 0.9;      // segundos de silêncio que fecham a frase
  const MIN_SPEECH = 0.35;    // menos do que isto é um estalido, não fala
  const MAX_SPEECH = 90;
  const IDLE = 'Conversa por voz: falas e a app responde em voz alta (tudo local, o áudio não sai do PC)';
  const LABELS = {
    listening: 'À escuta… fala quando quiseres.', hearing: 'A ouvir-te…', understanding: 'A perceber o que disseste…',
    thinking: 'A pensar…', speaking: 'A falar… fala por cima para interromper.',
  };
  let mode = 'off';
  let mic = null;
  let frameSeconds = FRAME / RATE;
  let noise = 0.004, loudRun = 0, quiet = 0, spoken = 0;
  let recent = [], taken = [];
  let generation = 0;         // muda a cada interrupção: o que era da resposta anterior é deitado fora
  let pending = '', inCode = false;
  let synth = Promise.resolve(), player = Promise.resolve(), waiting = 0, current = null, turns = 0, warned = false;
  let held = false, interrupting = false, muted = false, resumers = [];
  let awakeUntil = 0;   // enquanto > agora, a próxima frase conta como pergunta mesmo sem o nome (chamaste há pouco)
  let transcribing = false, queued = null;   // uma transcrição de cada vez; a frase seguinte espera em vez de se perder

  const language = () => { try { return localStorage.getItem('voiceLanguage') || 'pt'; } catch (e) { return 'pt'; } };
  // Segundos que o agente fica à escuta depois de ser chamado pelo nome (Configurações → «Escuta após o nome»).
  const listenWindowMs = () => { const s = Number(state.preferences && state.preferences.voice_listen_seconds); return (s >= 2 ? s : 8) * 1000; };

  function paint(next) {
    mode = next;
    const on = next !== 'off';
    button.classList.toggle('active', on);
    button.classList.toggle('hearing', next === 'hearing');
    button.classList.toggle('speaking', next === 'speaking');
    button.setAttribute('aria-pressed', on ? 'true' : 'false');
    button.dataset.mode = next;
    button.title = on ? 'Terminar a conversa por voz' : IDLE;
    if (dictation) dictation.disabled = on;
    if (on) { el.status.className = 'status'; el.status.textContent = LABELS[next] || ''; }
  }

  /* ---------- falar ---------- */
  function stopSpeech() {
    generation++;
    pending = ''; inCode = false; waiting = 0; held = false;
    const sound = current;
    current = null;
    if (sound) { try { sound.pause(); } catch (e) { /* já parado */ } if (sound.finish) sound.finish(); }
    for (const go of resumers.splice(0)) go();
  }

  // Interrupção por confirmar: a voz pára onde está, sem deitar nada fora.
  function hold() {
    held = true;
    if (current) { try { current.pause(); } catch (e) { /* já parado */ } }
  }

  // Afinal não era contigo: continua a dizer de onde ia.
  function release() {
    held = false;
    for (const go of resumers.splice(0)) go();
    if (current) current.play().catch(() => {});
  }

  function play(audio, mine, mime) {
    return new Promise(async (resolve) => {
      if (held) await new Promise((go) => resumers.push(go));   // à espera de saber se foste tu a interromper
      if (mine !== generation || mode === 'off') return resolve();
      const sound = new Audio('data:' + (mime || 'audio/wav') + ';base64,' + audio);
      current = sound;
      let over = false;
      const done = () => { if (over) return; over = true; if (current === sound) current = null; resolve(); };
      sound.onended = done; sound.onerror = done; sound.finish = done;
      sound.onpause = () => { if (!(held && current === sound)) done(); };   // em pausa por interrupção: fica à espera
      if (mode === 'thinking' || mode === 'listening') paint('speaking');
      sound.play().catch(() => {
        if (!warned) { warned = true; showError('A janela não deixou tocar o som da resposta.'); }
        done();
      });
    });
  }

  // Antes de o Piper ler, normaliza para soar bem: horas (20h30 → "20 horas e 30 minutos"), unidades e símbolos.
  function forSpeech(text) {
    return text
      .replace(/(\d{1,2})\s*h\s*(\d{2})\s*m?\b/gi, "$1 horas e $2 minutos")
      .replace(/(\d{1,2})\s*h(?![\wáéíóúâêôãõ])/gi, "$1 horas")
      .replace(/(\d{1,3})\s*min\b/gi, "$1 minutos")
      .replace(/(\d{1,3})\s*%/g, "$1 por cento")
      .replace(/(\d+)\s*(?:º|°)\s*C\b/gi, "$1 graus")
      .replace(/(\d+)\s*km\/h\b/gi, "$1 quilómetros por hora")
      .replace(/(\d+)\s*km\b/gi, "$1 quilómetros")
      .replace(/(\d+)\s*kg\b/gi, "$1 quilos")
      .replace(/(\d+)\s*€/g, "$1 euros")
      .replace(/€\s*(\d+)/g, "$1 euros");
  }

  function say(text) {
    const mine = generation;
    waiting++;
    const audio = synth.then(async () => {
      if (mine !== generation || mode === 'off') return null;
      const result = await call('speak_text', forSpeech(text));
      if (!result.ok) { if (!warned) { warned = true; showError(result.error); } return null; }
      return result.audio ? { audio: result.audio, mime: result.mime || 'audio/wav' } : null;
    }).catch(() => null);
    synth = audio;
    player = player.then(async () => {
      const data = await audio;
      if (data) await play(data.audio, mine, data.mime);
      if (mine === generation) { waiting = Math.max(0, waiting - 1); settle(); }
    });
  }

  // Corta o texto que vai chegando em frases; o que está dentro de um bloco de código não se lê.
  function feed(text, flush) {
    if (mode === 'off') return;
    pending += text;
    for (;;) {
      const match = /^([\s\S]*?(?:[.!?…:;](?=\s)|\n))/.exec(pending);
      let piece;
      if (match && (match[1].trim().length >= 12 || match[1].includes('\n'))) piece = match[1];
      else if (flush && pending) piece = pending;
      else if (!flush && pending.length > 320) piece = pending.slice(0, pending.lastIndexOf(' ', 320) + 1 || 320);
      else break;
      pending = pending.slice(piece.length);
      const fences = (piece.match(/```/g) || []).length;
      const skip = inCode || fences > 0;
      if (fences % 2) inCode = !inCode;
      if (!skip && /[\p{L}\p{N}]/u.test(piece)) say(piece.trim());
    }
  }

  function settle() {
    if (mode === 'off' || mode === 'hearing' || mode === 'understanding') return;
    if (waiting > 0 || current) { if (mode !== 'speaking' && current) paint('speaking'); return; }
    paint(turns > 0 || chatBusy ? 'thinking' : 'listening');
  }

  /* ---------- ouvir ---------- */
  function wavBase64(samples) {
    const bytes = new Uint8Array(44 + samples.length * 2), view = new DataView(bytes.buffer);
    const text = (at, value) => { for (let i = 0; i < value.length; i++) bytes[at + i] = value.charCodeAt(i); };
    text(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true); view.setUint32(24, RATE, true);
    view.setUint32(28, RATE * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true); text(36, 'data'); view.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) {
      const value = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(44 + i * 2, value < 0 ? value * 32768 : value * 32767, true);
    }
    let binary = '';
    for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
    return btoa(binary);
  }

  function resample(samples, from) {
    if (from === RATE) return samples;
    const out = new Float32Array(Math.floor(samples.length * RATE / from)), step = from / RATE;
    for (let i = 0; i < out.length; i++) {
      const at = i * step, low = Math.floor(at), high = Math.min(low + 1, samples.length - 1);
      out[i] = samples[low] + (samples[high] - samples[low]) * (at - low);
    }
    return out;
  }

  function onFrame(frame) {
    if (mode === 'off') return;   // durante a transcrição (understanding) continua a ouvir, para não perder a frase a seguir ao nome
    let sum = 0;
    for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
    const level = Math.sqrt(sum / frame.length);
    // enquanto a app fala, o limiar sobe: o eco das colunas não deve contar como interrupção
    const threshold = Math.max(0.012, noise * 3.5) * (mode === 'speaking' ? 2.5 : 1);
    const loud = level > threshold;
    if (mode !== 'hearing') {
      if (!loud) noise = noise * 0.95 + level * 0.05;
      recent.push(frame);
      if (recent.length > 4) recent.shift();
      loudRun = loud ? loudRun + 1 : 0;
      const needed = mode === 'listening' ? 2 : 3;   // interromper pede um pouco mais de certeza
      if (loudRun >= needed) {
        if (mode !== 'listening' && mode !== 'understanding') { interrupting = true; hold(); }   // a falar durante uma transcrição não é interrupção, é a frase a seguir ao nome
        taken = recent.slice(); recent = []; quiet = 0; spoken = loudRun * frameSeconds; loudRun = 0;
        paint('hearing');
      }
      return;
    }
    taken.push(frame);
    if (loud) { quiet = 0; spoken += frameSeconds; } else quiet += frameSeconds;
    if (quiet >= QUIET_END || taken.length * frameSeconds >= MAX_SPEECH) finishUtterance();
  }

  // O que se ouviu não era uma frase: se a app estava a responder, continua; senão volta a escutar.
  function carryOn() {
    if (interrupting) { interrupting = false; release(); }
    paint(current || waiting > 0 ? 'speaking' : chatBusy || turns > 0 ? 'thinking' : 'listening');
  }

  // Tira acentos e pontuação para comparar o que se ouviu com o nome, à prova dos tremidos da transcrição.
  const bare = (word) => word.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");
  // Decide o que fazer com o que se ouviu: {send} para enviar como mensagem, {wait} para abrir a janela de escuta
  // (chamaste só pelo nome), ou null para ignorar (não é contigo).
  function addressed(text) {
    const name = ((state.preferences && state.preferences.agent_name) || "").trim();
    if (!name) return { send: text };
    const wanted = name.split(/\s+/).map(bare).filter(Boolean);
    if (!wanted.length) return { send: text };
    const tokens = text.trim().split(/\s+/), low = tokens.map(bare);
    for (let start = 0; start < Math.min(2, tokens.length); start++) {
      if (wanted.every((w, k) => low[start + k] === w)) {
        const rest = tokens.slice(start + wanted.length).join(" ").replace(/^[\s,.:;!?…-]+/, "").trim();
        if (rest) return { send: rest };            // nome e pergunta na mesma frase
        awakeUntil = Date.now() + listenWindowMs();  // só disseste o nome: fica à escuta da pergunta
        return { wait: true };
      }
    }
    if (awakeUntil > 0 && Date.now() < awakeUntil) return { send: text };   // chamaste pelo nome há pouco e isto está dentro da janela de escuta
    return null;
  }

  // Uma transcrição de cada vez (o servidor não aceita duas). A frase ouvida enquanto outra transcreve fica em «queued» e
  // transcreve-se logo a seguir — assim a pergunta dita depois do nome não se perde no tempo da transcrição. O tratamento
  // (responder/interromper) corre à parte, para não travar a interrupção da resposta.
  async function finishUtterance(preset) {
    let frames, said;
    if (preset) { frames = preset; said = Infinity; }
    else { frames = taken; said = spoken; taken = []; spoken = 0; quiet = 0; }
    if (said < MIN_SPEECH) { if (!transcribing) carryOn(); return; }
    if (transcribing) { queued = frames; return; }
    transcribing = true;
    paint('understanding');
    const all = new Float32Array(frames.reduce((sum, frame) => sum + frame.length, 0));
    let at = 0;
    for (const frame of frames) { all.set(frame, at); at += frame.length; }
    let result;
    try { result = await call('transcribe_voice', wavBase64(resample(all, mic ? mic.context.sampleRate : RATE)), language(), true); }
    catch (error) { result = { ok: false, error: String(error && error.message || error) }; }
    transcribing = false;
    if (queued && mode !== 'off') { const next = queued; queued = null; finishUtterance(next); }   // a frase ouvida durante a transcrição trata-se já
    if (mode === 'off') return;
    if (!result.ok || !result.text) {
      // ruído ou fala que não se percebeu: volta a escutar sem incomodar (os erros a sério mostram-se)
      if (!result.ok && !/Não percebi|Não ouvi|demasiado curta|Já há uma transcrição/.test(result.error || '')) showError(result.error);
      return carryOn();
    }
    // Só se há um nome definido e foste tu a chamar por ele (ou dentro da janela de escuta): senão, ignora-se.
    const decided = addressed(result.text);
    if (!decided) return carryOn();
    if (decided.wait) {   // chamaste só pelo nome: cala-se se estava a falar e fica à escuta da pergunta
      if (interrupting) {
        interrupting = false; muted = true;
        stopSpeech();
        if (chatBusy && el.btnStop) el.btnStop.click();
        for (let i = 0; chatBusy && i < 150; i++) await new Promise((resolve) => setTimeout(resolve, 100));
        muted = false;
      }
      if (mode === 'off') return;
      paint('listening');
      el.status.textContent = 'Sim? Diz a tua pergunta…';
      return;
    }
    const command = decided.send;
    awakeUntil = 0;   // janela de escuta consumida (se estava aberta)
    if (interrupting) {   // interrompeste mesmo: cala-se, cancela o que estava a gerar e responde ao que disseste
      interrupting = false; muted = true;
      stopSpeech();
      if (chatBusy && el.btnStop) el.btnStop.click();
    }
    for (let i = 0; chatBusy && i < 150; i++) await new Promise((resolve) => setTimeout(resolve, 100));  // a resposta interrompida ainda a fechar
    if (mode === 'off') return;
    if (chatBusy) { muted = false; showError('A resposta anterior ainda não parou; repete quando terminar.'); return paint('thinking'); }
    muted = false;
    composer.value = (composer.value.trim() ? composer.value.trim() + ' ' : '') + command;
    // confirma logo, de forma natural e sem repetir o pedido à letra (útil quando estás longe do PC); varia para não soar a robô
    const ACKS = ['Ok, deixa-me ver e já te digo.', 'Certo, vou já tratar disso.', 'Ok, um instante e já te digo.', 'Deixa ver isso, já te digo.', 'Certo, já vejo isso e digo-te.'];
    say(ACKS[Math.floor(Math.random() * ACKS.length)]);
    turns++;
    paint('thinking');
    try { await send(); } finally { turns--; feed('', true); settle(); }
  }

  // Arranque a frio: um disparo curto e silencioso ao Whisper deixa-o quente, para a 1.ª transcrição real não falhar.
  async function warmWhisper() {
    if (transcribing || mode === 'off' || !mic) return;
    transcribing = true;
    try { await call('transcribe_voice', wavBase64(new Float32Array(Math.round(RATE * 0.4))), language(), true); } catch (e) { /* ignora */ }
    transcribing = false;
    if (queued) { const q = queued; queued = null; finishUtterance(q); }
  }

  /* ---------- ligar e desligar ---------- */
  async function start() {
    const status = await call('get_voice_input');
    if (!status.ok) throw new Error(status.error);
    if (!status.ready) throw new Error(status.reason);
    if (!status.speech || !status.speech.ready) throw new Error((status.speech && status.speech.reason) || 'Falta a voz (Piper).');
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('Esta janela não tem acesso ao microfone.');
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (error) {
      throw new Error(error && error.name === 'NotFoundError' ? 'Não encontrei nenhum microfone.'
        : 'Sem acesso ao microfone: autoriza-o quando a app perguntar e confirma, nas definições de privacidade do Windows, que as aplicações podem usar o microfone.');
    }
    const Context = window.AudioContext || window.webkitAudioContext;
    let context;
    try { context = new Context({ sampleRate: RATE }); } catch (e) { context = new Context(); }
    const source = context.createMediaStreamSource(stream), node = context.createScriptProcessor(FRAME, 1, 1), mute = context.createGain();
    mute.gain.value = 0;
    frameSeconds = FRAME / context.sampleRate;
    node.onaudioprocess = (event) => onFrame(new Float32Array(event.inputBuffer.getChannelData(0)));
    source.connect(node); node.connect(mute); mute.connect(context.destination);
    mic = { stream, context, node, source };
    noise = 0.004; loudRun = 0; recent = []; taken = []; warned = false; interrupting = false; muted = false; awakeUntil = 0; transcribing = false; queued = null;
    call('set_preference', 'voice_reply', true);   // o modelo passa a responder curto e sem formatação
    paint('listening');
    warmWhisper();   // aquece já o Whisper para a 1.ª pergunta não falhar
    mic.warmTimer = setInterval(() => { if (mode !== 'off') warmWhisper(); }, 90000);   // mantém-no quente enquanto está parado
  }

  async function stop() {
    const opened = mic;
    mic = null;
    if (opened && opened.warmTimer) clearInterval(opened.warmTimer);
    const was = mode;
    stopSpeech();
    paint('off');
    el.status.textContent = '';
    if (was !== 'off') call('set_preference', 'voice_reply', false);
    if (!opened) return;
    opened.node.onaudioprocess = null;
    opened.stream.getTracks().forEach((track) => track.stop());
    try { opened.source.disconnect(); opened.node.disconnect(); await opened.context.close(); } catch (e) { /* já fechado */ }
  }

  let switching = false;
  button.onclick = async () => {
    if (switching) return;
    switching = true;
    try {
      if (mode === 'off') await start(); else await stop();
    } catch (error) {
      await stop();
      showError(error.message);
    } finally { switching = false; }
  };

  // Voz e tom (Configurações → Aparência): guarda a escolha e diz uma frase para se ouvir a diferença.
  const tone = document.querySelector('#voice-tone-select'), picker = document.querySelector('#voice-name-select');
  async function sampleVoice() {
    const sample = await call('speak_text', 'Esta é a voz que vais ouvir na conversa.');
    if (!sample.ok) return showError(sample.error);
    if (sample.audio) new Audio('data:' + (sample.mime || 'audio/wav') + ';base64,' + sample.audio).play().catch(() => {});
  }
  async function choose(key, value) {
    const saved = await call('set_preference', key, value);
    if (!saved.ok) return showError(saved.error);
    applyState(saved);
    sampleVoice();
  }
  // O seletor junta as vozes Piper (locais) e as do Edge (naturais, mas online): a escolha define o motor da voz.
  async function chooseVoice(value) {
    let r;
    if (value.indexOf('edge:') === 0) { r = await call('set_preference', 'voice_engine', 'edge'); if (r.ok) r = await call('set_preference', 'edge_voice', value.slice(5)); }
    else { r = await call('set_preference', 'voice_engine', 'piper'); if (r.ok) r = await call('set_preference', 'voice_name', value); }
    if (!r.ok) return showError(r.error);
    applyState(r);
    sampleVoice();
  }
  if (tone) tone.onchange = () => choose('voice_tone', tone.value);
  if (picker) picker.onchange = () => chooseVoice(picker.value);
  // a lista de vozes vem do que está instalado; atualiza-se ao abrir as Configurações
  async function listVoices() {
    if (!picker) return;
    const status = await call('get_voice_input');
    const voices = (status.ok && status.speech && status.speech.voices) || [];
    picker.replaceChildren(...(voices.length ? voices : ['']).map((name) => new Option(name ? name.replace(/^pt_PT-/, '').replace(/-medium$|-low$|-high$/, '') + (name.startsWith('pt_PT') ? ' (Portugal)' : '') : '(por instalar)', name)));
    picker.add(new Option('🌐 Raquel — natural, online (vai à Microsoft)', 'edge:pt-PT-RaquelNeural'));
    picker.add(new Option('🌐 Duarte — natural, online (vai à Microsoft)', 'edge:pt-PT-DuarteNeural'));
    const prefs = state.preferences || {};
    if (prefs.voice_engine === 'edge') picker.value = 'edge:' + (prefs.edge_voice || 'pt-PT-RaquelNeural');
    else picker.value = (status.ok && status.speech && status.speech.voice) || '';
    picker.disabled = false;
  }
  const settings = document.querySelector('#btn-settings');
  if (settings) settings.addEventListener('click', () => { listVoices().catch(() => {}); });

  // A resposta chega aos bocados por estas funções da interface; ouve-se à passagem, sem as alterar.
  const append = window.appendStream, end = window.endStream;
  // (enquanto te ouve, o texto continua a entrar na fila — a voz é que está em pausa; depois de uma interrupção
  // confirmada, o que ainda chegar da resposta cancelada não se diz)
  window.appendStream = function (text) { append.apply(this, arguments); if (mode !== 'off' && !muted) feed(String(text || ''), false); };
  window.endStream = function () { end.apply(this, arguments); if (mode !== 'off' && !muted) feed('', true); };

  paint('off');
})();
