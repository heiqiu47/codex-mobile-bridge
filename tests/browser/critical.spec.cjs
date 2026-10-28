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
