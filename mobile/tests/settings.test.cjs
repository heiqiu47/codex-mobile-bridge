'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
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

test('Android hosts declare system appearance handling and settings themes', () => {
  for (const variant of ['android', 'android-push']) {
    assert.match(read(`mobile/${variant}/AndroidManifest.xml`), /android:configChanges="[^"]*\buiMode\b[^"]*"/);
  }
  for (const directory of ['values', 'values-night']) {
    assert.match(read(`mobile/android/res/${directory}/styles.xml`), /name="SettingsTheme"/);
  }
});
