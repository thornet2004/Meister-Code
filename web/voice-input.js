"use strict";
// Ditado por voz: grava o microfone, envia um WAV (mono, 16 bits, 16 kHz) pela ponte e põe o texto
// transcrito na caixa de mensagem, para o utilizador rever antes de enviar. A transcrição é local (Whisper).
// Tudo dentro de uma função: não acrescenta nomes globais.
(() => {
  const button = document.querySelector('#btn-voice');
  const composer = document.querySelector('#composer');
  if (!button || !composer) return;
  const RATE = 16000;
  const IDLE = 'Ditar por voz (transcrição local, o áudio não sai do PC)';
  let session = null;   // gravação em curso
  let busy = false;     // a transcrever
  let limit = 300;

  const paint = (state) => {
    button.classList.toggle('recording', state === 'recording');
    button.classList.toggle('working', state === 'working');
    button.disabled = state === 'working';
    button.textContent = state === 'recording' ? '■' : state === 'working' ? '…' : '🎤';
    button.title = state === 'recording' ? 'Parar e transcrever' : state === 'working' ? 'A transcrever…' : IDLE;
    button.setAttribute('aria-pressed', state === 'recording' ? 'true' : 'false');
  };

  const language = () => { try { return localStorage.getItem('voiceLanguage') || 'pt'; } catch (e) { return 'pt'; } };

  function resample(samples, from) {
    if (from === RATE) return samples;
    const out = new Float32Array(Math.floor(samples.length * RATE / from));
    const step = from / RATE;
    for (let i = 0; i < out.length; i++) {
      const at = i * step, low = Math.floor(at), high = Math.min(low + 1, samples.length - 1);
      out[i] = samples[low] + (samples[high] - samples[low]) * (at - low);
    }
    return out;
  }

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

  function insert(text) {
    const start = composer.selectionStart ?? composer.value.length, end = composer.selectionEnd ?? start;
    const before = composer.value.slice(0, start), after = composer.value.slice(end);
    const piece = (before && !/\s$/.test(before) ? ' ' : '') + text + (after && !/^\s/.test(after) ? ' ' : '');
    composer.value = before + piece + after;
    composer.selectionStart = composer.selectionEnd = (before + piece).length;
    composer.dispatchEvent(new Event('input', { bubbles: true }));
    composer.focus();
  }

  async function start() {
    const status = await call('get_voice_input');
    if (!status.ok) throw new Error(status.error);
    if (!status.ready) throw new Error(status.reason);
    limit = status.max_seconds || limit;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('Esta janela não tem acesso ao microfone.');
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    } catch (error) {
      throw new Error(error && error.name === 'NotFoundError' ? 'Não encontrei nenhum microfone.'
        : 'Sem acesso ao microfone: autoriza-o quando a app perguntar e confirma, nas definições de privacidade do Windows, que as aplicações podem usar o microfone.');
    }
    const Context = window.AudioContext || window.webkitAudioContext;
    let context;
    try { context = new Context({ sampleRate: RATE }); } catch (e) { context = new Context(); }
    const source = context.createMediaStreamSource(stream), node = context.createScriptProcessor(4096, 1, 1), mute = context.createGain();
    mute.gain.value = 0;  // o nó tem de estar ligado à saída para correr, mas não se quer ouvir o próprio microfone
    const chunks = [];
    node.onaudioprocess = (event) => { if (session) chunks.push(new Float32Array(event.inputBuffer.getChannelData(0))); };
    source.connect(node); node.connect(mute); mute.connect(context.destination);
    session = { stream, context, node, source, chunks, timer: setTimeout(() => { if (session) toggle(); }, limit * 1000) };
    paint('recording');
    setStatusMessage('A gravar… carrega outra vez no microfone para parar.');
  }

  async function finish() {
    const current = session;
    session = null;
    clearTimeout(current.timer);
    current.node.onaudioprocess = null;
    current.stream.getTracks().forEach((track) => track.stop());
    const rate = current.context.sampleRate;
    try { current.source.disconnect(); current.node.disconnect(); await current.context.close(); } catch (e) { /* já fechado */ }
    const total = current.chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    if (!total) throw new Error('Não foi gravado áudio nenhum.');
    const all = new Float32Array(total);
    let at = 0;
    for (const chunk of current.chunks) { all.set(chunk, at); at += chunk.length; }
    busy = true;
    paint('working');
    setStatusMessage('A transcrever no teu PC…');
    const result = await call('transcribe_voice', wavBase64(resample(all, rate)), language());
    if (!result.ok) throw new Error(result.error);
    insert(result.text);
    setStatusMessage(`Ditado: ${result.duration} s de áudio transcritos em ${result.seconds} s. Revê o texto antes de enviar.`);
  }

  async function toggle() {
    if (busy) return;
    try {
      if (session) await finish(); else await start();
    } catch (error) {
      if (session) { session.stream.getTracks().forEach((track) => track.stop()); clearTimeout(session.timer); try { await session.context.close(); } catch (e) { /* já fechado */ } session = null; }
      setStatusMessage('');
      showError(error.message);
    } finally {
      busy = false;
      paint(session ? 'recording' : 'idle');
    }
  }

  button.onclick = toggle;
  paint('idle');
})();
