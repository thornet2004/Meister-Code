"use strict";
(() => {
  let rows=[];
  const modal=document.querySelector('#tools-modal');
  const search=document.querySelector('#tools-search');
  const category=document.querySelector('#tools-category');
  const installed=document.querySelector('#tools-only-installed');
  function action(parent,label,fn) {
    const btn=document.createElement('button');btn.className='btn ghost small';btn.textContent=label;
    btn.onclick=async()=>{btn.disabled=true;try {await fn();} catch(e){showError(e.message);} finally {btn.disabled=false;}};
    parent.append(btn);
  }
  function text(tag,value,className='') {const node=document.createElement(tag);node.textContent=value;node.className=className;return node;}
  async function checked(method,...args) {const result=await call(method,...args);if(!result.ok)throw new Error(result.error);return result;}
  function render() {
    const list=document.querySelector('#tools-inventory');list.replaceChildren();
    const query=search.value.trim().toLocaleLowerCase('pt');
    const visible=rows.filter(r=>(!category.value||r.category===category.value)&&(!installed.checked||r.installed)&&(!query||[r.name,r.category,r.description,r.note].join(' ').toLocaleLowerCase('pt').includes(query)));
    for(const row of visible) {
      const card=document.createElement('article');card.className='mcp-card';card.dataset.toolName=row.name;
      const head=document.createElement('div');head.className='tools-card-head';
      head.append(text('strong',row.name+(row.version?' · '+row.version:'')),text('span',row.status,'badge '+(row.installed?'tools-ready':'tools-pending')));
      card.append(head,text('p',row.category,'hint'));
      if(row.description)card.append(text('p',row.description,'hint'));
      if(row.note)card.append(text('p',row.note,'hint'));
      if(row.error)card.append(text('p',row.error,'notice warn'));
      if(row.executable)card.append(text('code',row.executable));
      const actions=document.createElement('div');actions.className='top-actions';
      if(row.folderId) {
        action(actions,'Testar ligação MCP',async()=>{const result=await checked('test_folder_tool',row.folderId);setStatusMessage(row.name+': '+result.count+' operações MCP.');await refresh();});
        action(actions,row.enabled?'Desativar':'Ativar',async()=>{await checked('set_folder_tool',row.folderId,!row.enabled,null);await refresh();});
        // se o agente tem de pedir autorização em cada chamada a esta ferramenta (vinha das definições, «Ferramentas em pastas»)
        const label=document.createElement('label');label.className='field';
        const select=document.createElement('select');select.setAttribute('aria-label','Aprovação de '+row.name);
        for(const [value,caption] of [['each','Confirmar chamadas'],['auto','Usar sem perguntar']])select.add(new Option(caption,value));
        select.value=row.approval||'each';
        select.onchange=async()=>{try{await checked('set_folder_tool',row.folderId,null,select.value);await refresh();}catch(e){showError(e.message);}};
        label.append(text('span','Aprovação'),select);actions.append(label);
      }
      if(row.key) {
        if(row.executable&&['GIMP','ImHex','PulseView','SerialSniffer','Ghidra','URH','Packetry'].includes(row.key))action(actions,'Abrir aplicação',()=>checked('open_bench_app',row.key));
        action(actions,'Abrir pasta',()=>checked('open_bench_folder',row.key));
        action(actions,'Configurar executável',async()=>{await checked('configure_bench_executable',row.key);await refresh();});
      } else if(row.folderId)action(actions,'Abrir pasta',()=>checked('open_tools_folder',row.folderId));
      card.append(actions);list.append(card);
    }
    if(!visible.length)list.append(text('p','Nenhuma ferramenta corresponde a este filtro.','hint'));
    document.querySelector('#tools-summary').textContent=rows.filter(r=>r.installed).length+' instaladas / incluídas · '+rows.filter(r=>!r.installed).length+' com dependências pendentes · '+visible.length+' apresentadas';
  }
  async function refresh() {
    document.querySelector('#tools-summary').textContent='A verificar software instalado…';
    const result=await checked('get_tools_inventory');
    const folders=result.folder_tools||[];
    const normalize=path=>String(path||'').replaceAll('\\','/').toLowerCase();
    rows=(result.bench||[]).map(row=>{
      const folder=folders.find(f=>normalize(f.path)===normalize(row.path));
      const suffix=folder?.enabled===false?' · desativada':folder?.state?.connected?' · MCP ligado ('+(folder.state.tool_count||0)+' operações)':'';
      return {...row,version:row.version||folder?.package_version||'',status:row.status+suffix,folderId:folder?.id,enabled:folder?.enabled,approval:folder?.approval,error:folder?.state?.error||folder?.error};
    });
    const covered=new Set(rows.map(r=>normalize(r.path)));
    for(const row of folders)if(!covered.has(normalize(row.path)))rows.push({name:row.name,description:row.description,category:'Ferramentas locais',installed:!row.error,status:row.error?'Manifesto inválido':row.enabled?'Instalada · '+(row.state?.connected?'ligada':'ligação quando necessária'):'Instalada · desativada',folderId:row.id,enabled:row.enabled,approval:row.approval,error:row.error||row.state?.error,version:row.package_version});
    for(const row of result.mcp_servers||[])rows.push({name:row.name,category:'Servidores MCP',installed:true,status:row.enabled?(row.connected?'Ligado':'Configurado · ligação quando necessária'):'Desativado',error:row.error,description:(row.tool_count||0)+' operações descobertas'});
    for(const row of result.language_servers||[])rows.push({name:(row.label||(row.name==='python'?'Python · Pyright':'JavaScript/TypeScript'))+' · LSP',category:'Diagnósticos de código',installed:row.installed,status:row.installed?(row.connected?'Instalado · ligado':'Instalado · inicia quando necessário'):(row.source==='path'?'Opcional · '+row.executable+' não encontrado no PATH':'Não instalado'),description:'Diagnósticos de código disponíveis no botão Alterações e na ferramenta lsp_diagnosticos.'+(row.extensions?' Ficheiros: '+row.extensions.join(' '):'')});
    for(const tool of result.tools||[])rows.push({name:tool.name,description:tool.description,category:'Operações incluídas na app',installed:true,status:'Incluída'});
    const previous=category.value;category.replaceChildren(new Option('Todas as categorias',''));
    for(const group of [...new Set(rows.map(r=>r.category))].sort())category.add(new Option(group,group));
    category.value=previous;render();
  }
  document.querySelector('#btn-tools').onclick=async()=>{modal.classList.remove('hidden');search.focus();try{await refresh();}catch(e){showError(e.message);document.querySelector('#tools-summary').textContent='Não foi possível ler o inventário.';}};
  document.querySelector('#tools-close').onclick=()=>modal.classList.add('hidden');
  modal.addEventListener('click',e=>{if(e.target===modal)modal.classList.add('hidden');});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!modal.classList.contains('hidden')){modal.classList.add('hidden');document.querySelector('#btn-tools').focus();}});
  search.oninput=render;category.onchange=render;installed.onchange=render;
  document.querySelector('#tools-refresh').onclick=()=>refresh().catch(e=>showError(e.message));
  document.querySelector('#tools-folder').onclick=()=>checked('open_tools_folder').catch(e=>showError(e.message));
  document.querySelector('#tools-settings').onclick=()=>{modal.classList.add('hidden');document.querySelector('#btn-settings').click();};
})();
