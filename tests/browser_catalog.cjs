const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try {
 const page=await browser.newPage({viewport:{width:1400,height:1050}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8199');
 await page.waitForFunction(()=>window.app?.graph,{timeout:60000});
 await page.waitForTimeout(1500);await page.keyboard.press('Escape');await page.keyboard.press('Escape');
 await page.evaluate(async()=>{
   const {app}=await import('/scripts/app.js');await app.extensionManager.setting.set('Comfy.VueNodes.Enabled',false);
   app.graph.clear();const node=LiteGraph.createNode('AVSPromptHelper');node.pos=[200,100];app.graph.add(node);window.testNode=node;
 });
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Settings',exact:true});
 const adapter=page.getByLabel('Adapter',{exact:true}), model=page.getByLabel('Model',{exact:true}), effort=page.getByLabel('Reasoning effort',{exact:true});
 const test=page.getByRole('button',{name:'Test connection',exact:true});
 const levels=()=>effort.locator('option').evaluateAll(options=>options.map(o=>o.value));
 // Real read-only Codex app-server, no model turn.
 await adapter.selectOption('codex');
 await page.getByLabel('Model ID',{exact:true}).fill('GPT-6 Luna');await effort.selectOption('none');
 await test.click();await page.waitForFunction(()=>document.querySelector('[aria-label="Model"]')?.options.length>1,{timeout:50000});
 assert.equal(await model.inputValue(),'gpt-6-luna');
 assert.equal(await effort.inputValue(),'auto');assert(!(await levels()).includes('none'));
 assert((await levels()).includes('low'));
 const actualModels=await model.locator('option').count()-1;
 await effort.selectOption('low');
 await page.screenshot({path:'test-results/settings-catalog-codex.png'});
 await page.getByRole('button',{name:'Save settings',exact:true}).click();
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 assert.equal(await model.inputValue(),'gpt-6-luna');assert.equal(await effort.inputValue(),'low');
 assert(!(await page.getByLabel('Model ID',{exact:true}).isVisible()));
 // CLI fixtures for executables not installed on this host.
 await page.route('**/avs-prompt/test',async route=>{
   const request=route.request().postDataJSON();
   const models=request.adapter==='claude' ? [
     {id:'opus',name:'Claude Opus',reasoning:['low','high','max']},
     {id:'haiku',name:'Claude Haiku',reasoning:[]}
   ] : [
     {id:'kimi-alias',name:'Kimi',reasoning:['thinking','no_thinking']},
     {id:'reasoner',name:'Always thinking',reasoning:['thinking']}
   ];
   await route.fulfill({json:{message:'Fixture catalogue loaded',models}});
 });
 await adapter.selectOption('claude');await test.click();await model.selectOption('opus');
 assert.deepEqual(await levels(),['auto','low','high','max']);
 await effort.selectOption('max');await model.selectOption('haiku');
 assert.deepEqual(await levels(),['auto']);assert.equal(await effort.inputValue(),'auto');
 await adapter.selectOption('kimi');await test.click();await model.selectOption('kimi-alias');
 assert.deepEqual(await levels(),['auto','thinking','no_thinking']);
 await effort.selectOption('no_thinking');await model.selectOption('reasoner');
 assert.deepEqual(await levels(),['auto','thinking']);assert.equal(await effort.inputValue(),'auto');
 await model.selectOption('');await page.getByLabel('Model ID',{exact:true}).fill('custom-alias');
 await page.screenshot({path:'test-results/settings-catalog-kimi.png'});
 // A late result from another adapter cannot replace the current catalogue.
 await page.unroute('**/avs-prompt/test');let release;
 const gate=new Promise(resolve=>release=resolve);
 await page.route('**/avs-prompt/test',async route=>{await gate;await route.fulfill({json:{message:'Stale',models:[{id:'stale',name:'Stale',reasoning:[]}]}});});
 await test.click();await adapter.selectOption('claude');release();
 await page.waitForFunction(()=>!document.querySelector('.avs-dialog-actions button').disabled);
 assert(!(await model.locator('option').allTextContents()).includes('Stale'));
 assert((await model.locator('option').allTextContents()).some(x=>x.includes('Opus')));
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({result:'Catalog UI passed',actualCodexModels:actualModels,claudeAndKimi:'fixtures',errors}));
 await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
