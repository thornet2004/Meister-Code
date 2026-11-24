// Barra de modelos: um seletor por coisa (conversa, código, imagem, vídeo, áudio), sempre à vista; nada é escolhido pela app.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const assert=require('node:assert/strict');

(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>{
      const providers=[
        {id:'router',name:'OpenRouter',kind:'openrouter',has_key:true,models:[{id:'shared',name:'DeepSeek',type:'chat',defaults:{context_window:128000}},{id:'r2',name:'Outro chat',type:'chat',categories:['chat','code']},{id:'image',name:'Imagem',type:'image'},{id:'gone',name:'Saiu do catálogo',type:'image',catalog_available:false}]},
        {id:'other',name:'Segundo provedor',kind:'openrouter',has_key:false,models:[{id:'shared',name:'Modelo com ID repetido',type:'chat'},{id:'o2',name:'Chat alternativo',type:'chat'}]},
        {id:'audio',name:'Provedor áudio',kind:'openrouter',has_key:true,models:[{id:'voice',name:'Voz',type:'audio'}]}
      ];
      let selections=JSON.parse(localStorage.getItem('picker-test-selection') || 'null') || {chat:{provider_id:'router',model_id:'shared'}};
      const preferences=JSON.parse(localStorage.getItem('picker-test-preferences') || '{}');
      const state=()=>({ok:true,providers,projects:[],conversations:[],selections,preferences});
      window.pickerCalls=[];window.pickerState=state;
      window.pywebview={api:{
        get_state:async()=>state(),get_conversation:async()=>({ok:true,messages:[]}),
        set_model:async(type,provider,model)=>{
          window.pickerCalls.push([type,provider,model]);
          selections[type]=provider?{provider_id:provider,model_id:model}:{};
          localStorage.setItem('picker-test-selection',JSON.stringify(selections));
          return state();
        },
        set_preference:async(key,value)=>{preferences[key]=value;localStorage.setItem('picker-test-preferences',JSON.stringify(preferences));return state();},
        open_browser:async()=>({ok:true}),browser_layout:async()=>({ok:true}),browser_state:async()=>({ok:true}),
      }};
    });
    const groups=selector=>page.evaluate(sel=>[...document.querySelectorAll(sel+' optgroup')].map(group=>[group.label,[...group.children].map(option=>option.textContent)]),selector);
    await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
    await page.waitForFunction(()=>document.querySelector('#sel-chat').value==='router::shared');

    // os cinco seletores estão sempre à vista, cada um com os modelos da sua categoria agrupados por provedor
    for (const selector of ['#sel-chat','#sel-code','#sel-image','#sel-video','#sel-audio']) assert.equal(await page.locator(selector).isVisible(),true,selector);
    assert.deepEqual(await groups('#sel-chat'),[['OpenRouter',['DeepSeek · 128,0k','Outro chat']],['Segundo provedor — sem chave',['Chat alternativo','Modelo com ID repetido']]]);
    assert.deepEqual(await groups('#sel-code'),[['OpenRouter',['Outro chat']]],'«Código» só lista os modelos de conversa da categoria código');
    assert.deepEqual(await groups('#sel-image'),[['OpenRouter',['Imagem']]],'um modelo que saiu do catálogo não aparece');
    assert.deepEqual(await groups('#sel-audio'),[['Provedor áudio',['Voz']]]);
    // nada é escolhido pela app: o que o utilizador não escolheu fica por escolher, e marcado
    assert.deepEqual(await page.evaluate(()=>['#sel-code','#sel-image','#sel-video','#sel-audio'].map(sel=>[document.querySelector(sel).value,document.querySelector(sel).classList.contains('unset')])),[['',true],['',true],['',true],['',true]]);
    assert.equal(await page.locator('#sel-video').isDisabled(),true,'sem modelos de vídeo, o seletor fica desligado');
    assert.equal(await page.locator('#sel-video option').first().textContent(),'(sem modelos)');
    assert.equal(await page.locator('#sel-image option').first().textContent(),'(escolhe um modelo)');
    assert.deepEqual(await page.evaluate(()=>window.pickerCalls),[],'abrir a app não escolhe nada');

    // escolher um modelo de áudio ou de imagem não mexe no da conversa
    await page.selectOption('#sel-audio','audio::voice');
    await page.waitForFunction(()=>document.querySelector('#sel-audio').value==='audio::voice' && !document.querySelector('#sel-audio').disabled);
    await page.selectOption('#sel-image','router::image');
    await page.waitForFunction(()=>document.querySelector('#sel-image').value==='router::image' && !document.querySelector('#sel-image').disabled);
    assert.deepEqual(await page.evaluate(()=>window.pickerCalls),[['audio','audio','voice'],['image','router','image']]);
    assert.equal(await page.inputValue('#sel-chat'),'router::shared','a conversa continua com o seu modelo');

    // dois provedores com um modelo de ID igual: vai o do provedor escolhido
    await page.selectOption('#sel-chat','other::shared');
    await page.waitForFunction(()=>document.querySelector('#sel-chat').value==='other::shared' && !document.querySelector('#sel-chat').disabled);
    assert.deepEqual(await page.evaluate(()=>window.pickerCalls.at(-1)),['chat','other','shared']);

    // o modelo de código escolhe-se à parte e não mexe no da conversa
    await page.selectOption('#sel-code','router::r2');
    await page.waitForFunction(()=>document.querySelector('#sel-code').value==='router::r2' && !document.querySelector('#sel-code').disabled);
    assert.deepEqual(await page.evaluate(()=>window.pickerCalls.at(-1)),['code','router','r2']);
    assert.equal(await page.inputValue('#sel-chat'),'other::shared');
    assert.equal(await page.locator('#chat-code-only').count(),0,'a caixa «só código» deu lugar ao campo próprio');

    // fechar e abrir: as escolhas voltam
    await page.reload();
    await page.waitForFunction(()=>document.querySelector('#sel-chat').value==='other::shared');
    assert.deepEqual([await page.inputValue('#sel-code'),await page.inputValue('#sel-image'),await page.inputValue('#sel-audio')],['router::r2','router::image','audio::voice']);

    // tirar a escolha também é uma escolha do utilizador
    await page.selectOption('#sel-image','');
    await page.waitForFunction(()=>document.querySelector('#sel-image').classList.contains('unset') && !document.querySelector('#sel-image').disabled);
    assert.deepEqual(await page.evaluate(()=>window.pickerCalls.at(-1)),['image','','']);

    await page.screenshot({path:'tests/provider-picker-wide.png'});
    await page.click('#btn-browser');
    await page.waitForFunction(()=>document.querySelector('.layout').classList.contains('browser-open'));
    for (const width of [1440,1000,900,420]) {
      await page.setViewportSize({width,height:900});
      const bounds=await page.locator('.composer').boundingBox();
      for (const selector of ['#sel-chat','#sel-code','#sel-image','#sel-video','#sel-audio']) {
        const field=await page.locator(selector).boundingBox();
        assert(field.x>=bounds.x && field.x+field.width<=bounds.x+bounds.width+1,selector+' overflows composer at '+width);
      }
    }
    await page.screenshot({path:'tests/provider-picker-narrow.png'});
    await page.evaluate(()=>applyState({ok:true,providers:[],projects:[],conversations:[],selections:{}}));
    for (const selector of ['#sel-chat','#sel-code','#sel-image','#sel-video','#sel-audio']) assert.equal(await page.locator(selector).isDisabled(),true,selector);
    assert.deepEqual(errors,[]);
    console.log('PASS: model slots — five always-visible pickers grouped by provider, nothing chosen by the app, independent choices, duplicate model IDs, separate code model, persistence, clearing, narrow layout');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
