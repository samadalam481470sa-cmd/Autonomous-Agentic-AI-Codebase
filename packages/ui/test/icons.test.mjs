import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { build, ROOT } from '../build.mjs';
import {
  icons,
  iconNames,
  iconGrid,
  iconSvg,
  renderSprite,
  escapeText
} from '../src/icons.js';

const sprite = readFileSync(resolve(ROOT, 'icons.svg'), 'utf8');
const allowedAttributes = new Set([
  'd',
  'x',
  'y',
  'width',
  'height',
  'rx',
  'ry',
  'cx',
  'cy',
  'r',
  'x1',
  'y1',
  'x2',
  'y2'
]);

test('icon artifacts are generated and current', () => {
  assert.doesNotThrow(() => build({ check: true }));
});

test('icon set is substantial, unique, and labelled', () => {
  assert.ok(iconNames.length >= 40, `only ${iconNames.length} icons`);
  assert.equal(new Set(iconNames).size, iconNames.length);
  for (const name of iconNames) {
    const icon = icons[name];
    assert.match(name, /^[a-z][a-z0-9-]*$/);
    assert.ok(icon.label.length > 2, `${name} needs an accessible label`);
    assert.doesNotMatch(icon.label, /[<>]/);
  }
});

test('every glyph stays inside the 24px grid and uses only safe primitives', () => {
  for (const name of iconNames) {
    const body = icons[name].body;
    assert.ok(body.length > 10, `${name} is empty`);
    const tags = [...body.matchAll(/<([a-z]+)\b([^>]*)\/>/g)];
    assert.ok(tags.length > 0, `${name} has no primitives`);
    for (const [, tag, rawAttributes] of tags) {
      assert.ok(['path', 'rect', 'circle', 'ellipse', 'line'].includes(tag), `${name}: ${tag}`);
      for (const [, attribute, rawValue] of rawAttributes.matchAll(/([a-z-]+)="([^"]*)"/g)) {
        assert.ok(allowedAttributes.has(attribute), `${name}: attribute ${attribute}`);
        if (/^(x|y|width|height|rx|cx|cy|r|x1|y1|x2|y2)$/.test(attribute)) {
          assert.match(rawValue, /^-?\d+(\.\d+)?$/);
          const numeric = Number(rawValue);
          assert.ok(numeric >= 0 && numeric <= 24, `${name}: ${attribute}=${rawValue} outside grid`);
        }
        if (attribute === 'd') {
          assert.doesNotMatch(rawValue, /[<>]/, `${name}: unsafe path`);
          assert.doesNotMatch(rawValue, /[eE][+-]?\d/, `${name}: path must use explicit coordinates`);
        }
      }
    }
    assert.doesNotMatch(body, /fill=|stroke=|style=|on[a-z]+=/i, `${name}: glyph overrides presentation`);
  }
});

test('sprite contains a symbol for every icon and no stale symbols', () => {
  assert.equal((sprite.match(/<symbol /g) || []).length, iconNames.length);
  for (const name of iconNames) {
    assert.ok(sprite.includes(`<symbol id="ag-${name}"`), `missing symbol ${name}`);
    assert.ok(sprite.includes(icons[name].body), `missing body ${name}`);
  }
  assert.match(sprite, /stroke="currentColor"/);
  assert.match(sprite, /stroke-width="1.75"/);
  assert.doesNotMatch(sprite, /fill="(?!none)[^"]+"/);
  assert.equal(sprite, renderSprite());
});

test('standalone icon renderer is accessible and safe', () => {
  const decorative = iconSvg('spark');
  assert.match(decorative, /aria-hidden="true"/);
  assert.doesNotMatch(decorative, /role="img"/);
  const labelled = iconSvg('search', { title: 'Find & <replace>' });
  assert.match(labelled, /role="img"/);
  assert.match(labelled, /aria-labelledby="ag-icon-title-search"/);
  assert.match(labelled, /<title id="ag-icon-title-search">Find &amp; &lt;replace&gt;<\/title>/);
  assert.match(labelled, /width="24"/);
  assert.match(labelled, /viewBox="0 0 24 24"/);
  assert.throws(() => iconSvg('missing'), /Unknown icon/);
  assert.throws(() => iconSvg('spark', { size: 0 }), /positive/);
  assert.equal(escapeText('<script>'), '&lt;script&gt;');
});

test('the grid contract is explicit', () => {
  assert.deepEqual(iconGrid, {
    viewBox: '0 0 24 24',
    size: 24,
    strokeWidth: 1.75,
    liveArea: 20
  });
});
