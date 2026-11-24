// Configurações: uma escolha única entre provedores online e a rig local; o lado que não está em uso fica apagado e sem ação.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const assert=require('node:assert/strict');

(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1100}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>{
      const cloud={id:'router',name:'OpenRouter',kind:'openrouter',has_key:true,models:[{id:'deepseek',name:'DeepSeek',type:'chat'},{id:'flux',name:'Flux',type:'image'}]};
      const mine=()=>({id:'a-minha-rig',name:'Meister Chat',kind:'openai-compatible',has_key:true,rig:true,models:[{id:'qwen3.8-27b',name:'qwen3.8-27b',type:'chat',defaults:{context_window:32768},categories:['code']}]});
      let rig={enabled:false,address:'',has_key:false,effort:'leve',whisper:false,model:'',context:0};
      const online={chat:{provider_id:'router',model_id:'deepseek'},image:{provider_id:'router',model_id:'flux'}};
      let selections={...online};
      window.rigCalls=[];window.rigDown=false;
      const state=()=>({ok:true,providers:rig.enabled?[cloud,mine()]:[cloud],rig,projects:[],conversations:[],selections,preferences:{}});
      window.pywebview={api:{
        get_state:async()=>state(),get_conversation:async()=>({ok:true,messages:[]}),
        set_model:async(type,provider,model)=>{selections={...selections,[type]:provider?{provider_id:provider,model_id:model}:{}};return state();},
        set_preference:async()=>state(),
        set_rig:async(data)=>{
          window.rigCalls.push(data);
          if(data.enabled&&!data.address)return {ok:false,error:'Escreve o endereço da rig.'};
          const on=data.enabled&&!window.rigDown;
          rig={enabled:on,address:data.address,has_key:rig.has_key||!!data.api_key,effort:data.effort,whisper:on&&data.whisper,model:on?'qwen3.8-27b':'',context:on?32768:0};
          selections={...selections,chat:on?{provider_id:'a-minha-rig',model_id:'qwen3.8-27b'}:online.chat};
          return Object.assign(state(),data.enabled&&window.rigDown?{rig_error:'A rig não respondeu em '+data.address+'.'}:{});
        },
        open_browser:async()=>({ok:true}),browser_layout:async()=>({ok:true}),browser_state:async()=>({ok:true}),
      }};
    });
    await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
    await page.waitForFunction(()=>document.querySelector('#sel-chat').value==='router::deepseek');
    await page.click('#btn-settings');
    await page.waitForSelector('#source-section',{state:'visible'});
    const sides=()=>page.evaluate(()=>({online:document.querySelector('#source-online').checked,local:document.querySelector('#source-local').checked,
      rigOff:document.querySelector('#rig-section').inert,onlineOff:document.querySelector('#online-section').inert}));

    // de início: online em uso, a secção da rig apagada
    assert.deepEqual(await sides(),{online:true,local:false,rigOff:true,onlineOff:false});
    assert.equal(await page.locator('#providers-list .provider-card').count(),1);
    assert.match(await page.textContent('#source-hint'),/provedores online/);

    // escolher «local» sem rig configurada: abre a secção para escrever, ainda sem falar com o backend
    await page.check('#source-local');
    assert.deepEqual(await sides(),{online:false,local:true,rigOff:false,onlineOff:true});
    assert.equal(await page.evaluate(()=>window.rigCalls.length),0);
    assert.match(await page.textContent('#rig-status'),/Escreve o endereço/);
    assert.match(await page.textContent('#source-hint'),/Ainda não estás ligado/);

    // o que se escreve não se apaga quando o estado da app é atualizado por outro motivo (era o defeito que o user viu)
    await page.evaluate(()=>{window.rigDown=true;});
    await page.locator('#rig-address').pressSequentially('http://192.168.0.10:8081');
    await page.evaluate(async()=>{document.activeElement.blur?.();});
    await page.waitForFunction(()=>window.rigCalls.length===1,null,{timeout:10000});   // escrito o endereço, tenta ligar sozinha
    await page.waitForFunction(()=>document.querySelector('#rig-status').textContent.includes('não respondeu'));
    await page.locator('#rig-key').pressSequentially('segredo');
    await page.evaluate(async()=>{applyState(await window.pywebview.api.get_state());});
    assert.equal(await page.inputValue('#rig-address'),'http://192.168.0.10:8081','o endereço escrito fica');
    assert.equal(await page.inputValue('#rig-key'),'segredo','e a chave por guardar também');
    // sair do campo da chave guarda-a e tenta ligar; a caixa da voz fica como a deixaste
    await page.check('#rig-whisper');
    await page.waitForFunction(()=>window.rigCalls.at(-1).api_key==='segredo');
    await page.waitForFunction(()=>document.querySelector('#rig-key').value==='');
    await page.evaluate(async()=>{applyState(await window.pywebview.api.get_state());});
    assert.equal(await page.isChecked('#rig-whisper'),true);
    assert.equal(await page.inputValue('#rig-address'),'http://192.168.0.10:8081');

    // a rig não responde: fica tudo guardado, continua-se online e diz-se porquê
    await page.click('#rig-save');
    await page.waitForFunction(()=>document.querySelector('#rig-status').textContent.includes('não respondeu'));
    assert.match(await page.textContent('#rig-status'),/Continuas nos provedores online/);
    assert.equal(await page.inputValue('#rig-key'),'','a chave não fica à vista depois de guardada');
    assert.equal(await page.inputValue('#sel-chat'),'router::deepseek','a barra de modelos não mudou');

    // agora responde: passa a local, a barra de modelos da conversa só mostra a rig e o lado online fica sem ação
    await page.evaluate(()=>{window.rigDown=false;});
    await page.click('#rig-save');
    await page.waitForFunction(()=>document.querySelector('#rig-status').textContent.includes('Em uso'));
    assert.match(await page.textContent('#rig-status'),/Em uso · qwen3\.8-27b · contexto/);
    assert.deepEqual(await sides(),{online:false,local:true,rigOff:false,onlineOff:true});
    assert.deepEqual(await page.evaluate(()=>[...document.querySelectorAll('#sel-chat optgroup')].map(g=>g.label)),['Meister Chat'],'em modo local a conversa só lista a rig');
    assert.equal(await page.inputValue('#sel-chat'),'a-minha-rig::qwen3.8-27b');
    assert.equal(await page.locator('#providers-list .provider-card').count(),1,'os provedores online continuam listados, só que apagados');
    assert.match(await page.textContent('#providers-list'),/DeepSeek/,'e com os seus modelos de chat à vista');
    assert.match(await page.textContent('#source-hint'),/correm na tua rig/);
    await page.screenshot({path:process.env.RIG_UI_SHOT||path.join(require('node:os').tmpdir(),'rig-ui.png')});

    // em modo local só se veem os modelos da rig: os campos sem modelos dela nem aparecem (pedido do user, 24/11/2026)
    await page.evaluate(()=>{document.querySelector('#settings-modal').classList.add('hidden');});
    assert.deepEqual(await page.evaluate(()=>['chat','code','image','video','audio'].map(slot=>document.querySelector('#sel-'+slot).closest('.model-slot').classList.contains('hidden'))),[false,false,true,true,true]);
    assert.deepEqual(await page.evaluate(()=>[...document.querySelectorAll('#sel-code optgroup, #sel-image optgroup')].map(g=>g.label)),['Meister Chat'],'nenhum modelo online à vista');
    await page.click('#btn-settings');

    // esforço e voz guardam-se ao mudar, sem reescrever a chave
    await page.selectOption('#rig-effort','pesado');
    await page.waitForFunction(()=>window.rigCalls.at(-1).effort==='pesado');
    await page.uncheck('#rig-whisper');
    await page.waitForFunction(()=>window.rigCalls.at(-1).whisper===false);
    await page.check('#rig-whisper');
    await page.waitForFunction(()=>window.rigCalls.at(-1).whisper===true);
    assert.deepEqual(await page.evaluate(()=>window.rigCalls.at(-1)),{enabled:true,address:'http://192.168.0.10:8081',api_key:'',effort:'pesado',whisper:true});

    // voltar a «online»: a rig sai da barra, a escolha online volta e o endereço fica guardado
    await page.check('#source-online');
    await page.waitForFunction(()=>document.querySelector('#rig-section').inert);
    assert.deepEqual(await sides(),{online:true,local:false,rigOff:true,onlineOff:false});
    assert.deepEqual(await page.evaluate(()=>[...document.querySelectorAll('#sel-chat optgroup')].map(g=>g.label)),['OpenRouter']);
    assert.equal(await page.inputValue('#sel-chat'),'router::deepseek');
    assert.equal(await page.inputValue('#rig-address'),'http://192.168.0.10:8081');

    // com a rig já configurada, escolher «local» liga logo
    await page.check('#source-local');
    await page.waitForFunction(()=>document.querySelector('#rig-status').textContent.includes('Em uso'));
    assert.equal(await page.inputValue('#sel-chat'),'a-minha-rig::qwen3.8-27b');
    assert.deepEqual(errors,[]);
    console.log('PASS: online/local switch — unused side inert, draft before the rig answers, stays online when the rig is down, local shows only the rig for chat, online models hidden in local mode, effort and voice saved on change, back to online restores the picker');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
