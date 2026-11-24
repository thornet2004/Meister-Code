// Seletor de voz na barra de modelos: só aparece com um modelo de áudio que tenha vozes, e guarda a escolha.
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
      const providers=[{id:'router',name:'OpenRouter',kind:'openrouter',has_key:true,models:[
        {id:'chat',name:'Chat',type:'chat'},
        {id:'eleven',name:'Eleven v4 Turbo',type:'audio',defaults:{},voices:['george','sarah','adam']},
        {id:'fish',name:'Fish S1',type:'audio',defaults:{}},
        {id:'gemini',name:'Gemini TTS',type:'audio',defaults:{voice:'Kore'},voices:['Zephyr','Kore']}]}];
      const selections={chat:{provider_id:'router',model_id:'chat'},audio:{provider_id:'router',model_id:'eleven'}};
      const state=()=>({ok:true,providers,projects:[],conversations:[],selections,preferences:{}});
      window.voiceCalls=[];window.failNext=false;
      window.pywebview={api:{
        get_state:async()=>state(),get_conversation:async()=>({ok:true,messages:[]}),
        set_model:async(type,provider,model)=>{selections[type]=provider?{provider_id:provider,model_id:model}:{};return state();},
        set_model_voice:async(provider,model,voice)=>{
          window.voiceCalls.push([provider,model,voice]);
          if(window.failNext){window.failNext=false;return {ok:false,error:'Este modelo não tem a voz «x».'};}
          const found=providers[0].models.find(item=>item.id===model);
          found.defaults={...found.defaults};delete found.defaults.voice;if(voice)found.defaults.voice=voice;
          return state();
        },
        set_preference:async()=>state(),
        open_browser:async()=>({ok:true}),browser_layout:async()=>({ok:true}),browser_state:async()=>({ok:true}),
      }};
    });
    await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
    await page.waitForFunction(()=>document.querySelector('#sel-audio').value==='router::eleven');
    await page.waitForFunction(()=>!document.querySelector('#sel-voice').classList.contains('hidden'));
    assert.deepEqual(await page.locator('#sel-voice option').allTextContents(),['🗣 Voz: george (a primeira do modelo)','🗣 Voz: george','🗣 Voz: sarah','🗣 Voz: adam']);
    assert.equal(await page.inputValue('#sel-voice'),'','sem escolha fica na primeira do modelo');
    await page.selectOption('#sel-voice','sarah');
    await page.waitForFunction(()=>window.voiceCalls.length===1);
    assert.deepEqual(await page.evaluate(()=>window.voiceCalls[0]),['router','eleven','sarah']);
    await page.waitForFunction(()=>document.querySelector('#sel-voice').value==='sarah');
    // modelo sem lista de vozes: o seletor desaparece
    await page.selectOption('#sel-audio','router::fish');
    await page.waitForFunction(()=>document.querySelector('#sel-voice').classList.contains('hidden'));
    // modelo com voz já escolhida
    await page.selectOption('#sel-audio','router::gemini');
    await page.waitForFunction(()=>!document.querySelector('#sel-voice').classList.contains('hidden') && document.querySelector('#sel-voice').value==='Kore');
    // voltar à primeira do modelo limpa a escolha
    await page.selectOption('#sel-voice','');
    await page.waitForFunction(()=>window.voiceCalls.length===2);
    assert.deepEqual(await page.evaluate(()=>window.voiceCalls[1]),['router','gemini','']);
    // uma recusa mostra o erro e o seletor volta ao que estava guardado
    await page.evaluate(()=>{window.failNext=true;});
    await page.selectOption('#sel-voice','Zephyr');
    await page.waitForFunction(()=>window.voiceCalls.length===3 && document.querySelector('#sel-voice').value==='');
    // sem modelo de áudio escolhido não há voz
    await page.selectOption('#sel-audio','');
    await page.waitForFunction(()=>document.querySelector('#sel-voice').classList.contains('hidden'));
    // mudar a conversa não mexe no áudio nem na voz
    await page.selectOption('#sel-audio','router::eleven');
    await page.waitForFunction(()=>!document.querySelector('#sel-voice').classList.contains('hidden') && document.querySelector('#sel-voice').value==='sarah');
    await page.selectOption('#sel-chat','router::chat');
    assert.equal(await page.inputValue('#sel-audio'),'router::eleven');
    // janela estreita: não sai da caixa de mensagem
    await page.setViewportSize({width:420,height:900});
    await page.waitForFunction(()=>!document.querySelector('#sel-voice').classList.contains('hidden'));
    const bounds=await page.locator('.model-slots').boundingBox(),field=await page.locator('#sel-voice').boundingBox();
    assert(field.x>=bounds.x-1 && field.x+field.width<=bounds.x+bounds.width+1,'o seletor de voz sai da barra');
    assert.deepEqual(errors,[]);
    console.log('PASS: voice picker — only for an audio model with voices, saves the choice, clears it, survives a refusal, independent of the chat model, fits a narrow window');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
