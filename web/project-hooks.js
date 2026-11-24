"use strict";
(()=>{
 const node=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n;};
 const modal=document.querySelector('#agent-workspace-modal'),section=node('details');section.id='project-hooks-panel';section.append(node('summary','Hooks e regras do projeto'));modal.querySelector('.modal-body').prepend(section);
 const status=node('p','','hint'),editor=node('textarea'),runs=node('div');editor.id='project-hooks-editor';editor.rows=16;editor.style.width='100%';editor.style.fontFamily='monospace';editor.setAttribute('aria-label','Configuração JSON dos hooks');
 section.append(node('p','Eventos: before_tool, after_tool e task_end. Comandos usam argv, cwd relativo e timeout de 1 a 300 segundos. on_failure: block ou warn. deny_tools aceita padrões como mcp_*. A configuração ativada é fixada no início de cada pedido.','hint'),status,editor);
 let dirty=false;editor.oninput=()=>dirty=true;
 async function checked(method,...args){const r=await call(method,...args);if(!r.ok)throw Error(r.error);return r;}
 function button(label,action){const b=node('button',label,'btn ghost small');b.type='button';b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){status.textContent=e.message;}finally{b.disabled=false;}};section.append(b);}
 function render(r,replace=false){const c=r.configuration;status.textContent=r.workspace+' · '+(c.active?'Configuração ativada':'Configuração inativa ou alterada; requer ativação');if(replace||!dirty){editor.value=c.text;dirty=false;}runs.replaceChildren();for(const run of r.runs){const d=node('details');d.append(node('summary',new Date(run.created_at*1000).toLocaleString('pt-PT')+' · '+run.event+' / '+run.hook+' · '+run.state),node('pre',(run.output||'')+'\n'+JSON.stringify(run.argv),'step-body'));runs.append(d);}}
 button('Atualizar hooks',async()=>render(await checked('get_project_hooks')));
 button('Guardar e ativar hooks',async()=>render(await checked('save_project_hooks',editor.value,true),true));
 button('Desativar hooks',async()=>render(await checked('save_project_hooks',editor.value,false)));
 button('Inserir exemplo',()=>{editor.value=JSON.stringify({version:1,deny_tools:['mcp_exemplo_*'],hooks:[{id:'verificar',event:'task_end',argv:['python','-m','unittest','discover','-s','tests'],timeout:120,on_failure:'block',repeat_on_resume:true}]},null,2);dirty=true;});section.append(runs);
 section.addEventListener('toggle',()=>{if(section.open)checked('get_project_hooks').then(render).catch(e=>status.textContent=e.message);});
 new MutationObserver(()=>{if(!modal.classList.contains('hidden')&&section.open){dirty=false;checked('get_project_hooks').then(r=>render(r,true)).catch(e=>status.textContent=e.message);}}).observe(modal,{attributes:true,attributeFilter:['class']});
})();
