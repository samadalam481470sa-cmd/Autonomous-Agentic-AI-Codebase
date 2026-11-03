/**
 * Axiom design tokens — the single source of truth for the Agentic UI.
 *
 * The committed `tokens.css` and `icons.svg` files are generated from this
 * module and `icons.js`. Never edit generated files by hand: run
 * `node packages/ui/build.mjs`.
 *
 * Naming contract:
 *   palette keys  -> --ag-palette-<key>
 *   theme keys    -> --ag-<key>          (e.g. --ag-bg-canvas)
 *   scale groups  -> --ag-<group>-<key>  (e.g. --ag-space-4)
 */

export const palette = {
  'graphite-980': '#060a12',
  'graphite-950': '#080d18',
  'graphite-900': '#0b1120',
  'graphite-850': '#0f1728',
  'graphite-800': '#141f33',
  'graphite-750': '#1b2942',
  'graphite-700': '#243552',
  'graphite-600': '#344a6b',
  'graphite-500': '#4d6386',
  'graphite-400': '#6f86a8',
  'graphite-300': '#98abc7',
  'graphite-200': '#c3d0e2',
  'graphite-100': '#e2e9f4',
  'graphite-50': '#f4f7fc',
  'indigo-300': '#b3beff',
  'indigo-400': '#929fff',
  'indigo-500': '#7285f8',
  'indigo-600': '#5a6eea',
  'indigo-700': '#4557cf',
  'indigo-800': '#3342a4',
  'teal-300': '#8af0dc',
  'teal-400': '#5fe3c8',
  'teal-500': '#2cc9ab',
  'teal-600': '#12a98e',
  'teal-700': '#0b7e6b',
  'amber-300': '#fbdfa1',
  'amber-400': '#f6cd73',
  'amber-500': '#eab24a',
  'amber-600': '#b97c15',
  'amber-700': '#845400',
  'rose-300': '#ffc2cc',
  'rose-400': '#ff9aab',
  'rose-500': '#f26d85',
  'rose-600': '#c23a55',
  'rose-700': '#a51f37',
  'sky-300': '#bfe6ff',
  'sky-400': '#8fd3ff',
  'sky-500': '#59b8ee',
  'sky-600': '#2d7ea8',
  'sky-700': '#0c567c'
};

/** Theme-dependent semantic roles. Both themes define exactly the same keys. */
export const themes = {
  dark: {
    'bg-canvas': '#080d18',
    'bg-surface': '#0d1422',
    'bg-raised': '#121c2d',
    'bg-overlay': '#172338',
    'bg-inset': '#090f1b',
    'bg-code': '#0a1220',
    'bg-hover': 'rgba(147,162,255,0.08)',
    'bg-active': 'rgba(147,162,255,0.14)',
    'border-subtle': '#1a2740',
    'border-default': '#293a58',
    'border-strong': '#3d5275',
    'text-primary': '#edf2fb',
    'text-secondary': '#b3c2da',
    'text-muted': '#8496b3',
    'text-inverse': '#ffffff',
    'text-on-accent': '#0a1024',
    accent: '#93a2ff',
    'accent-hover': '#b0bbff',
    'accent-pressed': '#7285f8',
    'accent-subtle': '#182047',
    'accent-subtle-text': '#c4ccff',
    success: '#5fe3c8',
    'success-subtle': '#0e2f2a',
    'success-text': '#6be8d0',
    warning: '#f6cd73',
    'warning-subtle': '#33260d',
    'warning-text': '#f8d78e',
    danger: '#ff9aab',
    'danger-subtle': '#34141d',
    'danger-text': '#ffadbb',
    info: '#8fd3ff',
    'info-subtle': '#0d2738',
    'info-text': '#a8ddff',
    'focus-ring': '#a8b4ff',
    selection: '#253468',
    'scrollbar-thumb': '#344a6b',
    'scrollbar-track': 'transparent',
    'overlay-backdrop': 'rgba(3,7,15,0.72)',
    'shadow-sm': '0 1px 2px rgba(0,0,0,0.35)',
    'shadow-md': '0 8px 24px rgba(0,0,0,0.32)',
    'shadow-lg': '0 24px 64px rgba(0,0,0,0.45)',
    'shadow-glow':
      '0 0 0 1px rgba(147,162,255,0.28), 0 0 32px rgba(114,133,248,0.18)'
  },
  light: {
    'bg-canvas': '#f4f7fc',
    'bg-surface': '#ffffff',
    'bg-raised': '#ffffff',
    'bg-overlay': '#f9fbff',
    'bg-inset': '#edf2f9',
    'bg-code': '#f0f4fa',
    'bg-hover': 'rgba(69,87,207,0.06)',
    'bg-active': 'rgba(69,87,207,0.10)',
    'border-subtle': '#e4eaf3',
    'border-default': '#cdd7e6',
    'border-strong': '#a6b4c9',
    'text-primary': '#111a2b',
    'text-secondary': '#47566f',
    'text-muted': '#5b6d88',
    'text-inverse': '#ffffff',
    'text-on-accent': '#ffffff',
    accent: '#4557cf',
    'accent-hover': '#3342a4',
    'accent-pressed': '#26317c',
    'accent-subtle': '#e9ecff',
    'accent-subtle-text': '#2f3c9e',
    success: '#0b7e6b',
    'success-subtle': '#e3f7f2',
    'success-text': '#0b6b5b',
    warning: '#845400',
    'warning-subtle': '#fdf3dc',
    'warning-text': '#6f4700',
    danger: '#b3263f',
    'danger-subtle': '#fde9ed',
    'danger-text': '#a51f37',
    info: '#0c567c',
    'info-subtle': '#e5f3fb',
    'info-text': '#0a4b6d',
    'focus-ring': '#3f4fd6',
    selection: '#dde3ff',
    'scrollbar-thumb': '#b9c6d9',
    'scrollbar-track': 'transparent',
    'overlay-backdrop': 'rgba(15,23,40,0.45)',
    'shadow-sm': '0 1px 2px rgba(23,38,64,0.08)',
    'shadow-md': '0 8px 24px rgba(23,38,64,0.10)',
    'shadow-lg': '0 24px 64px rgba(23,38,64,0.16)',
    'shadow-glow':
      '0 0 0 1px rgba(69,87,207,0.22), 0 0 32px rgba(69,87,207,0.12)'
  }
};

