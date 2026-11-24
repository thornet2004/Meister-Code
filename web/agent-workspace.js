"use strict";
(()=>{
 const modal=document.querySelector('#agent-workspace-modal');let selected='',timer=null,busy=false,pending=false;
 const text=(tag,value,cls='')=>{const n=document.createElement(tag);n.textContent=value;n.className=cls;return n;};
 const labels={queued:'Na fila',running:'Em execução',cancelling:'A cancelar',cancelled:'Cancelada',completed:'Concluída',awaiting_review:'Proposta pronta para revisão',validation_failed:'Verificações por resolver',needs_resolution:'Resultado de operações por confirmar',limited:'Limite atingido',interrupted:'Interrompida',error:'Erro'};
 const active=s=>['queued','running','cancelling'].includes(s);
 const status=value=>document.querySelector('#agent-workspace-status').textContent=value;
 async function checked(method,...args){const r=await call(method,...args);if(!r.ok)throw new Error(r.error);return r;}
 function button(parent,label,fn,disabled=false){const btn=text('button',label,'btn ghost small');btn.disabled=disabled;btn.onclick=async()=>{btn.disabled=true;try{await fn();}catch(e){status(e.message);}finally{btn.disabled=disabled;}};parent.append(btn);}
 function stopPolling(){if(timer)clearTimeout(timer);timer=null;}
 function close(){modal.classList.add('hidden');stopPolling();}
 async function refresh(){
  if(busy){pending=true;return;}busy=true;
  try{
   const result=await checked('get_agent_workspace',selected);document.querySelector('#agent-workspace-path').textContent=result.workspace;
   const models=document.querySelector('#agent-model-settings');models.replaceChildren();
   for(const [id,label] of [['build','Implementar'],['plan','Planear'],['review','Rever'],['explore','Explorar']]){
    const field=text('label','','field');field.append(text('span',label));const select=document.createElement('select');select.setAttribute('aria-label','Modelo para '+label);select.add(new Option('Herdar da conversa',''));
    for(const provider of state.providers)for(const model of provider.models||[])if(model.type==='chat')select.add(new Option(provider.name+' · '+(model.name||model.id),JSON.stringify([provider.id,model.id])));
    const selectedModel=state.preferences.agent_models?.[id];select.value=selectedModel?.model_id?JSON.stringify([selectedModel.provider_id,selectedModel.model_id]):'';
    select.onchange=async()=>{const [provider,model]=select.value?JSON.parse(select.value):['',''];try{applyState(await checked('set_agent_model',id,provider,model));status('Modelo do perfil atualizado.');}catch(e){status(e.message);}};
    field.append(select);models.append(field);
   }
   document.querySelector('#agent-task-submit').disabled=!result.agent_enabled;
   const list=document.querySelector('#agent-tasks-list');list.replaceChildren();
   for(const task of result.tasks||[]){
    const card=text('article','','mcp-card');card.dataset.taskId=task.id;card.append(text('strong',task.title),text('p',(labels[task.state]||task.state)+' · '+task.profile+' · '+task.model_id+' · '+(task.usage?.total_tokens||0)+' tokens','hint'));
    const actions=text('div','','top-actions');button(actions,'Ver resultado',async()=>{selected=task.id;await refresh();});
    if(task.recovery&&!active(task.state))button(actions,'Recuperação / Retomar',async()=>{await window.openTaskRecovery(task.id);});
    if(active(task.state))button(actions,'Cancelar tarefa',async()=>{await checked('cancel_agent_task',task.id);await refresh();},task.state==='cancelling');card.append(actions);list.append(card);
   }
   if(!result.tasks?.length)list.append(text('p','Ainda não há tarefas de subagentes neste projeto/conversa.','hint'));
   const detail=document.querySelector('#agent-task-detail');detail.replaceChildren();
   if(result.task){const task=result.task;detail.append(text('h4',task.title),text('p',labels[task.state]||task.state,'hint'),text('pre',task.result||task.progress?.text||task.message||'A aguardar o resultado…','step-body'));
    if(task.proposal){button(detail,'Rever proposta isolada',async()=>{
     const r=await checked('review_agent_proposal',task.id),p=r.proposal,view=text('div');view.append(text('p',p.coverage,'hint'),text('p',p.workspace,'hint'));
     const v=p.validation||{state:'legacy',checks:[]};view.append(text('strong','Verificações: '+v.state+(v.stale?' · código alterado após a execução':'')));
     if(v.state==='no_checks')view.append(text('p','Sem verificações declaradas: esta proposta não foi validada por testes.','notice warn'));
     for(const check of v.checks||[])view.append(text('pre',check.label+' · '+check.state+'\n'+(check.output||check.message||''),'step-body'));
     if(p.state!=='applied'){
      button(view,'Revalidar proposta',async()=>{const run=await checked('validate_agent_proposal',task.id,false);status('Verificação iniciada: '+run.run.id+'. Volta a abrir a revisão para consultar o resultado.');});
      button(view,'Preparar dependências da proposta',async()=>{await checked('validate_agent_proposal',task.id,true);status('Preparação iniciada. Ao terminar, revalida a proposta.');});
     }
     for(const file of p.files)view.append(text('pre',(file.conflict?'CONFLITO · ':'')+file.path+'\n'+file.diff,'step-body'));
     if(p.state!=='applied'&&p.files.length&&p.can_apply!==false&&!p.files.some(f=>f.conflict))button(view,'Aplicar proposta ao projeto',async()=>{await checked('apply_agent_proposal',task.id);status('Proposta aplicada com checkpoint.');await refresh();});detail.append(view);
    });}
    if(task.steps?.length){const steps=text('details');steps.append(text('summary','Evidência das ferramentas'));for(const step of task.steps)steps.append(text('pre',step.title+'\n'+step.body,'step-body'));detail.append(steps);}
   }
   const rules=document.querySelector('#agent-project-rules');rules.replaceChildren();
   for(const item of result.rules||[]){const d=text('details');d.append(text('summary',item.path),text('pre',item.text+(item.truncated?'\n[truncado]':''),'step-body'));rules.append(d);}
   if(!result.rules?.length)rules.append(text('p','Sem AGENTS.md na raiz. Regras em subpastas são carregadas quando o agente lê ficheiros dessas pastas.','hint'));
   const skills=document.querySelector('#agent-project-skills');skills.replaceChildren();
   for(const skill of result.skills||[]){const card=text('article','','mcp-card');card.append(text('strong',skill.name),text('p',skill.description,'hint'),text('p',skill.path,'hint'));button(card,'Ver skill',async()=>{const r=await checked('get_project_skill',skill.id);const view=document.querySelector('#agent-skill-preview');view.textContent=r.skill.text;view.classList.remove('hidden');});skills.append(card);}
   if(!result.skills?.length)skills.append(text('p','Sem skills nos diretórios suportados.','hint'));
   stopPolling();if(!modal.classList.contains('hidden')&&(result.tasks||[]).some(t=>active(t.state)))timer=setTimeout(()=>refresh().catch(e=>status(e.message)),1800);
  }finally{busy=false;if(pending&&!modal.classList.contains('hidden')){pending=false;setTimeout(()=>refresh().catch(e=>status(e.message)),0);}}
 }
 document.querySelector('#btn-agent-workspace').onclick=async()=>{selected='';modal.classList.remove('hidden');status('');document.querySelector('#agent-skill-preview').classList.add('hidden');try{await refresh();}catch(e){status(e.message);}};
 document.querySelector('#agent-workspace-close').onclick=close;modal.addEventListener('click',e=>{if(e.target===modal)close();});document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!modal.classList.contains('hidden')){close();document.querySelector('#btn-agent-workspace').focus();}});
 document.querySelector('#agent-workspace-refresh').onclick=()=>refresh().catch(e=>status(e.message));
 window.addEventListener('agent-task-updated',()=>{if(!modal.classList.contains('hidden'))refresh().catch(e=>status(e.message));});
 document.querySelector('#agent-task-form').onsubmit=async e=>{e.preventDefault();const btn=document.querySelector('#agent-task-submit');btn.disabled=true;try{const r=await checked('start_agent_task',document.querySelector('#agent-task-profile').value,document.querySelector('#agent-task-prompt').value.trim());selected=r.task.id;document.querySelector('#agent-task-prompt').value='';status('Tarefa criada.');await refresh();}catch(error){status(error.message);}finally{btn.disabled=false;}};
})();
