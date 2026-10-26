'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const java = name => read(`mobile/android/src/io/github/try2love/codexbridge/${name}.java`);
const colors = directory => new Map([...read(`mobile/android/res/${directory}/colors.xml`)
  .matchAll(/<color name="([^"]+)">([^<]+)<\/color>/g)].map(([, key, value]) => [key, value]));

function luminance(hex) {
  const channels = hex.slice(1).match(/../g).map(value => parseInt(value, 16) / 255)
    .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
}

test('settings palettes resolve the same resources with readable primary and secondary text', () => {
  const light = colors('values'), dark = colors('values-night');
  assert.deepEqual([...light.keys()].sort(), [...dark.keys()].sort());
  for (const palette of [light, dark]) {
    for (const surface of ['settings_page', 'settings_surface']) {
      for (const text of ['settings_text', 'settings_muted']) {
        const pair = [luminance(palette.get(surface)), luminance(palette.get(text))].sort((a, b) => b - a);
        assert.ok((pair[0] + .05) / (pair[1] + .05) >= 4.5, `${surface}: ${text}`);
      }
    }
  }
});

test('settings use a scoped theme, preserving the web appearance preference', () => {
  const ui = java('SettingsUi'), page = java('SettingsPage');
  assert.match(ui, /getString\("settingsTheme","system"\)/);
  assert.match(ui, /applyOverrideConfiguration\(config\)/);
  assert.match(page, /putString\("settingsTheme",value\)/);
  assert.match(page, /待开发项，暂时只支持设置页主题切换/);
  assert.doesNotMatch(ui + page, /bridge-appearance|evaluateJavascript|setDefaultNightMode/);
  for (const directory of ['values', 'values-night']) {
    assert.match(read(`mobile/android/res/${directory}/styles.xml`), /name="SettingsTheme"/);
  }
});

test('both Android variants retain their live host when system appearance changes', () => {
  for (const variant of ['android', 'android-push']) {
    assert.match(read(`mobile/${variant}/AndroidManifest.xml`), /android:configChanges="[^"]*\buiMode\b[^"]*"/);
  }
  const app = java('MainActivity');
  const settings = app.slice(app.indexOf(' void settings()'), app.indexOf(' String appVersion()'));
  assert.match(settings, /new SettingsPage\(this,0\)/);
  assert.doesNotMatch(settings, /clear\(|home\(|connect\(|web\.destroy/);
  assert.match(app, /state\.putBoolean\("settingsOpen",true\)/);
  assert.match(app, /state\.getBoolean\("settingsOpen",false\)/);
});

test('settings have translated local-theme choices and one separately labeled hint target', () => {
  const page = java('SettingsPage'), strings = java('MobileStrings');
  assert.match(page, /setContentDescription\(ui\.L\("主题功能说明"\)\)/);
  for (const label of ['主题', '跟随系统', '浅色', '深色', '后台接收', '系统权限', '前往授权', '已豁免']) {
    assert.ok(strings.includes(`values.put("${label}",`), label);
  }
  const fontPattern = /\btext\((?:"[^"]*"|name|title|value),(\d+),/g;
  const sizes = [...java('SettingsUi').matchAll(fontPattern), ...page.matchAll(fontPattern)]
    .map(match => Number(match[1]));
  assert.ok(sizes.every(size => size >= 12));
  assert.ok(new Set(sizes).size <= 3);
  assert.ok(!page.includes('\u00b7'));
});

test('settings motion respects system animator settings and suppresses cancelled completion actions', () => {
  const motion = java('SettingsMotion');
  assert.match(motion, /ValueAnimator\.areAnimatorsEnabled\(\)/);
  assert.match(motion, /if\(!enabled\(\)\)\{frame\.accept\(1f\);if\(complete!=null\)complete\.run\(\);return null;/);
  assert.match(motion, /onAnimationCancel\(Animator animation\)\{cancelled=true;/);
  assert.match(motion, /if\(!cancelled&&complete!=null\)complete\.run\(\)/);
  assert.match(motion, /closing\|\|super\.dispatchTouchEvent\(event\)/);
});

test('notification toggles keep their live controls while permission rows animate', () => {
  const page = java('SettingsPage'), ui = java('SettingsUi');
  assert.doesNotMatch(page, /notificationHost\.removeAllViews/);
  assert.match(page, /taskToggle\.checked\(alerts\);backgroundToggle\.checked\(background\)/);
  assert.match(page, /TransitionSet\.ORDERING_TOGETHER/);
  assert.match(ui, /info\.setChecked\(toggle\.isChecked\(\)\)/);
  assert.match(ui, /float start=position,target=checked\?1:0/);
  assert.match(ui, /onDetachedFromWindow\(\).*animator\.cancel\(\)/);
});

test('theme crossfade captures only the bounded native page and releases it on teardown', () => {
  const page = java('SettingsPage'), motion = java('SettingsMotion'), app = java('MainActivity');
  assert.match(page, /SettingsMotion\.capture\(screen\)/);
  assert.match(motion, /1200000d/);
  assert.match(page, /previousFrame\.recycle\(\)/);
  assert.match(page, /onStop\(\).*releaseFrame\(\);TransitionManager\.endTransitions\(body\)/);
  assert.match(app, /previous\.isClosing\(\)/);
  assert.doesNotMatch(motion, /WebView|PixelCopy|MediaProjection/);
});
