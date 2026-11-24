const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      const catalog = [
        {id:'coder',name:'Code Model',categories:['chat','code'],types:['chat'],description:'Coding model'},
        {id:'vision',name:'Vision Chat',categories:['chat'],types:['chat'],description:'Reads images'},
        {id:'image',name:'Image Model',categories:['image'],types:['image'],description:'Generates images'},
        {id:'video',name:'Video Model',categories:['video'],types:['video'],description:'Generates videos'},
        {id:'embed',name:'Embeddings Model',categories:['embeddings'],types:[],description:'Vectors'},
      ];
      const provider = {id:'p',name:'OpenRouter',kind:'openrouter',has_key:true,catalog,catalog_updated_at:Date.now()/1000,
        models:catalog.flatMap(m=>m.types.map(type=>({...m,type,defaults:{},catalog_available:true})))};
      const state = {ok:true, providers:[provider],projects:[],conversations:[],selections:{chat:{provider_id:'p',model_id:'coder'}},preferences:{}};
      window.catalogSyncCalls=[];
      window.pywebview={api:{get_state:async()=>state,get_conversation:async()=>({ok:true,messages:[]}),
        get_context_usage:async()=>({ok:true,used:100,limit:0,percent:0,parts:{}}),
        sync_provider_models:async(pid,force)=>{window.catalogSyncCalls.push([pid,force]);return state;},
        set_model:async(type,pid,mid)=>{state.selections[type]={provider_id:pid,model_id:mid};return state;}}};
    });
    await page.goto(pathToFileURL(path.resolve('web/index.html')).href);
    await page.waitForFunction(()=>window.catalogSyncCalls.length===1);
    assert.deepEqual(await page.locator('#sel-chat option').allTextContents(),['(escolhe um modelo)','Code Model','Vision Chat']);
    assert.deepEqual(await page.locator('#sel-code option').allTextContents(),['(escolhe um modelo)','Code Model'],'o campo «Código» só lista os da categoria código');
    assert.deepEqual(await page.locator('#sel-image option').allTextContents(),['(escolhe um modelo)','Image Model']);
    await page.selectOption('#sel-image','p::image');
    await page.waitForFunction(()=>document.querySelector('#sel-image').value==='p::image');
    await page.evaluate(()=>discoverModels('p'));
    assert.equal(await page.locator('.catalog-row').count(),5);
    await page.selectOption('#catalog-category','embeddings');
    assert.equal(await page.locator('.catalog-row').count(),1);
    assert.match(await page.locator('.catalog-row').innerText(),/Só catálogo/);
    await page.selectOption('#catalog-category','');
    await page.fill('#catalog-search','Vision');
    assert.equal(await page.locator('.catalog-row').count(),1);
    assert.match(await page.locator('.catalog-row').innerText(),/Vision Chat/);
    await page.click('#modal-ok');
    await page.waitForFunction(()=>window.catalogSyncCalls.length===2);
    assert.deepEqual(await page.evaluate(()=>window.catalogSyncCalls),[['p',false],['p',true]]);
    assert.deepEqual(errors,[]);
    console.log('PASS: automatic sync, code/image filters, provider selection, searchable categories, catalog-only services, refresh, no JS errors');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
