const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {pathToFileURL}=require('node:url');const path=require('node:path');const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1400,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
   let servers=[];window.mcpCalls=[];
   const state=()=>({ok:true,providers:[],projects:[],conversations:[]});
   window.pywebview={api:{get_state:async()=>state(),get_conversation:async()=>({ok:true,messages:[]}),
    get_tool_catalog:async()=>({ok:true,tools:servers.filter(s=>s.enabled).map(s=>({name:'mcp_demo_tool',description:'MCP '+s.name})),mcp_servers:servers.map(s=>({...s,connected:s.enabled,tool_count:s.enabled?1:0,protocol:'2026-07-28'})),
     mcp_presets:[
      {kind:'linear',name:'Linear',mode:'remote',transport:'http',url:'https://mcp.linear.app/mcp',command:'',args:[],description:'Issues, projetos e tarefas no Linear.',profiles:['coding','work'],help:'',installed:true,node:true,server_id:'',enabled:false,approval:'each',settings:{},fields:[],job:{state:'idle',message:''}},
      {kind:'playwright',name:'Playwright',mode:'node',transport:'stdio',url:'',command:'node',args:['cli.js','--headless'],description:'Navegador de testes próprio.',profiles:['coding'],help:'',installed:false,node:true,server_id:'',enabled:false,approval:'each',settings:{},fields:[],job:{state:'idle',message:''}},
      {kind:'brave',name:'Brave Search',mode:'bundled',transport:'stdio',command:'studio.exe',args:['--integration-server','brave'],description:'Pesquisa web.',profiles:['research'],installed:true,node:true,settings:{},fields:[{key:'api_key',label:'Chave Brave',secret:true,required:true}]},
      {kind:'mysql',name:'MySQL',mode:'bundled',transport:'stdio',command:'studio.exe',args:['--integration-server','mysql'],description:'SQL.',profiles:['coding'],installed:true,node:true,settings:{},fields:[{key:'host',label:'Servidor',default:'localhost'},{key:'password',label:'Password',secret:true},{key:'readonly',label:'Permissões',default:'true',options:[['true','Só leitura'],['false','Permitir escrita SQL']]}]}
     ],mcp_profile:'all'}),
    save_mcp_server:async data=>{window.mcpCalls.push(['save',data]);const old=servers.find(s=>s.id===data.id)||{};const item={...old,...data,id:data.id||'demo-id'};item.env_names=data.env?Object.keys(data.env):old.env_names||[];item.header_names=data.headers?Object.keys(data.headers):old.header_names||[];delete item.env;delete item.headers;servers=servers.filter(s=>s.id!==item.id).concat(item);return {ok:true,servers};},
    test_mcp_server:async id=>{window.mcpCalls.push(['test',id]);return {ok:true,server:{tool_count:1}};},
    save_mcp_preset:async(kind,data)=>{window.mcpCalls.push(['preset-save',kind,data]);const item={...data,id:'native-'+kind};servers.push(item);return {ok:true,servers,server_id:item.id};},
    remove_mcp_server:async id=>{window.mcpCalls.push(['remove',id]);servers=servers.filter(s=>s.id!==id);return {ok:true,servers};},
    add_mcp_demo:async()=>{window.mcpCalls.push(['demo']);servers.push({id:'local',name:'Demonstração local',transport:'stdio',enabled:true,approval:'auto',args:[],env_names:[],header_names:[]});return {ok:true,servers};},
    start_mcp_oauth:async id=>{window.mcpCalls.push(['oauth',id]);return {ok:true,job:{state:'waiting',message:'Autoriza no browser'}};},
    mcp_oauth_status:async id=>{servers.find(s=>s.id===id).oauth={linked:true};return {ok:true,job:{state:'connected',message:'Conta autorizada'}};},
    disconnect_mcp_oauth:async id=>{window.mcpCalls.push(['logout',id]);servers.find(s=>s.id===id).oauth={linked:false};return {ok:true,servers};}
   }};
  });
  await page.goto(pathToFileURL(path.resolve('web/index.html')).href);await page.click('#btn-settings');
  await page.click('#mcp-add');await page.fill('#mcp-name','HTTP de teste');await page.selectOption('#mcp-transport','http');
  assert.equal(await page.locator('#mcp-local-fields').isVisible(),false);assert.equal(await page.locator('#mcp-http-fields').isVisible(),true);
  await page.fill('#mcp-url','http://localhost:9988/mcp');await page.fill('#mcp-headers','{"Authorization":"Bearer secret-test-ui"}');await page.selectOption('#mcp-approval','auto');await page.click('#modal-ok');
  await page.waitForFunction(()=>document.querySelector('#mcp-servers').textContent.includes('HTTP de teste'));
  assert.match(await page.textContent('#tools-list'),/mcp_demo_tool/);
  await page.locator('#mcp-servers .mcp-card button').getByText('Editar',{exact:true}).click();
  assert.equal(await page.inputValue('#mcp-headers'),'');assert.equal((await page.textContent('#modal-body')).includes('secret-test-ui'),false);
  await page.click('#modal-cancel');await page.locator('#mcp-servers .mcp-card button').getByText('Testar',{exact:true}).click();
  await page.waitForFunction(()=>window.mcpCalls.some(c=>c[0]==='test'));
  await page.locator('#mcp-servers .mcp-card button').getByText('Desligar',{exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#tools-count').textContent==='0');
  await page.locator('#mcp-servers .mcp-card button').getByText('Remover',{exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('#mcp-servers .mcp-card').length===0);
  await page.click('#mcp-demo');await page.waitForFunction(()=>document.querySelector('#mcp-servers').textContent.includes('Demonstração local'));
  await page.click('#mcp-add');await page.selectOption('#mcp-preset','linear-read');
  assert.equal(await page.inputValue('#mcp-url'),'https://mcp.linear.app/mcp/readonly');
  assert.equal(await page.inputValue('#mcp-auth'),'oauth');
  assert.equal(await page.locator('#mcp-manual-secrets').isVisible(),false);
  await page.fill('#mcp-scope','read');
  await page.click('#modal-ok');
  await page.waitForFunction(()=>window.mcpCalls.some(c=>c[0]==='oauth'));
  assert.equal(await page.evaluate(()=>window.mcpCalls.filter(c=>c[0]==='save').at(-1)[1].oauth_scope),'read');
  await page.waitForFunction(()=>document.querySelector('#mcp-oauth-message').textContent==='Conta autorizada');
  const linear=page.locator('#mcp-servers .mcp-card').filter({hasText:'Linear (leitura)'});
  await linear.getByRole('button',{name:'Desligar conta',exact:true}).click();
  await page.waitForFunction(()=>window.mcpCalls.some(c=>c[0]==='logout'));
  await page.waitForFunction(()=>document.querySelector('#mcp-presets').textContent.includes('Playwright'));
  const presetLinear=page.locator('#mcp-presets .mcp-card').filter({hasText:'Linear'});
  await presetLinear.getByRole('button',{name:'Configurar',exact:true}).click();
  assert.equal(await page.inputValue('#mcp-url'),'https://mcp.linear.app/mcp');
  assert.equal(await page.inputValue('#mcp-auth'),'oauth');
  assert.equal(await page.locator('#mcp-manual-secrets').isVisible(),false);
  await page.click('#modal-cancel');
  const presetPlaywright=page.locator('#mcp-presets .mcp-card').filter({hasText:'Playwright'});
  assert.equal(await presetPlaywright.getByRole('button',{name:'Instalar',exact:true}).isVisible(),true);
  await page.locator('#mcp-presets [data-kind="brave"]').getByRole('button',{name:'Configurar',exact:true}).click();
  assert.equal(await page.locator('#preset-field-api_key').getAttribute('type'),'password');
  assert.equal(await page.locator('#mcp-manual-secrets').isVisible(),false);
  await page.fill('#preset-field-api_key','brave-ui-probe');
  await page.selectOption('#mcp-approval','auto');
  await page.click('#modal-ok');
  await page.waitForFunction(()=>window.mcpCalls.some(c=>c[0]==='test'&&c[1]==='native-brave'));
  assert.equal(await page.evaluate(()=>window.mcpCalls.find(c=>c[0]==='preset-save')[2].api_key),'brave-ui-probe');
  await page.locator('#mcp-presets [data-kind="mysql"]').getByRole('button',{name:'Configurar',exact:true}).click();
  assert.equal(await page.inputValue('#preset-field-host'),'localhost');
  assert.equal(await page.inputValue('#preset-field-readonly'),'true');
  await page.selectOption('#preset-field-readonly','false');
  assert.equal(await page.locator('#preset-field-password').getAttribute('type'),'password');
  await page.click('#modal-cancel');
  await page.screenshot({path:'tests/mcp-settings.png'});assert.deepEqual(errors,[]);
  console.log('PASS: MCP settings CRUD, OAuth preset, login progress, logout, secret fields preserved, catalogue refresh, MCP presets');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
