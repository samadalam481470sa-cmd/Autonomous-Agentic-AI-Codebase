/**
 * Build the Axiom design system artifacts.
 *
 * Generated files are committed so the Python server and plain static hosting
 * can serve them without a Node build step. `--check` verifies that they are
 * current and is what CI runs.
 */
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { renderTokensCss, tokenMap, themes } from './src/tokens.js';
import { renderSprite, renderFavicon, icons, iconGrid, iconNames } from './src/icons.js';

export const ROOT = dirname(fileURLToPath(import.meta.url));
export const OUTPUTS = [
  { path: 'tokens.css', contents: () => renderTokensCss() },
  { path: 'icons.svg', contents: () => renderSprite() },
  { path: 'favicon.svg', contents: () => renderFavicon() },
  {
    path: 'dist/tokens.json',
    contents: () =>
      `${JSON.stringify({ themes: Object.keys(themes), dark: tokenMap('dark'), light: tokenMap('light') }, null, 2)}\n`
  },
  {
    path: 'dist/icons.json',
    contents: () =>
      `${JSON.stringify({ grid: iconGrid, names: iconNames, icons }, null, 2)}\n`
  },
  { path: 'dist/tokens.css', contents: () => renderTokensCss() },
  { path: 'dist/icons.svg', contents: () => renderSprite() }
];

function readIfPresent(path) {
  return existsSync(path) ? readFileSync(path, 'utf8') : null;
}

/** Build all artifacts. With `check`, fail instead of writing stale output. */
export function build({ check = false } = {}) {
  const stale = [];
  for (const output of OUTPUTS) {
    const destination = resolve(ROOT, output.path);
    const expected = output.contents();
    const actual = readIfPresent(destination);
    if (actual === expected) continue;
    if (check) {
      stale.push(output.path);
      continue;
    }
    mkdirSync(dirname(destination), { recursive: true });
    writeFileSync(destination, expected, 'utf8');
  }
  if (stale.length) {
    throw new Error(
      `Generated UI artifacts are stale: ${stale.join(', ')}. Run: node packages/ui/build.mjs`
    );
  }
  return { checked: check, outputs: OUTPUTS.map(output => output.path) };
}

const invokedDirectly =
  process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;

if (invokedDirectly) {
  const check = process.argv.includes('--check');
  try {
    const result = build({ check });
    console.log(
      check
        ? `Axiom UI artifacts are current (${result.outputs.length} files).`
        : `Axiom UI built: ${result.outputs.join(', ')}`
    );
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
