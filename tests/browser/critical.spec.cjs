'use strict';
const {test, expect} = require('@playwright/test');
const {readFileSync} = require('node:fs');
const path = require('node:path');

test.beforeEach(async ({context, request, baseURL}) => {
  // Even a test failure must never fall through to a real client or upstream API.
  await context.route('**/*', route => new URL(route.request().url()).origin === baseURL
    ? route.continue() : route.abort());
  expect(await (await request.get('/__fixture_health')).json()).toEqual({fixture: 'cmb-browser-regression'});
});

async function ready(page, scenario = 'success') {
  await page.goto('/?case=' + scenario);
  await page.waitForFunction(() => {
    const status = document.getElementById('bootstrap-status');
    return status && (status.hidden || status.dataset.state === 'failed');
  });
}

test('Markdown, literal code and math rendering', async ({page}, testInfo) => {
  await ready(page);
  await expect(page.locator('#bootstrap-status')).toBeHidden();
  await page.evaluate(async () => {
    await BridgeFeatures.load('chat');
    await BridgeFeatures.load('math');
    await document.fonts.ready;
  });
  for (const [file, count] of [['markdown', 15], ['math', 13]]) {
    const result = await page.evaluate(readFileSync(path.join(__dirname, file + '.browser.js'), 'utf8'));
    expect(result.passed).toBe(count);
    await testInfo.attach(file + '-checks', {body: JSON.stringify(result), contentType: 'application/json'});
  }
});

for (const scenario of ['success', 'css-once', 'js-twice', 'js-fatal', 'runtime',
  'opaque-error', 'external-runtime', 'external-rejection', 'app-cached-failure']) {
  test('startup and login: ' + scenario, async ({page}, testInfo) => {
    await ready(page, scenario);
    const evidence = await page.evaluate(async () => ({
      state: await (await fetch('/__state')).json(), probe: window.__startupTest,
      status: document.getElementById('bootstrap-status').dataset.state,
      diagnostic: document.getElementById('bootstrap-details').textContent,
    }));
    await testInfo.attach('startup-evidence', {body: JSON.stringify(evidence), contentType: 'application/json'});
    expect(evidence.state.writes).toEqual([]);
    await page.addScriptTag({url: '/__checks.js'});
    const result = await page.evaluate(() => runBootstrapBrowserChecks());
    expect(result.passed).toBe(true);
    expect(result.writes).toEqual([]);
    if (scenario === 'success') await expect(page.locator('#login')).toBeVisible();
  });
}

for (const [name, file, invoke] of [
  ['chat history, list entry and scroll position', 'desktop-history', 'runDesktopHistoryBrowserChecks'],
  ['account-scoped drafts and late send acknowledgement', 'persistent-drafts', 'runPersistentDraftTests'],
  ['API form labels, layout and upstream model selection', 'api-form', 'runApiFormBrowserChecks'],
  ['shared session menu on desktop and mobile', 'session-menu', 'runSessionMenuBrowserChecks'],
  ['composer quotes retain draft and layout', 'composer-quotes', 'runComposerQuoteLayoutChecks'],
]) {
  test(name, async ({page}, testInfo) => {
    await ready(page);
    await expect(page.locator('#bootstrap-status')).toBeHidden();
    await page.addScriptTag({url: `/__browser/${file}.browser.js`});
    const result = await page.evaluate(name => globalThis[name](), invoke);
    expect(Array.isArray(result) ? result.length : result.passed).toBeGreaterThan(0);
    await testInfo.attach('checks', {body: JSON.stringify(result), contentType: 'application/json'});
  });
}

for (const provider of ['claude', 'deepseek']) {
  test(provider + ' project dialog and directory isolation', async ({page}) => {
    await ready(page);
    await page.addScriptTag({url: '/__browser/project-creation.browser.js'});
    const result = await page.evaluate(provider => runProjectCreationBrowserChecks({provider, language: 'zh'}), provider);
    expect(result.passed).toBeGreaterThan(0);
  });
}

test('Android app theme synchronizes list and chat without replacing drafts or other appearance settings',async({page})=>{
 await ready(page);
 const result=await page.evaluate(()=>{
  const input=document.getElementById('message'),root=document.documentElement,theme=document.getElementById('appearance-theme');
  input.value='keep this draft';const original=input,changes=[];
  document.addEventListener('bridge-theme-change',event=>changes.push(event.detail.theme));
  const accent=document.getElementById('appearance-accent');accent.value='#6655cc';accent.oninput();
  const native=(choice,dark)=>{window.BridgeNativeTheme={theme:choice,dark};document.dispatchEvent(new Event('bridge-native-theme'));return root.dataset.theme;};
  const states=[native('system',true),native('system',false),native('dark',false),native('light',true)];
  theme.value='dark';theme.onchange();states.push(root.dataset.theme);
  const saved=JSON.parse(localStorage.getItem('bridge-appearance'));
  return {states,changes,draft:input.value,sameInput:original===document.getElementById('message'),accent:saved.accent,choice:saved.theme};
 });
 expect(result).toEqual({states:['dark','light','dark','light','dark'],changes:['dark'],draft:'keep this draft',sameInput:true,accent:'#6655cc',choice:'dark'});
});

