"use strict";
(() => {
  const modal=document.querySelector('#code-modal');let selected='',working=false;
  const node=(tag,value,cls='')=>{const n=document.createElement(tag);n.textContent=value;n.className=cls;return n;};
  function status(value){document.querySelector('#code-status').textContent=value;}
  async function checked(method,...args){const r=await call(method,...args);if(!r.ok)throw new Error(r.error);return r;}
  function action(parent,label,callback,disabled=false){
    const btn=node('button',label,'btn ghost small');btn.disabled=disabled;
    btn.onclick=async()=>{if(working)return;working=true;btn.disabled=true;try{await callback();}catch(e){status(e.message);}finally{working=false;btn.disabled=disabled;}};parent.append(btn);
  }
  async function refresh(){
    const result=await checked('get_code_changes',selected);
    document.querySelector('#code-workspace').textContent=result.workspace;
    document.querySelector('#code-lsp-status').textContent=(result.lsp||[]).map(s=>s.name+': '+(s.installed?(s.connected?'ligado':'instalado · inicia quando necessário'):'não instalado')).join(' · ');
    const list=document.querySelector('#code-checkpoints');list.replaceChildren();
    for(const cp of result.checkpoints||[]){
      const card=node('article','','mcp-card');card.dataset.checkpoint=cp.id;
      const state=cp.interrupted?'Pedido interrompido · rever ficheiros':({active:'Pedido em curso',applied:'Aplicado',undone:'Desfeito'}[cp.state]||cp.state);
      card.append(node('strong',cp.title),node('p',new Date(cp.created_at).toLocaleString('pt-PT')+' · '+cp.file_count+' ficheiro(s) · '+state,'hint'));
      const actions=node('div','','top-actions');action(actions,'Ver alterações',async()=>{selected=cp.id;status('');await refresh();});card.append(actions);list.append(card);
    }
    if(!result.checkpoints?.length)list.append(node('p','Ainda não há alterações com checkpoint neste contexto.','hint'));
    preview(result.checkpoint);
  }
  function preview(cp){
    const area=document.querySelector('#code-checkpoint-preview');area.replaceChildren();if(!cp)return;
    area.append(node('h4',cp.title));let conflicts=false;
    for(const file of cp.files){
      const detail=node('details');detail.open=true;detail.append(node('summary',file.path+(file.conflict?' · alterado entretanto':'')));
      if(file.conflict){conflicts=true;detail.append(node('p','Este ficheiro já não corresponde à versão esperada. O restauro será recusado para preservar a alteração posterior.','notice warn'));}
      detail.append(node('pre',file.diff||'(sem diferenças de texto)','step-body'));area.append(detail);
    }
    const actions=node('div','','top-actions');
    const redo=cp.state==='undone';
    action(actions,redo?'Refazer alterações':'Desfazer alterações',async()=>{
      await checked('restore_code_checkpoint',cp.id,redo);status(redo?'Alterações reaplicadas.':'Alterações desfeitas; a conversa foi mantida.');await refresh();
    },cp.state==='active'||conflicts);area.append(actions);
  }
  document.querySelector('#btn-code-changes').onclick=async()=>{selected='';modal.classList.remove('hidden');status('A carregar…');try{await refresh();status('');}catch(e){status(e.message);}};
  document.querySelector('#code-close').onclick=()=>modal.classList.add('hidden');
  document.querySelector('#code-refresh').onclick=()=>refresh().catch(e=>status(e.message));
  modal.addEventListener('click',e=>{if(e.target===modal)modal.classList.add('hidden');});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!modal.classList.contains('hidden')){modal.classList.add('hidden');document.querySelector('#btn-code-changes').focus();}});
  document.querySelector('#code-lsp-form').onsubmit=async event=>{
    event.preventDefault();const btn=document.querySelector('#code-lsp-run'),area=document.querySelector('#code-diagnostics');btn.disabled=true;area.replaceChildren(node('p','A analisar o ficheiro…','hint'));
    try{
      const {result}=await checked('get_code_diagnostics',document.querySelector('#code-lsp-path').value.trim());area.replaceChildren();
      if(result.status!=='complete')area.append(node('p',result.message||result.status,'notice warn'));
      else if(!result.diagnostics.length)area.append(node('p','Sem diagnósticos reportados pelo servidor LSP para esta versão do ficheiro.','hint'));
      for(const d of result.diagnostics||[])area.append(node('pre',d.line+':'+d.column+' · '+d.severity+' · '+d.message,'step-body'));
    }catch(e){area.replaceChildren(node('p',e.message,'notice error'));}finally{btn.disabled=false;}
  };
})();
