const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),path=require('node:path'),{pathToFileURL}=require('node:url');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
   window.inventoryCalls=[];
   window.pywebview={api:{get_state:async()=>({ok:true,providers:[],projects:[],conversations:[]}),get_conversation:async()=>({ok:true,messages:[]}),get_tools_inventory:async()=>({ok:true,bench:[{key:'Pillow',name:'Pillow',category:'Imagem',installed:true,status:'Instalado',path:'C:/app/Ferramentas/Pillow'},{key:'Lemon',name:'Lemon Serial Monitor',category:'Drivers opcionais',installed:false,status:'Integração preparada · dependência em falta',note:'Driver de kernel com assinatura de teste.',path:'C:/app/Ferramentas/Lemon'}],folder_tools:[{id:'pillow-id',path:'C:/app/Ferramentas/Pillow',enabled:true,approval:'each'},{id:'rea-id',name:'REA',path:'C:/app/Ferramentas/REA',enabled:true,state:{}}],tools:[{name:'browser_navigate',description:'Navegar no browser'}],mcp_servers:[]}),test_folder_tool:async id=>{window.inventoryCalls.push(['test',id]);return {ok:true,count:4};},configure_bench_executable:async id=>{window.inventoryCalls.push(['configure',id]);return {ok:true};},open_bench_folder:async id=>{window.inventoryCalls.push(['open',id]);return {ok:true};},set_folder_tool:async (...a)=>{window.inventoryCalls.push(['set',...a]);return {ok:true};}}};
  });
  await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
  await page.click('#btn-tools');await page.waitForSelector('#tools-inventory .mcp-card');
  assert.equal(await page.locator('#tools-inventory .mcp-card').count(),4);
  await page.fill('#tools-search','assinatura');assert.equal(await page.locator('#tools-inventory .mcp-card').count(),1);
  await page.check('#tools-only-installed');assert.equal(await page.locator('#tools-inventory .mcp-card').count(),0);
  await page.uncheck('#tools-only-installed');await page.fill('#tools-search','');await page.selectOption('#tools-category','Imagem');
  const card=page.locator('#tools-inventory .mcp-card');await card.getByRole('button',{name:'Testar ligação MCP'}).click();
  await card.getByRole('button',{name:'Configurar executável'}).click();await card.getByRole('button',{name:'Abrir pasta',exact:true}).click();
  assert.deepEqual(await page.evaluate(()=>window.inventoryCalls),[['test','pillow-id'],['configure','Pillow'],['open','Pillow']]);
  // a escolha de aprovação veio das definições para aqui
  assert.equal(await card.getByLabel('Aprovação de Pillow').inputValue(),'each');await card.getByLabel('Aprovação de Pillow').selectOption('auto');
  await page.waitForFunction(()=>window.inventoryCalls.some(c=>c[0]==='set'&&c[1]==='pillow-id'&&c[2]===null&&c[3]==='auto'));
  await page.click('#tools-close');await page.click('#btn-settings');assert.equal(await page.locator('#folder-tools, #folder-install-rea').count(),0,'a secção «Ferramentas em pastas» saiu das definições');
  await page.keyboard.press('Escape');await page.click('#btn-tools');await page.waitForSelector('#tools-inventory .mcp-card');
  await page.selectOption('#tools-category','');await page.screenshot({path:'tests/tools-inventory-ui.png'});
  await page.press('#tools-search','Escape');assert.equal(await page.locator('#tools-modal').isVisible(),false);assert.deepEqual(errors,[]);
  console.log('PASS: inventory button, local/builtin tools, dependencies, filters, test/configure/open actions, approval choice, settings section removed, keyboard close.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
