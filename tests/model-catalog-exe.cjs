const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),net=require('node:net'),os=require('node:os'),assert=require('node:assert/strict');
(async()=>{
  const root=process.env.MEISTERCODE_FINAL||'C:/Program Files/MeisterCode';
  const artifacts=process.env.CATALOG_ARTIFACTS||path.join(os.tmpdir(),'meistercode-catalog');fs.mkdirSync(artifacts,{recursive:true});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
  const app=spawn(path.join(root,'MeisterCode.exe'),[],{cwd:root,windowsHide:true,stdio:'ignore',env:{...process.env,WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port} --remote-allow-origins=*`}});
  let browser;
  try{
    let ready=false;
    for(let i=0;i<150;i++){try{ready=(await fetch(`http://127.0.0.1:${port}/json/version`,{signal:AbortSignal.timeout(800)})).ok;if(ready)break;}catch{}await new Promise(r=>setTimeout(r,300));}
    assert(ready,'CDP not ready');browser=await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
    let page;for(let i=0;i<60;i++){page=browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes('index.html'));if(page)break;await new Promise(r=>setTimeout(r,200));}assert(page);
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.waitForFunction(()=>window.pywebview?.api?.get_state);
    await page.waitForFunction(()=>document.querySelector('#sel-model').options.length>2);
    const state=await page.evaluate(()=>window.pywebview.api.get_state());assert(state.ok);assert.equal(state.app_version,'0.7.3');
    const provider=state.providers.find(p=>p.kind==='openrouter');assert(provider.catalog.length>100);
    await page.selectOption('#sel-type','code');assert(await page.locator('#sel-model option').count()>10);
    const allowed=provider.models.filter(m=>m.type==='chat'&&m.catalog_available!==false&&m.categories.includes('code')).map(m=>m.id);
    assert((await page.locator('#sel-model option').evaluateAll(nodes=>nodes.map(n=>n.value).filter(Boolean))).every(v=>allowed.includes(v.split('::')[1])));
    await page.evaluate(async pid=>{renderConversation([]);await discoverModels(pid);},provider.id);
    await page.selectOption('#catalog-category','video');assert(await page.locator('.catalog-row').count()>0);
    await page.screenshot({path:path.join(artifacts,'catalog-video.png')});
    await page.selectOption('#catalog-category','embeddings');assert.match(await page.locator('.catalog-row').first().innerText(),/Só catálogo/);
    assert.deepEqual(errors,[]);
    console.log('PASS: installed 0.7.3, live cached catalog, Code filter, video category, catalog-only embeddings, no JS errors');
  }finally{
    if(browser)await browser.close().catch(()=>{});
    try{execFileSync('taskkill',['/PID',String(app.pid),'/T','/F'],{stdio:'ignore',windowsHide:true});}catch{}
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