/** Theme-independent scales. Values are complete CSS values. */
export const scales = {
  space: {
    0: '0',
    1: '4px',
    2: '8px',
    3: '12px',
    4: '16px',
    5: '20px',
    6: '24px',
    8: '32px',
    10: '40px',
    12: '48px',
    16: '64px',
    20: '80px',
    24: '96px'
  },
  radius: {
    none: '0',
    xs: '4px',
    sm: '6px',
    md: '8px',
    lg: '12px',
    xl: '16px',
    '2xl': '20px',
    pill: '999px'
  },
  font: {
    sans: '"Inter", "SF Pro Text", system-ui, -apple-system, "Segoe UI", sans-serif',
    mono: '"JetBrains Mono", "SFMono-Regular", ui-monospace, "Cascadia Code", monospace'
  },
  text: {
    '2xs': '11px',
    xs: '12px',
    sm: '13px',
    md: '14px',
    lg: '16px',
    xl: '20px',
    '2xl': '24px',
    '3xl': '32px',
    '4xl': '40px',
    '5xl': '52px'
  },
  leading: {
    none: '1',
    tight: '1.2',
    snug: '1.35',
    normal: '1.55',
    relaxed: '1.7'
  },
  weight: {
    regular: '400',
    medium: '500',
    semibold: '600',
    bold: '700'
  },
  tracking: {
    tight: '-0.02em',
    normal: '0',
    wide: '0.04em'
  },
  border: {
    width: '1px',
    'width-strong': '2px'
  },
  control: {
    sm: '28px',
    md: '36px',
    lg: '44px'
  },
  icon: {
    xs: '12px',
    sm: '16px',
    md: '20px',
    lg: '24px',
    xl: '32px',
    stroke: '1.75'
  },
  duration: {
    instant: '0ms',
    fast: '120ms',
    base: '180ms',
    slow: '280ms'
  },
  ease: {
    standard: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
    exit: 'cubic-bezier(0.4, 0, 1, 1)',
    spring: 'cubic-bezier(0.34, 1.56, 0.64, 1)'
  },
  z: {
    base: '0',
    dropdown: '1000',
    sticky: '1100',
    overlay: '1200',
    modal: '1300',
    toast: '1400'
  },
  layout: {
    'sidebar-width': '272px',
    'topbar-height': '64px',
    'content-max': '1440px',
    'prose-max': '72ch'
  },
  blur: {
    sm: '8px',
    md: '16px'
  }
};

/** All CSS custom properties that are not theme-dependent. */
export function baseDeclarations() {
  const entries = [];
  for (const [key, value] of Object.entries(palette)) {
    entries.push([`--ag-palette-${key}`, value]);
  }
  for (const [group, values] of Object.entries(scales)) {
    for (const [key, value] of Object.entries(values)) {
      entries.push([`--ag-${group}-${key}`, value]);
    }
  }
  return entries;
}

/** All semantic CSS custom properties for one theme. */
export function themeDeclarations(theme = 'dark') {
  if (!themes[theme]) throw new TypeError(`Unknown theme: ${theme}`);
  return Object.entries(themes[theme]).map(([key, value]) => [`--ag-${key}`, value]);
}

/** A flat token map for the requested theme, useful in JavaScript. */
export function tokenMap(theme = 'dark') {
  return Object.fromEntries([...baseDeclarations(), ...themeDeclarations(theme)]);
}

/** Resolve a token by key, e.g. cssVar('bg-canvas') or cssVar('space-4'). */
export function cssVar(name) {
  return `var(--ag-${name})`;
}

/** Render the complete, deterministic stylesheet. */
export function renderTokensCss() {
  const root = [
    '  color-scheme: dark;',
    ...baseDeclarations().map(([name, value]) => `  ${name}: ${value};`),
    ...themeDeclarations('dark').map(([name, value]) => `  ${name}: ${value};`)
  ].join('\n');
  const light = themeDeclarations('light')
    .map(([name, value]) => `    ${name}: ${value};`)
    .join('\n');
  return `/* Axiom design tokens. Generated by packages/ui/build.mjs — do not edit. */
:root {
${root}
}

:root[data-theme="dark"] {
  color-scheme: dark;
}

:root[data-theme="light"] {
  color-scheme: light;
${light}
}

@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) {
    color-scheme: light;
${light}
  }
}

*,
*::before,
*::after {
  box-sizing: border-box;
}

::selection {
  background: var(--ag-selection);
  color: var(--ag-text-primary);
}

:focus-visible {
  outline: 2px solid var(--ag-focus-ring);
  outline-offset: 2px;
}

.ag-icon {
  display: inline-block;
  width: 1em;
  height: 1em;
  flex: none;
  fill: none;
  stroke: currentColor;
  stroke-width: var(--ag-icon-stroke);
  stroke-linecap: round;
  stroke-linejoin: round;
  vertical-align: -0.125em;
}

.ag-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (prefers-reduced-motion: reduce) {
  :root {
    --ag-duration-fast: 0ms;
    --ag-duration-base: 0ms;
    --ag-duration-slow: 0ms;
  }
}
`;
}
