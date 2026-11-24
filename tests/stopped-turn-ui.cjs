// Um pedido que parou antes de acabar diz porquê no fim da resposta e oferece «Continuar» (pedido do user, 24/11/2026).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const assert=require('node:assert/strict');

(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>{
      const steps=[{kind:'tool',title:'executar_comando',body:'python test.py',ok:false}];
      const messages=[
        {role:'user',text:'descompila'},
        {role:'assistant',text:'Primeira parte.',steps,turn_state:'limited',stop_reason:'Limite de chamadas de ferramentas atingido.'},
        {role:'user',text:'e agora'},
        {role:'assistant',text:'Pronto — 0 ficheiro(s) e 1 ação(ões).',steps,turn_state:'completed',stop_reason:'O modelo terminou sem escrever uma resposta final.'},
      ];
      const state={ok:true,providers:[],projects:[],conversations:[],selections:{},preferences:{}};
      window.chatCalls=[];
      window.pywebview={api:{
        get_state:async()=>state,get_conversation:async()=>({ok:true,messages}),
        chat:async(text)=>{window.chatCalls.push(text);messages.push({role:'user',text},{role:'assistant',text:'Continuei e acabei.',steps:[],turn_state:'completed'});return {ok:true};},
      }};
    });
    await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
    await page.waitForSelector('.msg-stopped');
    assert.equal(await page.locator('.msg-stopped').count(),1,'só a última resposta mostra o aviso');
    const last=page.locator('.msg.assistant').last();
    assert.match(await last.locator('.msg-stopped').innerText(),/O pedido parou antes de terminar: O modelo terminou sem escrever uma resposta final\. Queres que continue\?/);
    // o aviso fica no fim, por baixo das ações — é aí que a pessoa está a olhar
    const order=await last.evaluate(node=>[...node.children].map(child=>child.className.split(' ').pop()));
    assert(order.indexOf('msg-stopped')>order.findIndex(name=>/steps/.test(name)),'aviso depois das ações: '+order.join(','));
    await page.fill('#composer','rascunho meu');
    await page.locator('.msg-stopped button').click();
    await page.waitForFunction(()=>window.chatCalls.length===1);
    assert.deepEqual(await page.evaluate(()=>window.chatCalls),['Continua o trabalho a partir de onde ficaste.']);
    assert.equal(await page.inputValue('#composer'),'rascunho meu','o que estava escrito na caixa não se perde');
    await page.waitForFunction(()=>document.querySelectorAll('.msg-stopped').length===0);
    assert.deepEqual(errors,[]);
    console.log('PASS: stopped turn — reason shown after the actions on the last answer only, Continue sends the follow-up and keeps the draft, notice gone once the work goes on');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