for(const provider of ['Codex','Claude','DSH']){
 test(provider+' list menu entry, themes and equal archive confirmation',async({page},testInfo)=>{
  await ready(page,'session-menu');
  await expect(page.locator('#login')).toBeHidden();
  await page.locator('#client-switch').getByRole('button',{name:provider,exact:true}).click();
  const row=page.locator('.session:visible').filter({hasText:provider+' · 页面交互验证'}).first();
  await expect(row).toBeVisible();
  const listIdentity=await row.getAttribute('data-id');
  const openMenu=async()=>{
   if(page.viewportSize().width<=640){
    await row.dispatchEvent('pointerdown',{pointerType:'touch',button:0,clientX:80,clientY:150});
    await expect(page.locator('dialog.session-menu')).toBeVisible();
    await row.dispatchEvent('pointerup',{pointerType:'touch',button:0});
    await row.dispatchEvent('click');
   }else await row.click({button:'right'});
  };
  for(const theme of ['light','dark']){
   await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;},theme);
   await openMenu();
   const box=page.locator('dialog.session-menu');
   await expect(box).toBeVisible();
   await expect(page.locator('#app')).not.toHaveClass(/chat-open/);
   await expect(row).toHaveAttribute('data-id',listIdentity);
   await expect(box.locator('.sm-name strong')).toHaveText(provider+' · 页面交互验证');
   await expect(box.getByRole('button',{name:'聊天通知设置',exact:true})).toBeVisible();
   await expect(box.getByRole('button',{name:'项目',exact:true})).toHaveCount(1);
   await expect(box.getByRole('button',{name:'分区',exact:true})).toHaveCount(1);
   await box.evaluate(node=>Promise.all(node.getAnimations().map(a=>a.finished)));
   await page.screenshot({path:testInfo.outputPath(provider+'-'+theme+'-list.png')});
   await box.getByRole('button',{name:'会话详情',exact:true}).click();
   await page.keyboard.press('Escape');
   await expect(box.locator('.sm-name strong')).toHaveText(provider+' · 页面交互验证');
   await expect(page.locator('#app')).not.toHaveClass(/chat-open/);
   await page.keyboard.press('Escape');await expect(box).toHaveCount(0);
   await openMenu();
   await box.getByRole('button',{name:'修改聊天名称',exact:true}).click();
   await expect(box.getByRole('textbox',{name:'聊天名称',exact:true})).toHaveValue(provider+' · 页面交互验证');
   await box.getByRole('textbox',{name:'聊天名称',exact:true}).fill('返回不保存这个名称');
   await box.dispatchEvent('cancel',{cancelable:true});
   await expect(box.locator('.sm-name strong')).toHaveText(provider+' · 页面交互验证');
   for(const label of ['项目','分区']){
    await box.getByRole('button',{name:label,exact:true}).click();
    await expect(box.getByRole('button',{name:'示例'+label,exact:true})).toBeVisible();
    const local=provider==='Claude'||provider==='DSH'&&label==='分区';
    await expect(box.getByText('仅在 Bridge 中生效',{exact:true})).toHaveCount(local?1:0);
    await expect(box.getByRole('textbox',{name:label==='项目'?'新项目名称':'新分区名称',exact:true})).toHaveCount(local?1:0);
    await box.getByRole('button',{name:'返回会话菜单',exact:true}).click();
    await expect(box.locator('.sm-name strong')).toHaveText(provider+' · 页面交互验证');
   }
   await box.getByRole('button',{name:'停止任务并归档…',exact:true}).click();
   const confirm=box.getByRole('button',{name:'确认归档',exact:true}),cancel=box.getByRole('button',{name:'取消',exact:true});
   await expect(cancel).toBeFocused();
   const left=await confirm.boundingBox(),right=await cancel.boundingBox();
   expect(left.x).toBeLessThan(right.x);expect(Math.abs(left.width-right.width)).toBeLessThan(1);expect(left.height).toBe(right.height);
   const styles=await box.locator('.sm-confirm-actions button').evaluateAll(buttons=>buttons.map(b=>{const s=getComputedStyle(b);return [s.backgroundColor,s.color,s.borderRadius,s.fontSize];}));
   expect(styles[0]).toEqual(styles[1]);
   await page.screenshot({path:testInfo.outputPath(provider+'-'+theme+'-list-confirm.png')});
   await cancel.click();
   await expect(box.locator('.sm-name strong')).toHaveText(provider+' · 页面交互验证');
   await box.getByRole('button',{name:'停止任务并归档…',exact:true}).click();
   await box.dispatchEvent('cancel',{cancelable:true});
   await expect(box.locator('.sm-name strong')).toHaveText(provider+' · 页面交互验证');
   if(page.viewportSize().width<=640){
    const handle=box.locator('.sm-handle');
    await handle.dispatchEvent('pointerdown',{pointerType:'touch',pointerId:8,button:0,clientX:100,clientY:100});
    await handle.dispatchEvent('pointermove',{pointerType:'touch',pointerId:8,clientX:100,clientY:125});
    await handle.dispatchEvent('pointerup',{pointerType:'touch',pointerId:8,clientX:100,clientY:125});
    await expect(box).not.toHaveClass(/sm-returning/);
    await expect(box).toBeVisible();
    await handle.dispatchEvent('pointerdown',{pointerType:'touch',pointerId:8,button:0,clientX:100,clientY:100});
    await handle.dispatchEvent('pointermove',{pointerType:'touch',pointerId:8,clientX:100,clientY:260});
    await handle.dispatchEvent('pointerup',{pointerType:'touch',pointerId:8,clientX:100,clientY:260});
   }else await page.keyboard.press('Escape');
   await expect(box).toHaveCount(0);
  }
  const evidence=await page.evaluate(async()=>await(await fetch('/__state')).json());
  expect(evidence.writes.filter(path=>!path.endsWith('/activity'))).toEqual([]);
  expect(Object.keys(evidence.requests).filter(path=>/\/(detail|activate|resume)$/.test(path))).toEqual([]);
  expect(await page.evaluate(()=>window.__startupTest.errors)).toEqual([]);
 });
}

