"use strict";
(()=>{
 const el=(tag,value='',cls='')=>{const n=document.createElement(tag);n.textContent=value;n.className=cls;return n;};
 const launch=el('button','Processos / Git','btn ghost small');launch.id='btn-workspace-operations';document.querySelector('#btn-agent-workspace').after(launch);
 const modal=el('div','','modal-overlay hidden');modal.id='workspace-operations-modal';modal.setAttribute('role','dialog');modal.setAttribute('aria-modal','true');modal.setAttribute('aria-label','Processos, Git e limites');
 const box=el('div','','modal wide'),head=el('div','','modal-head'),body=el('div','','modal-body'),message=el('p','','hint');message.id='operations-status';message.setAttribute('role','status');
 head.append(el('h3','Processos, Git e limites'));box.append(head,body);modal.append(box);document.body.append(modal);let timer=null,selected='',working=false;
 const status=t=>message.textContent=t;
 async function checked(method,...args){const r=await call(method,...args);if(!r.ok)throw Error(r.error);return r;}
 function button(parent,label,fn){const b=el('button',label,'btn ghost small');b.type='button';b.onclick=async()=>{if(working)return;working=true;b.disabled=true;try{await fn();}catch(e){status(e.message);}finally{working=false;b.disabled=false;}};parent.append(b);return b;}
 const close=()=>{modal.classList.add('hidden');clearTimeout(timer);launch.focus();};button(head,'Fechar',close);body.append(message);
 modal.onclick=e=>{if(e.target===modal)close();};document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!modal.classList.contains('hidden'))close();});
 const jobsSection=el('section');jobsSection.append(el('h4','PowerShell em segundo plano'),el('p','O histórico e a saída são guardados. Depois de uma interrupção, voltar a executar cria um novo processo.','hint'));
 const form=el('form'),command=el('textarea'),cwd=el('input'),timeout=el('input');command.id='job-command';command.rows=3;command.placeholder='Comando PowerShell';command.required=true;command.setAttribute('aria-label','Comando PowerShell');cwd.placeholder='Pasta de trabalho (opcional)';cwd.setAttribute('aria-label','Pasta de trabalho');timeout.type='number';timeout.min='1';timeout.max='86400';timeout.value='3600';timeout.setAttribute('aria-label','Tempo máximo em segundos');
 form.append(command,cwd,timeout);button(form,'Iniciar processo',async()=>{const r=await checked('start_command_job',command.value,cwd.value,Number(timeout.value));selected=r.job.id;await refreshJobs();});form.onsubmit=e=>e.preventDefault();jobsSection.append(form);
 const jobs=el('div','','tools-inventory'),output=el('pre','','step-body');output.id='job-output';jobsSection.append(jobs,output);button(jobsSection,'Atualizar processos',refreshJobs);body.append(jobsSection);
 const active=s=>['starting','running','cancelling'].includes(s);
 async function refreshJobs(){
  clearTimeout(timer);const r=await checked('get_command_jobs',selected);jobs.replaceChildren();
  for(const job of r.jobs){const row=el('article','','mcp-card');row.append(el('strong',job.command),el('p',job.state+' · PID '+(job.pid||'—')+' · '+job.cwd,'hint'));
   button(row,'Ver saída',async()=>{selected=job.id;await refreshJobs();});
   if(active(job.state))button(row,'Cancelar processo',async()=>{await checked('cancel_command_job',job.id);await refreshJobs();});
   else button(row,'Preparar nova execução',async()=>{command.value=job.command;cwd.value=job.cwd;timeout.value=job.timeout;command.focus();status('Comando carregado. Clica em Iniciar processo para o voltar a executar.');});jobs.append(row);
  }
  output.textContent=r.job?(r.job.output||r.job.message||'A aguardar saída…')+'\n'+(r.job.checkpoint?JSON.stringify(r.job.checkpoint,null,2):''):'';
  if(!modal.classList.contains('hidden')&&r.jobs.some(j=>active(j.state)))timer=setTimeout(()=>refreshJobs().catch(e=>status(e.message)),1500);
 }
 const gitSection=el('details');gitSection.append(el('summary','Git: alterações, branches e worktrees'));body.append(gitSection);
 const gitInfo=el('p','','hint'),changes=el('div'),diff=el('pre','','step-body'),history=el('pre','','step-body');diff.id='git-diff';gitSection.append(gitInfo,changes,diff);
 const picked=()=>[...changes.querySelectorAll('input:checked')].map(n=>n.value);
 async function act(operation,options){const r=await checked('git_workspace_action',operation,options);if(operation==='diff')diff.textContent=r.result.text||'Sem diferenças de ficheiros já acompanhados.';else{status(r.result.text||'Operação concluída.');await refreshGit();}}
 button(gitSection,'Atualizar Git',refreshGit);button(gitSection,'Ver diferenças',()=>act('diff',{paths:picked()}));button(gitSection,'Ver staged',()=>act('diff',{paths:picked(),staged:true}));button(gitSection,'Stage selecionados',()=>act('stage',{paths:picked()}));button(gitSection,'Retirar de staged',()=>act('unstage',{paths:picked()}));
 const commit=el('input');commit.placeholder='Mensagem de commit';commit.id='git-commit-message';gitSection.append(commit);button(gitSection,'Criar commit dos ficheiros staged',()=>act('commit',{message:commit.value}));
 const branch=el('input');branch.placeholder='Nome da branch';branch.id='git-branch-name';gitSection.append(branch);button(gitSection,'Criar branch',()=>act('branch',{branch:branch.value}));button(gitSection,'Trocar para branch',()=>act('switch',{branch:branch.value}));
 const worktree=el('input');worktree.placeholder='Caminho absoluto de nova worktree';gitSection.append(worktree);button(gitSection,'Criar worktree da branch',()=>act('worktree',{branch:branch.value,path:worktree.value}));
 const conflict=el('section'),editor=el('textarea');editor.rows=12;editor.id='git-conflict-editor';conflict.classList.add('hidden');const conflictTitle=el('h4');conflict.append(conflictTitle,editor);let conflictPath='',conflictSha='';button(conflict,'Guardar resolução com checkpoint',async()=>{await checked('save_git_conflict',conflictPath,editor.value,conflictSha);status('Resolução guardada. Verifica o ficheiro e adiciona-o a staged quando estiver resolvido.');conflict.classList.add('hidden');await refreshGit();});gitSection.append(conflict,history);
 async function refreshGit(){
  const r=await checked('get_git_workspace');gitInfo.textContent=r.git.root+' · '+r.git.branch+' · Branches: '+r.git.branches.join(', ');changes.replaceChildren();
  for(const file of r.git.changes){const row=el('div'),label=el('label'),check=el('input');check.type='checkbox';check.value=file.path;label.append(check,document.createTextNode(file.status+' '+file.path));row.append(label);
   if(file.conflict)button(row,'Resolver '+file.path,async()=>{const r=await checked('read_git_conflict',file.path);conflictPath=file.path;conflictSha=r.sha256;editor.value=r.content;conflictTitle.textContent=file.path;conflict.classList.remove('hidden');});changes.append(row);
  }history.textContent=r.git.history+'\n\nWorktrees\n'+r.git.worktrees;
 }
 const limits=el('details');limits.append(el('summary','Limites por pedido'));const fields={};
 for(const [key,label] of Object.entries({seconds:'Tempo (segundos)',tokens:'Tokens',tool_calls:'Chamadas de ferramentas',cost:'Custo máximo estimado (0 desativa)',input_per_million:'Preço de entrada por milhão',output_per_million:'Preço de saída por milhão'})){const field=el('label',label,'field'),input=el('input');input.type='number';input.min='0';input.step='any';input.dataset.limit=key;fields[key]=input;field.append(input);limits.append(field);}
 limits.append(el('p','Os preços usam a moeda que configurares. O limite de custo é uma estimativa por pedido; os limites são avaliados entre chamadas e podem ser ultrapassados pela resposta em curso. Comandos têm o seu próprio timeout.','hint'));
 button(limits,'Guardar limites',async()=>{await checked('set_execution_limits',Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,Number(v.value)])));status('Limites guardados.');});body.append(limits);
 launch.onclick=async()=>{modal.classList.remove('hidden');status('');try{await refreshJobs();const r=await checked('get_execution_limits');for(const [key,value] of Object.entries(r.limits))if(fields[key])fields[key].value=value;}catch(e){status(e.message);}};
})();
