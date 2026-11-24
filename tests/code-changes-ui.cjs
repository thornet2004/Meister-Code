const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),path=require('node:path'),{pathToFileURL}=require('node:url');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1200,height:850}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
   let state='applied';window.codeCalls=[];
   window.pywebview={api:{get_state:async()=>({ok:true,providers:[],projects:[],conversations:[]}),get_conversation:async()=>({ok:true,messages:[]}),get_code_changes:async id=>({ok:true,workspace:'C:/project',lsp:[{name:'python',installed:true}],checkpoints:[{id:'abc',state,title:'Corrigir código',created_at:'2026-11-06T12:00:00Z',file_count:1}],checkpoint:id?{id,state,title:'Corrigir código',files:[{path:'C:/project/a.py',diff:'-x = "wrong"\n+x = 42',conflict:window.codeConflict||false}]}:null}),restore_code_checkpoint:async(id,redo)=>{window.codeCalls.push([id,redo]);state=redo?'applied':'undone';return {ok:true};},get_code_diagnostics:async p=>({ok:true,result:{status:'complete',diagnostics:[{line:1,column:4,severity:'error',message:'Type mismatch'}]}})}};
  });
  await page.goto(pathToFileURL(path.resolve('web/index.html')).href);await page.click('#btn-code-changes');
  await page.getByRole('button',{name:'Ver alterações',exact:true}).click();assert.match(await page.textContent('#code-checkpoint-preview'),/x = 42/);
  await page.getByRole('button',{name:'Desfazer alterações',exact:true}).click();await page.getByRole('button',{name:'Refazer alterações',exact:true}).click();assert.deepEqual(await page.evaluate(()=>window.codeCalls),[['abc',false],['abc',true]]);
  await page.fill('#code-lsp-path','a.py');await page.click('#code-lsp-run');await page.waitForFunction(()=>document.querySelector('#code-diagnostics').textContent.includes('Type mismatch'));
  await page.evaluate(()=>window.codeConflict=true);await page.click('#code-refresh');assert(await page.getByRole('button',{name:'Desfazer alterações',exact:true}).isDisabled());
  await page.screenshot({path:'tests/code-changes-ui.png'});await page.press('#code-lsp-path','Escape');assert(!(await page.locator('#code-modal').isVisible()));assert.deepEqual(errors,[]);console.log('PASS: review diffs, undo/redo, conflict protection, diagnostics and keyboard close.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
