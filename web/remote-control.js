"use strict";
// Painel «Acesso remoto» da janela da app: liga e desliga o servidor para o telemóvel e mostra o endereço e o código.
// As funções que o Python chama ficam em window; não há nomes globais novos declarados.
(() => {
  const modal = document.querySelector('#remote-modal');
  if (!modal) return;
  const $id = (id) => document.querySelector('#' + id);
  let timer = null;

  async function checked(method) {
    const result = await call(method);
    if (!result.ok) throw new Error(result.error);
    return result;
  }

  function render(data) {
    $id('remote-status').textContent = data.running ? `Ligado na porta ${data.port}.` : 'Desligado.';
    $id('remote-details').classList.toggle('hidden', !data.running);
    $id('remote-start').classList.toggle('hidden', data.running);
    $id('remote-stop').classList.toggle('hidden', !data.running);
    const urls = $id('remote-urls');
    urls.replaceChildren();
    for (const url of data.urls || []) { const item = document.createElement('li'); item.textContent = url; urls.append(item); }
    if (data.running && !(data.urls || []).length) { const item = document.createElement('li'); item.textContent = `http://<endereço deste PC>:${data.port}/`; urls.append(item); }
    $id('remote-code').textContent = data.locked ? `bloqueado ${data.locked} s (demasiadas tentativas)` : data.code || '';
    const devices = data.devices || [];
    $id('remote-devices').textContent = devices.length ? 'Dispositivos lembrados: ' + devices.map((device) => `${device.address} (desde as ${device.since})`).join(', ') + '.' : 'Nenhum dispositivo lembrado.';
    $id('remote-forget').classList.toggle('hidden', !devices.length);
  }

  async function refresh() {
    render(await checked('get_remote_control'));
  }

  function watch(on) {
    clearInterval(timer);
    timer = on ? setInterval(() => { if (modal.classList.contains('hidden')) watch(false); else refresh().catch(() => {}); }, 3000) : null;
  }

  const guard = (fn) => () => fn().catch((error) => showError(error.message));
  const close = () => { modal.classList.add('hidden'); watch(false); };
  window.openRemoteControl = guard(async () => { modal.classList.remove('hidden'); await refresh(); watch(true); });
  // chamadas pelo Python: um dispositivo emparelhou; ou o telemóvel mexeu na conversa
  window.remoteControlChanged = () => { if (!modal.classList.contains('hidden')) refresh().catch(() => {}); };
  window.remoteConversationChanged = (reload, text) => {
    if (text) setStatusMessage('Mensagem enviada do telemóvel…');
    if (!reload) return;
    call('get_state').then((result) => { if (result.ok) applyState(result); return loadConversation(); }).catch(() => {});
  };
  $id('remote-start').onclick = guard(async () => { render(await checked('start_remote_control')); });
  $id('remote-stop').onclick = guard(async () => { render(await checked('stop_remote_control')); });
  $id('remote-forget').onclick = guard(async () => {
    if (!confirm('Esquecer os dispositivos emparelhados? Cada um terá de voltar a emparelhar com o código.')) return;
    render(await checked('forget_remote_devices'));
  });
  $id('remote-close').onclick = close;
  modal.addEventListener('click', (event) => { if (event.target === modal) close(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !modal.classList.contains('hidden')) close(); });
})();
