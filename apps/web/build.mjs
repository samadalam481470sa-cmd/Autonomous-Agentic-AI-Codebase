/**
 * Bundle Monaco and its workers for same-origin, fully offline editor usage.
 * All third-party notices are preserved in assets.
 */
import esbuild from 'esbuild';
import { mkdirSync, readFileSync, writeFileSync, existsSync, copyFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build as buildUi } from '../../packages/ui/build.mjs';
const root = dirname(fileURLToPath(import.meta.url));
const assets = resolve(root,'assets');
const ui = resolve(root,'..','..','packages','ui');
mkdirSync(assets,{recursive:true});
await buildUi();
for (const name of ['tokens.css','icons.svg','favicon.svg']) {
  copyFileSync(resolve(ui,name),resolve(assets,name));
}
const workerRoot = resolve(root,'node_modules','monaco-editor','esm','vs');
const entryPoints = {
  'monaco-entry':resolve(root,'monaco-entry.js'),
  'editor.worker':resolve(workerRoot,'editor','editor.worker.js'),
  'json.worker':resolve(workerRoot,'language','json','json.worker.js'),
  'css.worker':resolve(workerRoot,'language','css','css.worker.js'),
  'html.worker':resolve(workerRoot,'language','html','html.worker.js'),
  'ts.worker':resolve(workerRoot,'language','typescript','ts.worker.js')
};
await esbuild.build({
  entryPoints,
  outdir:assets,
  bundle:true,
  splitting:false,
  minify:true,
  target:['es2022'],
  platform:'browser',
  format:'iife',
  entryNames:'[name]',
  assetNames:'media/[name]-[hash]',
  loader:{'.ttf':'file','.woff':'file','.woff2':'file','.svg':'file'},
  legalComments:'linked',
  logLevel:'info'
});
const licenseCandidates = [
  resolve(root,'node_modules','monaco-editor','LICENSE'),
  resolve(root,'node_modules','monaco-editor','LICENSE.txt'),
  resolve(root,'..','..','third_party','monaco-editor','LICENSE.txt')
];
const licenseFile = licenseCandidates.find(existsSync);
if (!licenseFile) throw new Error('Monaco MIT license notice is missing');
const license = readFileSync(licenseFile,'utf8');
writeFileSync(resolve(assets,'MONACO_LICENSE.txt'),license);
console.log('Monaco editor and workers bundled for local use.');
