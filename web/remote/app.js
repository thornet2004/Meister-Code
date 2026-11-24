"use strict";
// Página do acesso remoto (telemóvel). Fala só com o servidor da app, na mesma origem.
// Todo o texto que vem do servidor é posto com textContent: nunca como HTML.
(() => {
  const $ = (id) => document.getElementById(id);
  const messages = $('messages'), text = $('text'), status = $('status');
  let last = 0, busy = false, streamEl = null, state = null, approvalId = '', stopped = false, polling = false;

  async function api(path, body) {
    const options = body === undefined ? { credentials: 'same-origin' }
      : { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-MeisterCode': '1' }, body: JSON.stringify(body) };
    let response;
    try { response = await fetch(path, options); } catch (error) { throw new Error('Sem ligação ao PC.'); }
    let data = null;
    try { data = await response.json(); } catch (error) { data = null; }
    if (response.status === 401) { showPair(); throw new Error('Emparelha este dispositivo.'); }
    if (response.status === 503) { stopped = true; throw new Error('O acesso remoto foi desligado no PC.'); }
    if (!data) throw new Error('Resposta inesperada do PC.');
    if (!data.ok) throw new Error(data.error || 'Falhou.');
    return data;
  }

  const say = (message, bad) => { status.textContent = message || ''; status.classList.toggle('bad', !!bad); };
  const atBottom = () => messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80;
  const toBottom = () => { messages.scrollTop = messages.scrollHeight; };

  function bubble(message) {
    const node = document.createElement('div');
    node.className = 'msg ' + (message.role === 'user' ? 'user' : 'assistant') + (message.error ? ' error' : '');
    node.textContent = message.text || '';
    const extras = [...(message.media || []).map((kind) => '[' + kind + ' gerado: vê no PC]'), ...(message.files || []).filter(Boolean).map((name) => '[anexo: ' + name + ']')];
    if (extras.length) node.append(document.createTextNode((message.text ? '\n' : '') + extras.join('\n')));
    if ((message.steps || []).length) {
      const steps = document.createElement('div');
      steps.className = 'steps';
      for (const step of message.steps) {
        const line = document.createElement('div');
        line.textContent = (step.ok ? '✓ ' : '✕ ') + step.title;
        if (!step.ok) line.className = 'bad';
        steps.append(line);
      }
      node.append(steps);
    }
    return node;
  }

  function setBusy(value) {
    busy = value;
    $('send').classList.toggle('hidden', busy);
    $('stop').classList.toggle('hidden', !busy);
    $('context').disabled = busy;
    $('new').disabled = busy;
  }

  function renderContext() {
    const select = $('context');
    select.replaceChildren();
    const group = (label, rows, prefix, name, active) => {
      if (!rows.length) return;
      const box = document.createElement('optgroup');
      box.label = label;
      for (const row of rows) {
        const option = document.createElement('option');
        option.value = prefix + ':' + row.id;
        option.textContent = row[name] || row.id;
        option.selected = row.id === active;
        box.append(option);
      }
      select.append(box);
    };
    group('Projetos', state.projects || [], 'project', 'name', state.active_project_id);
    group('Conversas', state.conversations || [], 'conversation', 'title', state.active_project_id ? '' : state.active_conversation_id);
  }

  async function loadConversation() {
    const data = await api('/api/conversation');
    messages.replaceChildren();
    streamEl = null;
    if (!data.messages.length) { const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = 'Conversa vazia.'; messages.append(empty); }
    for (const message of data.messages) messages.append(bubble(message));
    toBottom();
  }

  function appendStream(piece) {
    const stick = atBottom();
    if (!streamEl) { streamEl = bubble({ role: 'assistant', text: '' }); messages.querySelector('.empty')?.remove(); messages.append(streamEl); }
    streamEl.textContent += piece;
    if (stick) toBottom();
  }

  function showApproval(request) {
    approvalId = request ? request.id : '';
    $('approval').classList.toggle('hidden', !request);
    if (!request) return;
    $('approval-summary').textContent = request.summary || 'Ação do agente';
    $('approval-category').textContent = { dangerous: 'perigoso', command: 'comando', write: 'escrita', instalar: 'instalar ferramenta' }[request.category] || request.category || '';
    $('approval-detail').textContent = request.detail || '';
  }

  async function loadAll() {
    state = await api('/api/state');
    last = state.last || 0;
    renderContext();
    setBusy(!!state.busy);
    await loadConversation();
    if (state.stream) appendStream(state.stream);
    showApproval(state.approval);
    say(state.busy ? 'A responder…' : '');
  }

  async function handle(event) {
    if (event.kind === 'stream_start') { streamEl = null; say('A responder…'); }
    else if (event.kind === 'stream') appendStream(event.data || '');
    else if (event.kind === 'stream_end') { /* a mensagem completa chega com «done» */ }
    else if (event.kind === 'busy') { setBusy(true); say('A responder…'); }
    else if (event.kind === 'done') { setBusy(false); await loadConversation(); say(event.data ? 'Falhou: ' + event.data : '', !!event.data); }
    else if (event.kind === 'changed') await loadAll();
    else if (event.kind === 'approval') showApproval(event.data);
    else if (event.kind === 'approval_done') { if (event.data === approvalId) showApproval(null); }
    else if (event.kind === 'stopped') { stopped = true; say('O acesso remoto foi desligado no PC.', true); }
  }

  async function poll() {
    if (polling) return;
    polling = true;
    while (!stopped) {
      try {
        const data = await api('/api/events?after=' + last);
        if (data.reload) { await loadAll(); continue; }
        for (const event of data.events) { last = event.seq; await handle(event); }
        last = Math.max(last, data.last || 0);
      } catch (error) {
        if (!$('pair').classList.contains('hidden')) break;  // à espera do código; recomeça depois de emparelhar
        say(error.message, true);
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
    }
    polling = false;
  }

  function showPair() {
    $('pair').classList.remove('hidden');
    $('code').focus();
  }

  async function start() {
    try { await loadAll(); } catch (error) { if ($('pair').classList.contains('hidden')) say(error.message, true); return; }
    poll();
  }

  async function act(run) {
    try { await run(); } catch (error) { say(error.message, true); }
  }

  $('pair-ok').onclick = async () => {
    $('pair-error').textContent = '';
    try {
      await api('/api/pair', { code: $('code').value });
      $('pair').classList.add('hidden');
      $('code').value = '';
      await start();
    } catch (error) { $('pair-error').textContent = error.message; }
  };
  $('code').addEventListener('keydown', (event) => { if (event.key === 'Enter') $('pair-ok').click(); });
  $('send').onclick = () => act(async () => {
    const value = text.value.trim();
    if (!value || busy) return;
    await api('/api/chat', { text: value });
    text.value = '';
    text.style.height = '';
    messages.querySelector('.empty')?.remove();
    messages.append(bubble({ role: 'user', text: value }));
    streamEl = null;
    setBusy(true);
    say('A responder…');
    toBottom();
  });
  $('stop').onclick = () => act(() => api('/api/stop', {}));
  $('new').onclick = () => act(() => api('/api/new', {}));
  $('context').onchange = () => act(async () => { const [kind, ...rest] = $('context').value.split(':'); await api('/api/select', { kind, id: rest.join(':') }); });
  $('approval-allow').onclick = () => act(async () => { const id = approvalId; await api('/api/approval', { id, decision: 'allow' }); showApproval(null); });
  $('approval-deny').onclick = () => act(async () => { const id = approvalId; await api('/api/approval', { id, decision: 'deny' }); showApproval(null); });
  text.addEventListener('input', () => { text.style.height = ''; text.style.height = Math.min(text.scrollHeight, window.innerHeight * 0.4) + 'px'; });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !stopped && $('pair').classList.contains('hidden')) start(); });
  start();
})();
