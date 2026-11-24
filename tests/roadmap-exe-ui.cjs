const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http'),net=require('node:net'),assert=require('node:assert/strict'),{spawn,execFileSync}=require('node:child_process');
(async()=>{
 const validationFixture=Boolean(process.env.STUDIO_VALIDATION_FIXTURE),root=path.resolve('.'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'studio-roadmap-')),project=path.join(temp,'project'),appdata=path.join(temp,'AppData'),settings=path.join(appdata,'gerador-imagens');fs.mkdirSync(project,{recursive:true});fs.mkdirSync(settings,{recursive:true});fs.writeFileSync(path.join(project,'a.txt'),'before\n');
 if(validationFixture){fs.writeFileSync(path.join(project,'maths.py'),'def add(a,b): return a-b\n');fs.mkdirSync(path.join(project,'tests'));fs.writeFileSync(path.join(project,'tests/test_maths.py'),'import unittest\nfrom maths import add\nclass TestAdd(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n');}
 const git=(...args)=>execFileSync('git',['-C',project,...args],{encoding:'utf8',windowsHide:true});git('init');git('config','user.name','Roadmap Test');git('config','user.email','test@example.invalid');git('add','.');git('commit','-m','Initial');let requests=0,captured=[];
 const model=http.createServer(async(req,res)=>{let raw='';for await(const chunk of req)raw+=chunk;
  if(req.method==='GET'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({data:[{id:'fixture'}]}));return;}
  try{
   const body=JSON.parse(raw);captured.push(body);assert.equal(req.url,'/v1/responses');assert.equal(req.headers.authorization,'Bearer fixture-key');requests++;
   const fn=(id,name,args)=>({type:'function_call',call_id:id,name,arguments:JSON.stringify(args)});let output;
   if(validationFixture){
    if(requests===1)output=[fn('blocked','executar_comando',{comando:'Write-Output forbidden'})];
    else if(requests===2||requests===5){if(requests===5)assert(JSON.stringify(body.input.at(-1)).includes('AssertionError'));output=[fn('read'+requests,'ler_codigo',{caminho:'maths.py'})];}
    else if(requests===3||requests===6){const read=JSON.parse(body.input.at(-1).output);output=[fn('edit'+requests,'aplicar_patch',{alteracoes:[{caminho:'maths.py',sha256:read.sha256,trecho_antigo:requests===3?'a-b':'a*b',trecho_novo:requests===3?'a*b':'a+b'}]})];}
    else output=[{type:'message',role:'assistant',content:[{type:'output_text',text:'Alteração pronta para validar.'}]}];
   }
   else if(requests===1)output=[fn('blocked','executar_comando',{comando:'Write-Output forbidden'})];
   else if(requests===2){assert(body.input.at(-1).output.includes('bloqueada'));output=[fn('read','ler_codigo',{caminho:'a.txt'})];}
   else if(requests===3){const read=JSON.parse(body.input.at(-1).output);output=[fn('edit','aplicar_patch',{alteracoes:[{caminho:'a.txt',sha256:read.sha256,trecho_antigo:'before',trecho_novo:'after'}]})];}
   else output=[{type:'message',role:'assistant',content:[{type:'output_text',text:'Proposta isolada pronta.'}]}];
   res.setHeader('Content-Type','text/event-stream');res.end('data: '+JSON.stringify({type:'response.completed',response:{status:'completed',output,usage:{input_tokens:10,output_tokens:3,total_tokens:13}}})+'\n\n');
  }catch(e){res.writeHead(500);res.end(String(e));}
 });await new Promise(r=>model.listen(0,'127.0.0.1',r));
 const port=await new Promise(r=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>r(p));});});
 fs.writeFileSync(path.join(settings,'config.json'),JSON.stringify({storage_layout:2,storage_root:root,projects:[{id:'p',name:'Roadmap',path:project}],active_project_id:'p',providers:[{id:'native',name:'OpenAI fixture',kind:'openai',api_key:'fixture-key',base_url:`http://127.0.0.1:${model.address().port}/v1`,models:[{id:'fixture',name:'Fixture',type:'chat'}]}],chat:{provider_id:'native',model_id:'fixture'},preferences:{agent:{enabled:true,scope:'project',approval:'auto'}}}));
 let app,browser,page;const kill=()=>{if(app){try{execFileSync('taskkill',['/PID',String(app.pid),'/T','/F'],{stdio:'ignore',windowsHide:true});}catch{}app=null;}};
 async function open(){app=spawn(process.env.STUDIO_TEST_SOURCE?'python':path.join(root,'dist/Studio de Media.exe'),process.env.STUDIO_TEST_SOURCE?['app.py']:[],{cwd:root,windowsHide:true,stdio:'ignore',env:{...process.env,APPDATA:appdata,WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port} --remote-allow-origins=*`}});let ready=false;
  for(let i=0;i<150;i++){try{const r=await fetch(`http://127.0.0.1:${port}/json/version`,{signal:AbortSignal.timeout(800)});if(r.ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,300));}assert(ready,'Exe CDP available');browser=await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  for(let i=0;i<50;i++){page=browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes('index.html'));if(page)break;await new Promise(r=>setTimeout(r,200));}assert(page);await page.waitForFunction(()=>window.pywebview?.api?.get_command_jobs);page.setDefaultTimeout(60000);
 }
 async function api(method,...args){const r=await page.evaluate(async({method,args})=>window.pywebview.api[method](...args),{method,args});assert(r.ok,method+': '+JSON.stringify(r));return r;}
 try{
  await open();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  assert.equal((await api('discover_provider_models','native')).models[0].id,'fixture');await api('set_agent_model','build','native','fixture');
  const task=(await api('start_agent_task','build',validationFixture?'Corrigir add em maths.py e confirmar com os testes do projeto.':'Substituir before por after em a.txt.')).task;let done;
  for(let i=0;i<200;i++){done=(await api('get_agent_workspace',task.id)).task;if(!['queued','running'].includes(done.state))break;await new Promise(r=>setTimeout(r,200));}
  assert.equal(done.state,'awaiting_review',JSON.stringify(done));assert.equal(requests,validationFixture?7:4);assert.equal(fs.readFileSync(path.join(project,'a.txt'),'utf8'),'before\n');assert.equal(done.proposal.isolation,'git-worktree');
  if(validationFixture){assert.equal(done.validation.state,'passed');assert(done.steps.some(s=>s.kind==='validation'&&!s.ok));assert(fs.readFileSync(path.join(project,'maths.py'),'utf8').includes('a-b'));}
  await page.click('#btn-agent-workspace');await page.getByRole('button',{name:'Ver resultado',exact:true}).click();await page.getByRole('button',{name:'Rever proposta isolada',exact:true}).click();
  if(validationFixture){await page.waitForFunction(()=>document.querySelector('#agent-task-detail').textContent.includes('Verificações: passed'));await page.screenshot({path:path.join(__dirname,'validation-proposal-exe-ui.png')});}
  await page.getByRole('button',{name:'Aplicar proposta ao projeto',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#agent-workspace-status').textContent.includes('aplicada'));
  if(validationFixture){assert(fs.readFileSync(path.join(project,'maths.py'),'utf8').includes('a+b'));await page.getByText('Verificações do projeto',{exact:true}).click();await page.getByRole('button',{name:'Executar selecionadas',exact:true}).click();let verified=false;for(let i=0;i<150;i++){const r=await api('get_project_validation');if(r.runs.some(run=>run.state==='passed')){verified=true;break;}await new Promise(r=>setTimeout(r,100));}assert(verified,'Manual validation passed');await page.getByRole('button',{name:'Detetar / atualizar verificações',exact:true}).click();await page.screenshot({path:path.join(__dirname,'validation-project-exe-ui.png')});}
  else assert.equal(fs.readFileSync(path.join(project,'a.txt'),'utf8'),'after\n');await page.click('#agent-workspace-close');
  const started=(await api('start_command_job',"[IO.File]::WriteAllText('job.txt','from-job'); Write-Output 'job-evidence-42'",'',20)).job;let job;
  for(let i=0;i<120;i++){job=(await api('get_command_jobs',started.id)).job;if(!['starting','running'].includes(job.state))break;await new Promise(r=>setTimeout(r,100));}
  assert.equal(job.state,'completed',JSON.stringify(job));assert(job.output.includes('job-evidence-42'));assert(job.checkpoint.file_count>=1);await api('restore_code_checkpoint',job.checkpoint.id,false);assert(!fs.existsSync(path.join(project,'job.txt')));await api('restore_code_checkpoint',job.checkpoint.id,true);
  const long=(await api('start_command_job','Start-Sleep -Seconds 30','',40)).job;await api('cancel_command_job',long.id);for(let i=0;i<100;i++){if(!['starting','running'].includes((await api('get_command_jobs',long.id)).job.state))break;await new Promise(r=>setTimeout(r,100));}
  await page.click('#btn-workspace-operations');await page.getByRole('button',{name:'Ver saída',exact:true}).last().click();await page.getByText('Git: alterações, branches e worktrees',{exact:true}).click();await page.getByRole('button',{name:'Atualizar Git',exact:true}).click();
  const changedFile=validationFixture?'maths.py':'a.txt',gitState=(await api('get_git_workspace')).git;assert(gitState.changes.some(f=>f.path===changedFile));await api('git_workspace_action','stage',{paths:[changedFile]});await api('git_workspace_action','commit',{message:'Isolated proposal validated'});await api('git_workspace_action','branch',{branch:'codex/roadmap'});
  await page.getByText('Limites por pedido',{exact:true}).click();await page.locator('[data-limit="tokens"]').fill('12345');await page.getByRole('button',{name:'Guardar limites',exact:true}).click();assert.equal((await api('get_execution_limits')).limits.tokens,12345);await page.screenshot({path:path.join(__dirname,'roadmap-exe-ui.png')});assert.deepEqual(errors,[]);
  await browser.close();browser=null;kill();await new Promise(r=>setTimeout(r,600));await open();assert.equal((await api('get_command_jobs',started.id)).job.state,'completed');assert.equal((await api('review_agent_proposal',task.id)).proposal.state,'applied');
  const result={ok:true,requests,task:done.state,job:job.state,checkpoint:job.checkpoint.id,restart:true,project,isolation:done.proposal.isolation,validation:done.validation.state,corrected_failed_tests:validationFixture};fs.writeFileSync(path.join(__dirname,validationFixture?'validation-exe-result.json':'roadmap-exe-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{if(browser)await browser.close();kill();await new Promise(r=>model.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
