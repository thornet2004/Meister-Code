"use strict";
(()=>{
 const el=(tag,value='',cls='')=>{const n=document.createElement(tag);n.textContent=value;n.className=cls;return n;};
 const host=document.querySelector('#agent-workspace-modal'),body=host.querySelector('.modal-body'),panel=el('details');panel.id='task-recovery-panel';panel.append(el('summary','Recuperação de conversas e tarefas'));body.prepend(panel);const status=el('p','','hint'),list=el('div'),detail=el('div');status.id='recovery-status';detail.id='recovery-detail';panel.append(status,list,detail);let current=null,busy=false;
 const eligible=s=>['interrupted','cancelled','error','limited','validation_failed','needs_resolution'].includes(s);
 async function checked(method,...args){const r=await call(method,...args);if(!r.ok)throw Error(r.error);return r;}
 function button(parent,label,fn,disabled=false){const b=el('button',label,'btn ghost small');b.type='button';b.disabled=disabled;b.onclick=async()=>{if(busy)return;busy=true;b.disabled=true;try{await fn();}catch(e){status.textContent=e.message;}finally{busy=false;b.disabled=disabled;}};parent.append(b);return b;}
 button(panel,'Atualizar recuperação',async()=>{await refresh();if(current)await show(current.kind,current.key);});
 async function refresh(){const r=await checked('get_chat_recovery');list.replaceChildren();for(const run of r.runs.filter(r=>r.state!=='completed')){const card=el('article','','mcp-card');card.dataset.recoveryId=run.id;card.append(el('strong',run.prompt.slice(0,160)),el('p',run.state+' · tentativa '+run.attempt,'hint'));button(card,'Ver recuperação da conversa',async()=>show('turn',run.id));list.append(card);}if(!list.childElementCount)list.append(el('p','Sem pedidos de conversa por recuperar neste contexto. Usa Recuperação / Retomar nas tarefas para consultar os subagentes.','hint'));}
 async function show(kind,key){
  current={kind,key};host.classList.remove('hidden');panel.open=true;const r=await checked(kind==='turn'?'get_chat_recovery':'get_agent_recovery',key),j=r.recovery;detail.replaceChildren();status.textContent='';
  detail.append(el('h4',(kind==='turn'?'Conversa':'Subagente')+' · tentativa '+j.attempt),el('p',j.state+' · '+j.action_count+' ações registadas · '+(j.profile||'')+' · '+(j.model_id||''),'hint'),el('p','Workspace original: '+j.workspace,'hint'),el('pre',j.progress?.text||'Sem resposta parcial guardada.','step-body'));
  if(j.unknown.length)detail.append(el('p','Há operações sem resultado conhecido. A retoma pode analisar o estado; novas escritas e comandos ficam bloqueados até verificação.','notice warn'));
  for(const action of j.unknown){const card=el('article','','mcp-card');card.append(el('strong',action.name),el('pre',action.arguments_preview+(action.error?'\n'+action.error:''),'step-body'));const outcome=el('select');outcome.add(new Option('Escolhe o resultado que verificaste',''));outcome.add(new Option('A operação foi executada','completed'));outcome.add(new Option('A operação não foi executada','not_run'));const note=el('textarea');note.rows=2;note.placeholder='Como verificaste o resultado?';note.maxLength=2000;card.append(outcome,note);button(card,'Guardar verificação manual',async()=>{if(!outcome.value||!note.value.trim())throw Error('Indica o resultado e como o verificaste.');await checked(kind==='turn'?'resolve_chat_recovery':'resolve_agent_recovery',key,action.id,outcome.value,note.value.trim());await show(kind,key);});detail.append(card);}
  const evidence=el('details');evidence.append(el('summary','Ações e tentativas anteriores'));for(const action of j.actions)evidence.append(el('pre',action.name+' · '+action.state+'\n'+(action.output_preview||action.error||action.arguments_preview||''),'step-body'));for(const attempt of j.attempts)evidence.append(el('pre','Tentativa '+attempt.attempt+' · '+attempt.state+'\n'+(attempt.progress?.text||''),'step-body'));detail.append(evidence);
  if(eligible(j.state)){const input=el('textarea');input.rows=3;input.maxLength=12000;input.placeholder='Orientação adicional para continuar (opcional)';input.id='recovery-instruction';detail.append(input);
   async function resume(useCurrent){
    if(kind==='task'){await checked('resume_agent_task',key,input.value,useCurrent);window.dispatchEvent(new Event('agent-task-updated'));await show(kind,key);status.textContent='Tarefa retomada na mesma área isolada. Consulta o resultado na lista de tarefas.';}
    else{
     if(chatBusy)throw Error('Já existe uma conversa em execução.');host.classList.add('hidden');setBusy(true);showTyping(true);
     try{const result=await call('resume_chat_turn',key,input.value,useCurrent);if(!result.ok)showError(result.error);}finally{showTyping(false);setBusy(false);await loadConversation();}
    }
   }
   button(detail,j.unknown.length?'Retomar análise da tarefa':'Retomar trabalho',()=>resume(false));button(detail,'Retomar com modelo atual',()=>resume(true));
  }
 }
 window.openTaskRecovery=async key=>{try{await show('task',key);}catch(e){status.textContent=e.message;}};
 panel.addEventListener('toggle',()=>{if(panel.open)refresh().catch(e=>status.textContent=e.message);});
})();
