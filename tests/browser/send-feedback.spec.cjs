'use strict';
const {test,expect}=require('@playwright/test');

test.beforeEach(async({context,request,baseURL})=>{
 await context.route('**/*',route=>new URL(route.request().url()).origin===baseURL?route.continue():route.abort());
 expect(await(await request.get('/__fixture_health')).json()).toEqual({fixture:'cmb-browser-regression'});
});
for(const [provider,backend] of [['claude','code'],['claude','cowork'],['deepseek','desktop']])test(`${provider} ${backend} has immediate, scoped send feedback`,async({page},testInfo)=>{
 await page.goto('/?case=success');await expect(page.locator('#bootstrap-status')).toBeHidden();await page.waitForFunction(()=>typeof DesktopSessionsView==='function');
 await page.evaluate(async({provider,backend})=>{
  await BridgeFeatures.load('chat');document.getElementById('login').hidden=true;
  const root=document.createElement('div');root.className='app';root.id='send-feedback-root';root.style.cssText='position:fixed;inset:0;background:var(--page);z-index:10';document.body.append(root);
  const select=document.createElement('select');['codex','claude','deepseek'].forEach(id=>select.add(new Option(id,id)));
  const fixture=window.sendFeedbackFixture={writes:[],notices:[],finish:null};
  const detail={session:{id:'feedback-test',title:'发送交互验证',backend,status:'idle',capabilities:{send:true}},messages:[{id:'reply',role:'assistant',text:'可以发送一条测试消息。'}],connected:true};
  const view=fixture.view=new DesktopSessionsView({root,select,notify:text=>fixture.notices.push(text),onSelect(){},csrf:()=>'',onUnauthorized(){},request:async(url,body)=>{
   if(body){fixture.writes.push(body);return new Promise(resolve=>fixture.finish=resolve);}
   if(url.includes('/detail'))return detail;if(url.includes('/workspace'))return {entries:[],total:0,project:'/fixture'};
   return {sessions:[detail.session]};
  }});
  await view.choose(provider);await view.open('feedback-test');clearTimeout(view.timer);
 },{provider,backend});
 const composer=page.locator('#send-feedback-root .ds-composer'),input=composer.locator('textarea'),send=composer.locator('button[type=submit]'),feedback=composer.locator('.ds-send-feedback');
 await input.fill('请检查这条消息的发送状态，暂不执行任何任务。');await send.click();
 await expect(feedback).toBeVisible();await expect(feedback).toContainText('正在发送…');await expect(feedback).toContainText('请检查这条消息');await expect(send).toBeDisabled();
 expect(await page.evaluate(()=>sendFeedbackFixture.notices)).toEqual([]);
 for(const theme of ['light','dark']){
  await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
  await expect(feedback).toBeInViewport();
  expect(await feedback.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
  await page.screenshot({path:testInfo.outputPath(`${provider}-${backend}-${theme}-sending.png`)});
 }
 await input.fill('下一条草稿');
 await page.evaluate(()=>sendFeedbackFixture.finish({status:'accepted'}));
 await expect(feedback).toBeHidden();await expect(input).toHaveValue('下一条草稿');
 await expect.poll(()=>page.evaluate(()=>sendFeedbackFixture.notices)).toEqual(['已发送到会话']);
 await send.click();await expect(feedback).toBeVisible();
 await page.evaluate(()=>sendFeedbackFixture.finish({status:'unknown',message:'发送结果待核对'}));
 await expect(feedback).toBeHidden();await expect(input).toHaveValue('下一条草稿');await expect(composer.locator('.error')).toContainText('发送结果待核对');
 expect(await page.evaluate(()=>sendFeedbackFixture.writes.length)).toBe(2);
 expect(await page.evaluate(()=>sendFeedbackFixture.notices.filter(value=>value==='已发送到会话').length)).toBe(1);
 // A successful submission is distinct from ongoing native work. The indicator
 // remains in the real chat timeline and never reuses the send acknowledgement.
 await page.evaluate(()=>{const v=sendFeedbackFixture.view;v.applyDetail({connected:true,session:{...v.state,status:'active',requests:[]},messages:v.historyMessages});});
 const progress=page.locator('#send-feedback-root .ds-messages .working');
 await expect(progress).toBeVisible();await expect(progress).toContainText('正在工作…');
 expect(await progress.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
 await page.screenshot({path:testInfo.outputPath(`${provider}-${backend}-native-working.png`)});
 await page.evaluate(()=>sendFeedbackFixture.view.staleDetail());
 await expect(progress).toContainText('运行状态暂不可用');
 await page.evaluate(()=>{const v=sendFeedbackFixture.view;v.applyDetail({connected:true,session:{...v.state,status:'idle',requests:[]},messages:v.historyMessages});});
 await expect(progress).toBeHidden();
 await page.evaluate(()=>sendFeedbackFixture.view.clear());
});
