'use strict';
const {test, expect} = require('@playwright/test');

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

for (const scenario of ['success', 'css-once', 'js-twice', 'js-fatal', 'runtime']) {
  test('startup and login: ' + scenario, async ({page, browserName}, testInfo) => {
    await ready(page, scenario);
    const evidence = await page.evaluate(async () => ({
      state: await (await fetch('/__state')).json(), probe: window.__startupTest,
      status: document.getElementById('bootstrap-status').dataset.state,
      diagnostic: document.getElementById('bootstrap-details').textContent,
    }));
    await testInfo.attach('startup-evidence', {body: JSON.stringify(evidence), contentType: 'application/json'});
    // v2.1.6 WebKit can reuse the first failed script fetch for all retries.
    // Only this observed signature is an expected failure, never a general WebKit skip.
    const knownRetryFailure = browserName === 'webkit' && scenario === 'js-twice'
      && evidence.status === 'failed' && evidence.state.requests['/i18n.js'] === 1
      && evidence.diagnostic.includes('resource @ /i18n.js')
      && evidence.probe.errors.length === 0 && !evidence.probe.executed.includes('/app.js');
    expect(evidence.state.writes).toEqual([]);
    if (knownRetryFailure) {
      testInfo.annotations.push({type: 'known-baseline',
        description: 'v2.1.6 WebKit failed-URL cache; related PR #88 is not included in this test-only change.'});
      test.fail(true, 'Known v2.1.6 failure: https://github.com/try2love/codex-mobile-bridge/pull/88');
    }
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
