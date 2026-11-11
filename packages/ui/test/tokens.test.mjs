import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { build, ROOT } from '../build.mjs';
import {
  palette,
  themes,
  scales,
  baseDeclarations,
  themeDeclarations,
  tokenMap
} from '../src/tokens.js';

const css = readFileSync(resolve(ROOT, 'tokens.css'), 'utf8');

test('committed generated artifacts are current', () => {
  assert.doesNotThrow(() => build({ check: true }));
});

test('every canonical token is present in the stylesheet', () => {
  for (const [name, value] of [...baseDeclarations(), ...themeDeclarations('dark'), ...themeDeclarations('light')]) {
    assert.ok(css.includes(`${name}: ${value};`), `missing ${name}`);
  }
});

test('themes define identical semantic keys', () => {
  assert.deepEqual(Object.keys(themes.dark).sort(), Object.keys(themes.light).sort());
  assert.ok(Object.keys(themes.dark).length >= 40);
});

test('token names are unique and namespaced', () => {
  const names = [...baseDeclarations(), ...themeDeclarations('dark')].map(([name]) => name);
  assert.equal(new Set(names).size, names.length);
  assert.ok(names.every(name => name.startsWith('--ag-')));
});

test('token maps resolve both themes', () => {
  assert.equal(tokenMap('dark')['--ag-bg-canvas'], palette['graphite-950']);
  assert.equal(tokenMap('light')['--ag-bg-canvas'], '#f4f7fc');
  assert.equal(tokenMap('dark')['--ag-space-4'], scales.space[4]);
});

function channel(value) {
  const normalized = value / 255;
  return normalized <= 0.04045
    ? normalized / 12.92
    : Math.pow((normalized + 0.055) / 1.055, 2.4);
}

function luminance(hex) {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  assert.ok(match, `expected opaque hex color, got ${hex}`);
  const number = Number.parseInt(match[1], 16);
  const r = channel((number >> 16) & 255);
  const g = channel((number >> 8) & 255);
  const b = channel(number & 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(foreground, background) {
  const a = luminance(foreground);
  const b = luminance(background);
  const lighter = Math.max(a, b);
  const darker = Math.min(a, b);
  return (lighter + 0.05) / (darker + 0.05);
}

const textPairs = [
  ['text-primary', 'bg-canvas'],
  ['text-primary', 'bg-surface'],
  ['text-primary', 'bg-raised'],
  ['text-primary', 'bg-code'],
  ['text-secondary', 'bg-canvas'],
  ['text-secondary', 'bg-surface'],
  ['text-muted', 'bg-canvas'],
  ['text-muted', 'bg-surface'],
  ['accent', 'bg-canvas'],
  ['accent', 'bg-surface'],
  ['success', 'bg-canvas'],
  ['warning', 'bg-canvas'],
  ['danger', 'bg-canvas'],
  ['info', 'bg-canvas'],
  ['success-text', 'success-subtle'],
  ['warning-text', 'warning-subtle'],
  ['danger-text', 'danger-subtle'],
  ['info-text', 'info-subtle'],
  ['accent-subtle-text', 'accent-subtle']
];

for (const themeName of Object.keys(themes)) {
  test(`${themeName} theme meets WCAG AA text contrast`, () => {
    const theme = themes[themeName];
    for (const [foreground, background] of textPairs) {
      const ratio = contrast(theme[foreground], theme[background]);
      assert.ok(
        ratio >= 4.5,
        `${themeName}: ${foreground} on ${background} is ${ratio.toFixed(2)}:1`
      );
    }
  });

  test(`${themeName} theme meets AA for accent button text`, () => {
    const theme = themes[themeName];
    for (const accent of ['accent', 'accent-hover', 'accent-pressed']) {
      const ratio = contrast(theme['text-on-accent'], theme[accent]);
      assert.ok(
        ratio >= 4.5,
        `${themeName}: text-on-accent on ${accent} is ${ratio.toFixed(2)}:1`
      );
    }
  });

  test(`${themeName} theme keeps focus indicators at 3:1`, () => {
    const theme = themes[themeName];
    const ratio = contrast(theme['focus-ring'], theme['bg-canvas']);
    assert.ok(ratio >= 3, `${themeName}: focus-ring on bg-canvas is ${ratio.toFixed(2)}:1`);
  });
}

test('palette uses one consistent six-digit hex format', () => {
  for (const [name, value] of Object.entries(palette)) {
    assert.match(value, /^#[0-9a-f]{6}$/i, name);
  }
});
