"use strict";
(()=>{
 const node=(tag,value='',cls='')=>{const n=document.createElement(tag);n.textContent=value;n.className=cls;return n;};
 const modal=document.querySelector('#agent-workspace-modal'),body=modal.querySelector('.modal-body');
 const section=node('details');section.id='project-validation-panel';section.append(node('summary','Verificações do projeto'));body.prepend(section);
 const message=node('p','','hint'),choices=node('div'),runs=node('div');section.append(message,choices,runs);let timer=null,busy=false;
 async function checked(method,...args){const r=await call(method,...args);if(!r.ok)throw Error(r.error);return r;}
 function button(parent,label,action){const b=node('button',label,'btn ghost small');b.type='button';b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){message.textContent=e.message;}finally{b.disabled=false;}};parent.append(b);return b;}
 button(section,'Detetar / atualizar verificações',refresh);
 button(section,'Executar selecionadas',async()=>{const ids=[...choices.querySelectorAll('input:checked')].map(n=>n.value);if(!ids.length)throw Error('Seleciona pelo menos uma verificação.');await checked('start_project_validation',ids,false);await refresh();});
 button(section,'Preparar dependências do projeto',async()=>{await checked('start_project_validation',null,true);await refresh();});
 async function refresh(){
  if(busy)return;busy=true;clearTimeout(timer);
  try{
   const r=await checked('get_project_validation'),plan=r.plan,oldChoices=choices.childElementCount?new Set([...choices.querySelectorAll('input:checked')].map(n=>n.value)):null;message.textContent=plan.warnings.join(' ');choices.replaceChildren();
   for(const check of plan.checks){const label=node('label','','validation-choice'),input=node('input');input.type='checkbox';input.value=check.id;input.checked=oldChoices?oldChoices.has(check.id):check.recommended;input.disabled=!check.available;label.append(input,document.createTextNode(check.label+(check.available?'':' · runtime em falta')));choices.append(label);}
   runs.replaceChildren();
   for(const run of r.runs){const d=node('details');d.append(node('summary',new Date(run.created_at*1000).toLocaleString('pt-PT')+' · '+(run.prepare?'Preparação':'Verificação')+' · '+run.state));
    if(['queued','running'].includes(run.state))button(d,'Cancelar verificação',async()=>{await checked('cancel_project_validation',run.id);await refresh();});
    for(const check of run.checks)d.append(node('pre',check.label+' · '+check.state+'\n'+(check.output||check.message||''),'step-body'));if(run.message)d.append(node('p',run.message,'notice warn'));runs.append(d);
   }
   if(section.open&&!modal.classList.contains('hidden')&&r.runs.some(r=>['queued','running'].includes(r.state)))timer=setTimeout(()=>refresh().catch(e=>message.textContent=e.message),1500);
  }finally{busy=false;}
 }
 section.addEventListener('toggle',()=>{clearTimeout(timer);if(section.open)refresh().catch(e=>message.textContent=e.message);});
 new MutationObserver(()=>{clearTimeout(timer);if(section.open&&!modal.classList.contains('hidden'))refresh().catch(e=>message.textContent=e.message);}).observe(modal,{attributes:true,attributeFilter:['class']});
})();
