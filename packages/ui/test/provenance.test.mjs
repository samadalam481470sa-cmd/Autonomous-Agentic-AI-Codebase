import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { ROOT } from '../build.mjs';

const tokens = readFileSync(resolve(ROOT, 'tokens.css'), 'utf8');
const sprite = readFileSync(resolve(ROOT, 'icons.svg'), 'utf8');
const sources = [
  readFileSync(resolve(ROOT, 'src', 'tokens.js'), 'utf8'),
  readFileSync(resolve(ROOT, 'src', 'icons.js'), 'utf8')
].join('\n');
const manifest = JSON.parse(readFileSync(resolve(ROOT, 'package.json'), 'utf8'));
const provenance = readFileSync(resolve(ROOT, 'PROVENANCE.md'), 'utf8');

test('tokens load no remote or embedded assets', () => {
  assert.doesNotMatch(tokens, /@import/i);
  assert.doesNotMatch(tokens, /url\s*\(/i);
  assert.doesNotMatch(tokens, /https?:\/\//i);
  assert.doesNotMatch(tokens, /data:/i);
});

test('sprite contains only local symbols and no external or embedded artwork', () => {
  assert.doesNotMatch(sprite, /<image\b/i);
  assert.doesNotMatch(sprite, /xlink:href/i);
  assert.doesNotMatch(sprite, /href\s*=\s*["'](?:https?:|data:|\/\/)/i);
  for (const match of sprite.matchAll(/<use\b[^>]*href="([^"]+)"/gi)) {
    assert.match(match[1], /^#ag-[a-z0-9-]+$/, `external sprite reference: ${match[1]}`);
  }
});

test('design sources reference no remote artwork', () => {
  const withoutNamespaces = sources.replaceAll('xmlns="http://www.w3.org/2000/svg"', '');
  assert.doesNotMatch(withoutNamespaces, /https?:\/\//i);
  assert.doesNotMatch(withoutNamespaces, /data:image/i);
  assert.doesNotMatch(withoutNamespaces, /<image\b/i);
});

test('originality record is shipped with the package', () => {
  assert.match(provenance, /created for this repository/i);
  assert.match(provenance, /No third-party icon set/i);
  assert.match(provenance, /MIT license/i);
  assert.ok(manifest.files.includes('PROVENANCE.md'));
  assert.equal(manifest.license, 'MIT');
});