test('reset outlook is opt-in and fits both themes',async({page},testInfo)=>{
  await ready(page);
  await page.evaluate(()=>{
    const now=Date.now()/1000;
    const value={accounts:[],resetDynamicEnabled:true,reminders:{},globalReset:{state:'ready',updatedAt:now,checkedAt:now,lastResetAt:now-172800,probabilities:{h24:24,h48:48},confidence:'low'}};
    accountsPanel.read=async()=>value;
    accountsPanel.request=async request=>{if(request.action==='reminders')value.reminders={...value.reminders,...request.preferences};return value;};
    accountsPanel.accept(value);
    document.getElementById('accounts-dialog').showModal();
  });
  await expect(page.locator('label:has(#appearance-reset-dynamic)')).toHaveText('Codex官方重置动态');
  const card=page.locator('.accounts-global-reset');
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
    await expect(card).toBeVisible();
    await expect(card).toContainText('第三方统计与预测');
    await expect(card).toContainText('24%');
    await expect(card).toContainText('48%');
    await expect(card.getByRole('button',{name:'开启重置动态提醒'})).toHaveAttribute('aria-pressed','false');
    await expect(card.locator('.accounts-global-reminder')).toHaveText('提醒已关闭');
    await card.getByRole('button',{name:'开启重置动态提醒'}).click();
    await expect(card.locator('.accounts-global-reminder')).toHaveText('提醒已开启');
    await expect(card.getByRole('button',{name:'关闭重置动态提醒'})).toHaveAttribute('aria-pressed','true');
    await card.getByRole('button',{name:'关闭重置动态提醒'}).click();
    await expect(card.locator('.accounts-global-reminder')).toHaveText('提醒已关闭');
    const bounds=await card.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x+bounds.width).toBeLessThanOrEqual(page.viewportSize().width);
    await page.screenshot({path:testInfo.outputPath('reset-outlook-'+theme+'.png')});
  }
  const alignment=await page.evaluate(()=>{
    accountsPanel.tools.open=true;
    return [...accountsPanel.reminders.querySelectorAll('.account-reminder')].map(row=>{
      const measure=()=>{const a=row.querySelector('input').getBoundingClientRect(),b=row.querySelector('span').getBoundingClientRect();return Math.abs(a.y+a.height/2-b.y-b.height/2);};
      const normal=measure();row.style.width='160px';const wrapped=measure();row.style.width='';return {normal,wrapped};
    });
  });
  expect(alignment.length).toBeGreaterThan(0);
  for(const row of alignment){expect(row.normal).toBeLessThanOrEqual(1);expect(row.wrapped).toBeLessThanOrEqual(1);}
  await page.evaluate(()=>accountsPanel.accept({...accountsPanel.value,globalReset:{...accountsPanel.value.globalReset,state:'error',stale:true}}));
  await expect(card).toContainText('数据延迟');
  await expect(card.locator('.accounts-global-odds')).toHaveCount(0);
  await page.evaluate(()=>accountsPanel.accept({...accountsPanel.value,resetDynamicEnabled:false,globalReset:null}));
  await expect(card).toBeHidden();
});
