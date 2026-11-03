# Axiom UI

First-party design tokens and an original icon set for Autonomous Agentic AI. It is maintained in this repository under the same MIT license as the application. No icon library, icon font, or proprietary design asset is vendored or required.

## Design principles

1. **Calm by default.** Dark graphite surfaces, one indigo accent, and status colour used only for status. The interface should recede so the code and the conversation remain the focus.
2. **Legible before decorative.** Every text/background pair in both themes is tested to WCAG 2.1 AA (4.5:1). Muted text is never used for essential content.
3. **One visual grammar.** Every icon is drawn on the same 24px grid with a 20px live area, 1.75px strokes, round joins, and `currentColor`. Icons never carry their own colour.
4. **Token, then component.** Components consume semantic roles (`--ag-bg-surface`, `--ag-text-muted`) rather than raw palette values. Themes swap roles, not markup.
5. **Local-first.** Everything is plain CSS, SVG, and ES modules. No runtime dependency, webfont, CDN, or build step is needed to serve the assets.

## Usage

The Python server exposes the generated assets at `/ui/`:

```html
<html data-theme="dark">
  <link rel="stylesheet" href="/ui/tokens.css">
  ...
  <svg class="ag-icon" aria-hidden="true"><use href="/ui/icons.svg#ag-spark"></use></svg>
</html>
```

Use `data-theme="light"` or `data-theme="dark"` to pin a theme. Without the attribute the stylesheet follows `prefers-color-scheme`.

From JavaScript:

```js
import { cssVar, iconSvg, tokenMap } from '@autonomous-agentic-ai/ui';

const surface = cssVar('bg-surface'); // "var(--ag-bg-surface)"
const markup = iconSvg('terminal', { title: 'Terminal' });
const dark = tokenMap('dark');
```

## Token contract

| Group | Example | Purpose |
| --- | --- | --- |
| Palette | `--ag-palette-indigo-500` | Raw, theme-independent colours |
| Surfaces | `--ag-bg-canvas`, `--ag-bg-surface`, `--ag-bg-raised` | Page and layered backgrounds |
| Text | `--ag-text-primary`, `--ag-text-secondary`, `--ag-text-muted` | Content hierarchy |
| Borders | `--ag-border-subtle`, `--ag-border-default` | Dividers and control edges |
| Accent | `--ag-accent`, `--ag-accent-hover`, `--ag-accent-subtle` | Primary actions and links |
| Status | `--ag-success`, `--ag-warning`, `--ag-danger`, `--ag-info` | State only, never decoration |
| Space | `--ag-space-1` … `--ag-space-24` | 4px-based spacing |
| Type | `--ag-font-sans`, `--ag-text-md`, `--ag-leading-normal` | Type roles and scale |
| Shape | `--ag-radius-md`, `--ag-border-width` | Corners and strokes |
| Motion | `--ag-duration-fast`, `--ag-ease-standard` | Transitions |
| Depth | `--ag-shadow-md`, `--ag-z-modal` | Elevation and layering |

The canonical values live in [`src/tokens.js`](src/tokens.js). Both themes must define the same semantic keys. `packages/ui/test/tokens.test.mjs` enforces key parity, generated-file freshness, and contrast.

## Icons

The set contains 43 original glyphs: `spark`, `chat`, `code`, `terminal`, `file`, `folder`, `search`, `play`, `send`, `check`, `close`, `chevron-right`, `chevron-down`, `plus`, `minus`, `settings`, `cpu`, `database`, `shield`, `branch`, `diff`, `cube`, `mic`, `download`, `upload`, `alert`, `lock`, `key`, `sun`, `moon`, `sidebar`, `refresh`, `trash`, `clock`, `link`, `external`, `copy`, `save`, `undo`, `redo`, `info`, `package`, `book`.

Rules for adding a glyph:

- 24×24 viewBox, keep artwork inside 2–22 on both axes.
- Strokes only; no fills, embedded colours, filters, masks, images, or scripts.
- Round caps and joins; 1.75px stroke; single continuous visual weight.
- Add a human label. Decorative use is `aria-hidden`; meaningful standalone use passes `title` to `iconSvg`.
- Run `node packages/ui/build.mjs` and commit the regenerated sprite. CI runs `--check` and the icon contract tests.

## Build and verify

```bash
node packages/ui/build.mjs          # regenerate tokens.css, icons.svg, favicon.svg, dist/
node packages/ui/build.mjs --check  # fail if committed artifacts are stale
node --test packages/ui/test        # token, contrast, icon, and freshness checks
```

## Provenance

All token values, glyph geometry, and build code in this package are first-party work authored for this repository. No third-party icon set, icon font, sprite, illustration, or design template is copied or bundled. The generated CSS loads no remote assets, and the generated sprite contains no external references. See [PROVENANCE.md](PROVENANCE.md).

The package is MIT licensed; see the repository [`LICENSE`](../../LICENSE). Original work remains the copyright of its authors and is licensed, not waived. Generated files are marked "do not edit" and excluded from authored line counts by `scripts/code_metrics.py`.
