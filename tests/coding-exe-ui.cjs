const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),http=require('node:http'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'studio-code-exe-'));
 const settings=path.join(data,'gerador-imagens'),project=path.join(data,'project');fs.mkdirSync(settings);fs.mkdirSync(project);
 const file=path.join(project,'bad.py');fs.writeFileSync(file,'x: int = "wrong"\n');let calls=0,seenPatch;
 const model=http.createServer(async(req,res)=>{
  try{
   let raw='';for await(const part of req)raw+=part;const request=JSON.parse(raw);calls++;
   let message;
   const fn=(name,args,id)=>({role:'assistant',content:null,tool_calls:[{id,type:'function',function:{name,arguments:JSON.stringify(args)}}]});
   if(calls===1){assert(request.tools.some(t=>t.function.name==='aplicar_patch'));message=fn('ler_codigo',{caminho:'bad.py'},'read-code');}
   else if(calls===2){const reading=JSON.parse(request.messages.at(-1).content);message=fn('aplicar_patch',{alteracoes:[{caminho:'bad.py',sha256:reading.sha256,trecho_antigo:'x: int = "wrong"',trecho_novo:'x: int = 42'}]},'patch-code');}
   else {seenPatch=JSON.parse(request.messages.at(-1).content);assert(seenPatch.checkpoint_id,JSON.stringify(seenPatch));message={role:'assistant',content:'Código corrigido e verificado.'};}
   res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({choices:[{message,finish_reason:message.tool_calls?'tool_calls':'stop'}]}));
  }catch(e){res.writeHead(500);res.end(String(e));}
 });
 await new Promise(r=>model.listen(0,'127.0.0.1',r));
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
 fs.writeFileSync(path.join(settings,'config.json'),JSON.stringify({storage_layout:2,storage_root:root,providers:[{id:'fixture',name:'Modelo local de teste',kind:'openrouter',api_key:'fixture',base_url:`http://127.0.0.1:${model.address().port}/v1`,models:[{id:'fixture',name:'Fixture',type:'chat'}]}],chat:{provider_id:'fixture',model_id:'fixture'},preferences:{agent:{enabled:true,scope:'project',approval:'auto'}},projects:[{id:'smoke',name:'Teste código',path:project}],active_project_id:'smoke'}));
 let app,browser;
 try{
  app=spawn(path.join(root,'dist/Studio de Media.exe'),[],{cwd:root,windowsHide:true,stdio:'ignore',env:{...process.env,APPDATA:data,WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port} --remote-allow-origins=*`}});
  let ready=false;const end=Date.now()+45000;
  while(Date.now()<end){try{const r=await fetch(`http://127.0.0.1:${port}/json/version`,{signal:AbortSignal.timeout(1000)});if(r.ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,300));}assert(ready);
  browser=await chromium.connectOverCDP(`http://127.0.0.1:${port}`);let page;
  for(let i=0;i<50;i++){page=browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes('index.html'));if(page)break;await new Promise(r=>setTimeout(r,200));}
  assert(page);page.setDefaultTimeout(90000);await page.waitForFunction(()=>window.pywebview?.api?.get_code_changes);
  const inventory=await page.evaluate(()=>window.pywebview.api.get_tools_inventory());assert(inventory.ok);assert.equal(inventory.language_servers.length,2);assert(inventory.language_servers.every(s=>s.installed));
  const before=await page.evaluate(()=>window.pywebview.api.get_code_diagnostics('bad.py'));assert(before.ok,JSON.stringify(before));assert(before.result.diagnostics.some(d=>d.severity==='error'),JSON.stringify(before));
  const chat=await page.evaluate(()=>window.pywebview.api.chat('Corrige o tipo deste ficheiro com um patch.'));assert(chat.ok,JSON.stringify(chat));assert.equal(calls,3);assert.equal(fs.readFileSync(file,'utf8'),'x: int = 42\n');
  assert.equal(seenPatch.diagnostics[0].status,'complete');assert(!seenPatch.diagnostics[0].diagnostics.some(d=>d.severity==='error'));
  await page.click('#btn-code-changes');await page.getByRole('button',{name:'Ver alterações',exact:true}).click();await page.getByRole('button',{name:'Desfazer alterações',exact:true}).click();await page.getByRole('button',{name:'Refazer alterações',exact:true}).waitFor();assert.equal(fs.readFileSync(file,'utf8'),'x: int = "wrong"\n');
  await page.getByRole('button',{name:'Refazer alterações',exact:true}).click();await page.getByRole('button',{name:'Desfazer alterações',exact:true}).waitFor();assert.equal(fs.readFileSync(file,'utf8'),'x: int = 42\n');
  await page.fill('#code-lsp-path','bad.py');await page.click('#code-lsp-run');await page.waitForFunction(()=>document.querySelector('#code-diagnostics').textContent.includes('Sem diagnósticos'));
  await page.screenshot({path:path.join(__dirname,'coding-exe-ui.png')});
  const report={packaged_exe:true,real_lsp:true,model_tool_cycles:calls,patch_applied:true,checkpoint_undo_redo:true,diagnostics_after_fix:seenPatch.diagnostics};fs.writeFileSync(path.join(__dirname,'coding-exe-result.json'),JSON.stringify(report,null,2));console.log('PASS: packaged model tool loop, guarded patch, real LSP, review and undo/redo.');
 }finally{
  if(browser)await browser.close();if(app?.pid){try{execFileSync('taskkill',['/PID',String(app.pid),'/T','/F'],{stdio:'ignore'});}catch{}}await new Promise(r=>model.close(r));
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
