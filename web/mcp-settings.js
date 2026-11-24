"use strict";
window.MCPSettings = (() => {
  let servers=[];
  const authTimers=new Map();
  let activeAuth=null;
  async function startAuth(id) {
    activeAuth=id;
    const result=await call('start_mcp_oauth',id);
    if (!result.ok) {showError(result.error);return;}
    $('#mcp-oauth-progress').classList.remove('hidden');
    $('#mcp-oauth-cancel').classList.remove('hidden');
    $('#mcp-oauth-message').textContent=result.job.message;
    if (authTimers.has(id))clearInterval(authTimers.get(id));
    const timer=setInterval(async()=>{
      const status=await call('mcp_oauth_status',id);
      if (!status.ok)return;
      if (activeAuth===id)$('#mcp-oauth-message').textContent=status.job.message;
      if (!['starting','waiting'].includes(status.job.state)) {
        clearInterval(timer);authTimers.delete(id);
        if (activeAuth===id)$('#mcp-oauth-cancel').classList.add('hidden');
        if (status.job.state==='error')showError(status.job.message);
        if (status.job.state==='connected') { try { await call('test_mcp_server',id); } catch (error) { /* o cartão mostra o erro */ } }
        await refreshToolCatalog();
      }
    },700);
    authTimers.set(id,timer);
  }
  function renderServers(items) {
    servers=items;
    const list=document.querySelector('#mcp-servers');
    list.replaceChildren();
    if (!items.length) {list.textContent='Ainda não há servidores MCP configurados.';return;}
    for (const server of items) {
      const card=document.createElement('div');card.className='mcp-card';
      const title=document.createElement('strong');title.textContent=server.name;
      const detail=document.createElement('p');detail.className='hint';
      detail.textContent=(server.enabled ? server.connected ? 'Ligado' : server.error ? 'Ativo · não ligou' : 'Ativo · liga sozinho na primeira mensagem' : 'Desligado')+' · '+server.transport+(server.connected ? ' · '+server.tool_count+' ferramenta(s)' : '')+(server.protocol ? ' · MCP '+server.protocol : '')+(server.error ? ' · '+server.error : '');
      if (server.service_error)detail.textContent+=' · Ligação ao serviço falhou: '+server.service_error;
      const actions=document.createElement('div');actions.className='top-actions';
      const choices=[['Editar','edit'],['Testar','test'],[server.enabled?'Desligar':'Ligar','toggle'],['Remover','remove']];
      if (server.auth_mode==='oauth') {
        choices.unshift(['Ligar conta','oauth']);
        if (server.oauth?.linked)choices.push(['Desligar conta','logout']);
        detail.textContent+=' · Conta '+(server.oauth?.linked?'autorizada':'por autorizar');
      }
      for (const [label,action] of choices) {
        const button=document.createElement('button');button.className='btn ghost small';button.textContent=label;
        button.onclick=async () => {
          if (action==='edit') {
            const preset=presets.find(p=>p.kind===server.preset);
            return preset?editPreset(preset):editServer(server);
          }
          if (action==='oauth')return startAuth(server.id);
          button.disabled=true;
          try {
            let result;
            if (action==='test')result=await call('test_mcp_server',server.id);
            else if (action==='toggle')result=await call('save_mcp_server',{id:server.id,enabled:!server.enabled});
            else if (action==='logout')result=await call('disconnect_mcp_oauth',server.id);
            else result=await call('remove_mcp_server',server.id);
            if (!result.ok)showError(result.error);
            else if (action==='test')setStatusMessage('Servidor MCP ligado: '+result.server.tool_count+' ferramenta(s).');
            await refreshToolCatalog();
          } finally {button.disabled=false;}
        };
        actions.append(button);
      }
      card.append(title,detail,actions);list.append(card);
    }
  }
  function editServer(server=null, preset=null) {
    const title=preset?(server?.id?'Editar integração MCP':'Configurar integração MCP'):(server?'Editar servidor MCP':'Adicionar servidor MCP');
    const presetFields=(preset?.fields||[]).map(field=>`
      <label class="field"><span>${esc(field.label)}</span>
        ${field.options?`<select id="preset-field-${esc(field.key)}">${field.options.map(([value,label])=>`<option value="${esc(value)}" ${String(server?.settings?.[field.key] ?? field.default ?? '')===value?'selected':''}>${esc(label)}</option>`).join('')}</select>`:`<input id="preset-field-${esc(field.key)}" type="${field.secret?'password':'text'}" autocomplete="${field.secret?'new-password':'off'}" value="${field.secret?'':esc(server?.settings?.[field.key] ?? field.default ?? '')}" placeholder="${esc(field.label)}" />`}
      </label>`).join('');
    const presetHelp=preset?.help?`<p class="hint">${esc(preset.help)}</p>`:'';
    const quickPreset=preset?'':`<label class="field"><span>Configuração rápida</span><select id="mcp-preset"><option value="custom">Servidor personalizado</option><option value="linear-read">Linear — só leitura</option><option value="linear">Linear — leitura e escrita</option><option value="github">GitHub remoto — pode exigir Client ID próprio</option></select></label>`;
    showModal({title,okLabel:'Guardar e ligar',bodyHTML:`
      ${preset?`<p class="hint">${esc(preset.description)}</p>`:''}
      ${quickPreset}
      <label class="field"><span>Nome</span><input id="mcp-name" value="${esc(server?.name || preset?.name || '')}" placeholder="GitHub, Playwright, servidor local…" ${preset?'readonly':''} /></label>
      <label class="field"><span>Transporte</span><select id="mcp-transport" ${preset?'disabled':''}><option value="stdio">Local — stdio</option><option value="http">Remoto — Streamable HTTP</option></select></label>
      <div id="mcp-local-fields">
        <label class="field"><span>Executável</span><input id="mcp-command" value="${esc(server?.command || preset?.command || '')}" placeholder="C:\\caminho\\servidor.exe ou npx.cmd" ${preset?'readonly':''} /></label>
        <label class="field"><span>Argumentos (lista JSON)</span><textarea id="mcp-args" rows="2" ${preset?'readonly':''}>${esc(JSON.stringify(server?.args || preset?.args || []))}</textarea></label>
        <label class="field"><span>Pasta de execução (vazio = projeto/conversa)</span><input id="mcp-cwd" value="${esc(server?.cwd || '')}" ${preset?'readonly':''} /></label>
      </div>
      <div id="mcp-http-fields"><label class="field"><span>URL do endpoint MCP</span><input id="mcp-url" value="${esc(server?.url || preset?.url || '')}" placeholder="https://servico.exemplo/mcp" ${preset?'readonly':''} /></label></div>
      <div id="mcp-auth-field"><label class="field"><span>Autenticação</span><select id="mcp-auth"><option value="manual">Token/cabeçalhos manuais</option><option value="oauth">Iniciar sessão no browser (OAuth)</option></select></label></div>
      <div id="mcp-oauth-fields"><p class="hint">Ao guardar abre-se o browser do sistema para iniciares sessão e autorizares a ligação. A app trata do registo automático quando suportado e da renovação da autorização.</p>
        <label class="field"><span>Scope (opcional)</span><input id="mcp-scope" value="${esc(server?.oauth_scope || '')}" placeholder="read write" /></label>
        <details><summary>Opções avançadas — serviços sem registo automático</summary>
          <label class="field"><span>Client ID próprio (opcional)</span><input id="mcp-client-id" value="${esc(server?.oauth_client_id || '')}" /></label>
          <label class="field"><span>Client secret (opcional; vazio mantém o atual)</span><input id="mcp-client-secret" type="password" autocomplete="new-password" /></label>
          <label class="field"><span>Porta de retorno fixa (0 = automática)</span><input id="mcp-callback-port" type="number" min="0" max="65535" value="${Number(server?.oauth_callback_port || 0)}" /></label>
          <p class="hint">O retorno usa http://127.0.0.1:&lt;porta&gt;/oauth/callback. Alguns serviços exigem registar esta aplicação primeiro.</p>
        </details>
      </div>
      <div id="mcp-manual-secrets">
      <label class="field"><span>Variáveis de ambiente (objeto JSON; vazio mantém as atuais)</span><textarea id="mcp-env" rows="2" placeholder='{"API_TOKEN":"…"}'></textarea></label>
      <label class="field"><span>Cabeçalhos HTTP (objeto JSON; vazio mantém os atuais)</span><textarea id="mcp-headers" rows="2" placeholder='{"Authorization":"Bearer …"}'></textarea></label>
      <p class="hint">Credenciais atuais: ${esc([...(server?.env_names || []),...(server?.header_names || [])].join(', ') || 'nenhuma')}. Os valores não são devolvidos ao catálogo. Usa {} para limpar um campo de credenciais.</p>
      </div>
      ${presetFields}
      ${presetHelp}
      <label class="field"><span>Aprovação das chamadas deste servidor</span><select id="mcp-approval"><option value="each">Confirmar cada chamada</option><option value="auto">Usar autonomamente, sem perguntar</option></select></label>
      <label class="check"><input type="checkbox" id="mcp-enabled" checked /> <span>Servidor ativo</span></label>
      <p class="hint">O servidor executa com as próprias permissões. Os limites de ficheiros da app não isolam um processo MCP externo. Tokens OAuth não aparecem no catálogo; no Windows são protegidos pelo DPAPI.</p>`,
      onOk:async () => {
        try {
          const data={name:$('#mcp-name').value.trim(),transport:$('#mcp-transport').value,command:$('#mcp-command').value.trim(),args:JSON.parse($('#mcp-args').value || '[]'),cwd:$('#mcp-cwd').value.trim(),url:$('#mcp-url').value.trim(),approval:$('#mcp-approval').value,enabled:$('#mcp-enabled').checked};
          data.auth_mode=data.transport==='http'?$('#mcp-auth').value:'manual';
          data.oauth_client_id=$('#mcp-client-id').value.trim();
          data.oauth_callback_port=Number($('#mcp-callback-port').value || 0);
          data.oauth_scope=$('#mcp-scope').value.trim();
          if ($('#mcp-client-secret').value)data.oauth_client_secret=$('#mcp-client-secret').value;
          if (server)data.id=server.id;
          if ($('#mcp-env').value.trim())data.env=JSON.parse($('#mcp-env').value);
          if ($('#mcp-headers').value.trim())data.headers=JSON.parse($('#mcp-headers').value);
          if (preset) {
            data.preset=preset.kind;
            for (const field of preset.fields||[]) {
              const input=$('#preset-field-'+field.key);
              if (input)data[field.key]=input.value.trim();
            }
            const result=await call('save_mcp_preset',preset.kind,data);
            if (!result.ok) {showError(result.error);return false;}
            if (data.auth_mode==='oauth') {
              const savedId=result.server_id || (result.servers||[]).find(s=>s.preset===preset.kind)?.id;
              if (savedId)await startAuth(savedId);
            }
            if (preset.mode==='bundled' && data.enabled && result.server_id) {
              const tested=await call('test_mcp_server',result.server_id);
              if (!tested.ok)showError('Configuração guardada. A ligação ainda falhou: '+tested.error);
            }
            await refreshToolCatalog();return true;
          }
          const result=await call('save_mcp_server',data);
          if (!result.ok) {showError(result.error);return false;}
          if (data.auth_mode==='oauth') {
            const saved=server?result.servers.find(s=>s.id===server.id):result.servers.at(-1);
            await startAuth(saved.id);
          }
          await refreshToolCatalog();return true;
        } catch(error) {showError('Configuração MCP inválida: '+error.message);return false;}
      }});
    $('#mcp-transport').value=server?.transport || preset?.transport || 'stdio';
    $('#mcp-approval').value=server?.approval || 'each';
    $('#mcp-auth').value=server?.auth_mode || (preset?.mode==='remote'?'oauth':'manual');
    $('#mcp-enabled').checked=server?.enabled ?? true;
    const nodePreset=preset?.mode==='node';
    const update=() => {
      const http=$('#mcp-transport').value==='http',oauth=http && $('#mcp-auth').value==='oauth';
      $('#mcp-local-fields').classList.toggle('hidden',http);$('#mcp-http-fields').classList.toggle('hidden',!http);
      $('#mcp-auth-field').classList.toggle('hidden',!http);$('#mcp-oauth-fields').classList.toggle('hidden',!oauth);
      $('#mcp-manual-secrets').classList.toggle('hidden',nodePreset || preset?.mode==='bundled' || oauth);
    };
    const quick=$('#mcp-preset');
    if (quick) quick.onchange=()=>{
      const value=quick.value;
      if (value==='custom')return;
      $('#mcp-transport').value='http';$('#mcp-auth').value='oauth';
      $('#mcp-name').value=value==='github'?'GitHub':value==='linear-read'?'Linear (leitura)':'Linear';
      $('#mcp-url').value=value==='github'?'https://api.githubcopilot.com/mcp/':value==='linear-read'?'https://mcp.linear.app/mcp/readonly':'https://mcp.linear.app/mcp';
      update();
    };
    $('#mcp-transport').onchange=update;$('#mcp-auth').onchange=update;update();
  }
  let presets=[];
  let presetProfile="all";
  const presetTimers=new Map();

  function addPresetButton(actions,label,fn,disabled=false) {
    const button=document.createElement('button');
    button.className='btn ghost small';button.textContent=label;button.disabled=!!disabled;
    button.onclick=async()=>{button.disabled=true;try{await fn();}finally{button.disabled=false;}};
    actions.append(button);
  }

  function updatePresetJob(kind,job) {
    if (!job || !job.message)return;
    const element=document.querySelector(`#mcp-presets .mcp-card[data-kind="${kind}"] [data-preset-status]`);
    if (element)element.textContent=job.message;
  }

  function pollPreset(kind) {
    if (presetTimers.has(kind))clearInterval(presetTimers.get(kind));
    const timer=setInterval(async()=>{
      const result=await call('mcp_component_status',kind);
      if (!result.ok) {clearInterval(timer);presetTimers.delete(kind);showError(result.error);return;}
      const job=result.job||{};
      updatePresetJob(kind,job);
      if (job.state!=='running') {
        clearInterval(timer);presetTimers.delete(kind);
        if (job.state==='error')showError(job.message);
        await refreshToolCatalog();
      }
    },700);
    presetTimers.set(kind,timer);
  }

  async function installPreset(kind) {
    const result=await call('install_mcp_component',kind);
    if (!result.ok) {showError(result.error);return;}
    updatePresetJob(kind,result.job);
    pollPreset(kind);
  }

  async function authorizePreset(kind) {
    const result=await call('install_mcp_component',kind,true);
    if (!result.ok) {showError(result.error);return;}
    updatePresetJob(kind,result.job);
    pollPreset(kind);
  }

  async function testPreset(preset) {
    const result=await call('test_mcp_server',preset.server_id);
    if (!result.ok)showError(result.error);
    else setStatusMessage('Integração ligada: '+result.server.tool_count+' ferramenta(s).');
    await refreshToolCatalog();
  }

  async function removePreset(preset) {
    const result=await call('remove_mcp_server',preset.server_id);
    if (!result.ok)showError(result.error);
    await refreshToolCatalog();
  }

  async function disconnectPreset(preset) {
    const result=await call('disconnect_mcp_oauth',preset.server_id);
    if (!result.ok)showError(result.error);
    await refreshToolCatalog();
  }

  function editPreset(preset) {
    const server=preset.server?{...preset.server}:{};
    Object.assign(server,{
      preset:preset.kind,
      settings:preset.settings||{},
      name:preset.name,
      transport:preset.transport,
      url:preset.url,
      command:preset.command,
      args:preset.args,
      approval:preset.approval||'each',
      enabled:preset.server?preset.server.enabled:true,
    });
    editServer(server,preset);
  }

  function renderPresets(items,profile) {
    presets=Array.isArray(items)?items:[];
    if (profile) {
      presetProfile=profile;
      const select=document.querySelector('#presets-profile');
      if (select && select.value!==profile)select.value=profile;
    }
    const list=document.querySelector('#mcp-presets');
    if (!list)return;
    list.replaceChildren();
    const visible=presets.filter(p=>presetProfile==='all'||(p.profiles||[]).includes(presetProfile));
    if (!visible.length) {list.textContent='Sem integrações neste perfil.';return;}
    for (const p of visible) {
      const card=document.createElement('div');card.className='mcp-card';card.dataset.kind=p.kind;
      const title=document.createElement('strong');title.textContent=p.name;
      const badges=document.createElement('div');badges.className='badges';
      const badge=(text)=>{const item=document.createElement('span');item.className='badge';item.textContent=text;badges.append(item);};
      badge(p.mode==='remote'?'remoto':'local');
      if (p.version)badge('v'+p.version);
      if (p.mode==='node')badge(p.installed?'instalado':'por instalar');
      if (p.server)badge(p.server.enabled?(p.server.service_error?'falha no serviço':p.server.connected?'ligado':'por ligar'):'desligado');
      const description=document.createElement('p');description.className='hint';description.textContent=p.description;
      const job=p.job||{state:'idle',message:''};
      const status=document.createElement('p');status.className='hint';status.dataset.presetStatus=p.kind;
      if (job.state==='running'||job.state==='error')status.textContent=job.message;
      else if (p.server)status.textContent=p.server.service_error?('Ligação ao serviço falhou · '+p.server.service_error):(p.server.connected?((p.mode==='bundled'&&!p.server.service_verified?'Conector pronto; serviço ainda não testado':'Ligado')+' · '+p.server.tool_count+' ferramenta(s)'):'Configurado, por ligar')+(p.server.error?' · '+p.server.error:'');
      else if (p.mode==='node'&&!p.node)status.textContent='Instala Node.js 20 ou superior.';
      else if (p.mode==='node'&&!p.installed)status.textContent='Componente local por instalar.';
      else status.textContent='Pronto para configurar.';
      const actions=document.createElement('div');actions.className='top-actions';
      const busy=job.state==='running';
      if (p.mode==='node'&&!p.installed)addPresetButton(actions,'Instalar',()=>installPreset(p.kind),busy||!p.node);
      if (p.mode==='node'&&p.installed&&p.kind==='google_drive'&&p.settings?.credentials_path)addPresetButton(actions,'Autorizar',()=>authorizePreset(p.kind),busy);
      if (!p.server) {
        addPresetButton(actions,'Configurar',()=>editPreset(p),busy||(p.mode==='node'&&!p.installed));
      } else {
        if (p.mode==='remote'&&p.server.auth_mode==='oauth') {
          if (p.server.oauth?.linked)addPresetButton(actions,'Desligar conta',()=>disconnectPreset(p));
          else addPresetButton(actions,'Ligar conta',()=>startAuth(p.server_id));
        }
        addPresetButton(actions,'Editar',()=>editPreset(p),busy);
        addPresetButton(actions,'Testar',()=>testPreset(p),busy);
        addPresetButton(actions,'Remover',()=>removePreset(p),busy);
      }
      card.append(title,badges,description);
      if (p.help) {
        const help=document.createElement('p');help.className='hint preset-help';help.textContent=p.help;card.append(help);
      }
      card.append(status,actions);
      list.append(card);
    }
  }

  function init() {
    $('#mcp-oauth-cancel').onclick=async()=>{
      if (!activeAuth)return;
      await call('cancel_mcp_oauth',activeAuth);
      $('#mcp-oauth-message').textContent='A cancelar a ligação…';
    };
    $('#mcp-add').onclick=()=>editServer();
    const profile=$('#presets-profile');
    if (profile) profile.onchange=async()=>{
      const result=await call('set_preference','mcp_profile',profile.value);
      if (!result.ok) {showError(result.error);return;}
      await refreshToolCatalog();
    };
    $('#mcp-demo').onclick=async () => {
      const button=$('#mcp-demo');button.disabled=true;
      try {const result=await call('add_mcp_demo');if (!result.ok)showError(result.error);else await refreshToolCatalog();}
      finally {button.disabled=false;}
    };
  }
  return {init,renderServers,renderPresets};
})();
