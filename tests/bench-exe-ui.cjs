// Valida o bridge e os recursos do executável real, em dados temporários.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'..');const data=fs.mkdtempSync(path.join(os.tmpdir(),'studio-bench-exe-'));
 const configPath=path.join(data,'gerador-imagens');fs.mkdirSync(configPath);
 fs.writeFileSync(path.join(configPath,'config.json'),JSON.stringify({storage_layout:2,storage_root:root,providers:[],projects:[{id:'smoke',name:'Teste bancada',path:data}],active_project_id:'smoke'}));
 const port=await new Promise(resolve=>{const server=net.createServer();server.listen(0,'127.0.0.1',()=>{const port=server.address().port;server.close(()=>resolve(port));});});
 let app,browser;
 try {
  app=spawn(path.join(root,'dist/Studio de Media.exe'),[],{cwd:root,windowsHide:true,stdio:'ignore',env:{...process.env,APPDATA:data,WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port} --remote-allow-origins=*`}});
  const end=Date.now()+45000;let ready=false;
  while(Date.now()<end){try {const response=await fetch(`http://127.0.0.1:${port}/json/version`,{signal:AbortSignal.timeout(1000)});if(response.ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,300));}
  assert(ready,'WebView2 CDP não arrancou.');
  browser=await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  let page;
  for(let i=0;i<50;i++){page=browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes('index.html'));if(page)break;await new Promise(r=>setTimeout(r,200));}
  assert(page,'Página principal não encontrada.');
  await page.waitForFunction(()=>window.pywebview?.api?.get_tools_inventory);
  await page.click('#btn-tools');await page.waitForSelector('#tools-inventory .mcp-card');
  const result=await page.evaluate(()=>window.pywebview.api.get_tools_inventory());assert(result.ok,result.error);
  assert.equal(result.bench.length,27);assert.equal(result.bench.filter(t=>t.installed).length,25);
  assert.equal(result.bench.filter(t=>!t.installed).map(t=>t.key).sort().join(','),'Lemon,PortSniffer');
  const tests=[];
  for(const key of ['Pillow','ImageMagickMCP','GIMP']){
   const tool=result.folder_tools.find(t=>t.path.replaceAll('\\','/').endsWith('/'+key));assert(tool,key);
   const tested=await page.evaluate(id=>window.pywebview.api.test_folder_tool(id),tool.id);assert(tested.ok,JSON.stringify(tested));tests.push({key,count:tested.count});
  }
  await page.click('#tools-refresh');
  await page.waitForFunction(()=>document.querySelector('#tools-inventory').textContent.includes('57 operações'));
  await page.fill('#tools-search','');await page.selectOption('#tools-category','Imagem');
  await page.screenshot({path:path.join(__dirname,'tools-inventory-exe.png')});
  const box=await page.locator('#btn-tools').boundingBox();assert(box&&box.x>=0&&box.x+box.width<=1200,'Botão fora da janela.');
  const report={packaged_exe:true,bench_integrations:result.bench.length,installed:25,driver_dependencies:['Lemon','PortSniffer'],mcp:tests};
  fs.writeFileSync(path.join(__dirname,'bench-exe-result.json'),JSON.stringify(report,null,2));console.log('PASS',JSON.stringify(report));
 }finally{
  if(browser)await browser.close();
  if(app?.pid){try{execFileSync('taskkill',['/PID',String(app.pid),'/T','/F'],{stdio:'ignore'});}catch{}}
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
