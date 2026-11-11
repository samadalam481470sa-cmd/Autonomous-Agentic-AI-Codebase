/**
 * Axiom Icons — an original first-party icon set.
 *
 * Every glyph is drawn on a 24×24 grid with a 20px live area, 1.75px strokes,
 * round caps/joins, and no fills. Glyphs are single-color and inherit
 * `currentColor`, so one sprite works in every theme.
 */

const definitions = [
  { name: 'spark', label: 'Agent spark', body: '<path d="M12 3l1.6 6.4L20 11l-6.4 1.6L12 19l-1.6-6.4L4 11l6.4-1.6L12 3z"/>' },
  { name: 'chat', label: 'Conversation', body: '<path d="M5 6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v6a2.5 2.5 0 0 1-2.5 2.5H12l-5 3.5v-3.5H7.5A2.5 2.5 0 0 1 5 12.5z"/>' },
  { name: 'code', label: 'Code', body: '<path d="M9 7 4.5 12 9 17"/><path d="M15 7l4.5 5L15 17"/>' },
  { name: 'terminal', label: 'Terminal', body: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M7 9l3 3-3 3"/><path d="M12.5 15H17"/>' },
  { name: 'file', label: 'File', body: '<path d="M7 3h6.5L18 7.5V20a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M13.5 3v4.5H18"/>' },
  { name: 'folder', label: 'Folder', body: '<path d="M3.5 7A2.5 2.5 0 0 1 6 4.5h3.4c.5 0 1 .2 1.4.6l1.3 1.3c.4.4.9.6 1.4.6H18A2.5 2.5 0 0 1 20.5 9.5v7A2.5 2.5 0 0 1 18 19H6a2.5 2.5 0 0 1-2.5-2.5z"/>' },
  { name: 'search', label: 'Search', body: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 20.5 20.5"/>' },
  { name: 'play', label: 'Play', body: '<path d="M8 5.5v13l10-6.5z"/>' },
  { name: 'send', label: 'Send', body: '<path d="M20 4 4 11l6.5 2.5L13 20z"/><path d="M10.5 13.5 20 4"/>' },
  { name: 'check', label: 'Check', body: '<path d="M4.5 12.5 9.5 17.5 19.5 6.5"/>' },
  { name: 'close', label: 'Close', body: '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>' },
  { name: 'chevron-right', label: 'Expand', body: '<path d="M9 6l6 6-6 6"/>' },
  { name: 'chevron-down', label: 'Collapse', body: '<path d="M6 9l6 6 6-6"/>' },
  { name: 'plus', label: 'Add', body: '<path d="M12 5v14"/><path d="M5 12h14"/>' },
  { name: 'minus', label: 'Remove', body: '<path d="M5 12h14"/>' },
  { name: 'settings', label: 'Settings', body: '<path d="M4 7h9"/><path d="M19 7h1"/><circle cx="16" cy="7" r="2.5"/><path d="M4 17h1"/><path d="M11 17h9"/><circle cx="8" cy="17" r="2.5"/>' },
  { name: 'cpu', label: 'Processor', body: '<rect x="7" y="7" width="10" height="10" rx="2"/><rect x="10" y="10" width="4" height="4" rx="1"/><path d="M9.5 3.5V7M14.5 3.5V7M9.5 17v3.5M14.5 17v3.5M3.5 9.5H7M3.5 14.5H7M17 9.5h3.5M17 14.5h3.5"/>' },
  { name: 'database', label: 'Database', body: '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>' },
  { name: 'shield', label: 'Security', body: '<path d="M12 3.5 19 6v5.5c0 4.3-3 7.3-7 9-4-1.7-7-4.7-7-9V6z"/>' },
  { name: 'branch', label: 'Branch', body: '<circle cx="6" cy="5" r="2.5"/><circle cx="6" cy="19" r="2.5"/><circle cx="18" cy="8" r="2.5"/><path d="M6 7.5v9"/><path d="M18 10.5c0 3.5-3.5 5-7 5H6"/>' },
  { name: 'diff', label: 'Diff', body: '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 9h4"/><path d="M8 15h8"/><path d="M16 7.5v5"/><path d="M13.5 10h5"/>' },
  { name: 'cube', label: 'Model', body: '<path d="M12 3 20 7.5v9L12 21 4 16.5v-9z"/><path d="M4 7.5 12 12l8-4.5"/><path d="M12 12v9"/>' },
  { name: 'mic', label: 'Microphone', body: '<path d="M12 4a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3z"/><path d="M6.5 11.5a5.5 5.5 0 0 0 11 0"/><path d="M12 17v3"/><path d="M9 20h6"/>' },
  { name: 'download', label: 'Download', body: '<path d="M12 4v10"/><path d="M8 10.5l4 4 4-4"/><path d="M5 19h14"/>' },
  { name: 'upload', label: 'Upload', body: '<path d="M12 20V10"/><path d="M8 13.5l4-4 4 4"/><path d="M5 5h14"/>' },
  { name: 'alert', label: 'Warning', body: '<path d="M10.3 4.3 2.7 17.5A1.6 1.6 0 0 0 4.1 20h15.8a1.6 1.6 0 0 0 1.4-2.5L13.7 4.3a2 2 0 0 0-3.4 0z"/><path d="M12 9v5"/><path d="M12 17.5h.01"/>' },
  { name: 'lock', label: 'Locked', body: '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/><path d="M12 14v2"/>' },
  { name: 'key', label: 'Key', body: '<circle cx="8" cy="16" r="4"/><path d="M11 13 20 4"/><path d="M16 8l2 2"/><path d="M18 6l2 2"/>' },
  { name: 'sun', label: 'Light theme', body: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4"/>' },
  { name: 'moon', label: 'Dark theme', body: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z"/>' },
  { name: 'sidebar', label: 'Sidebar', body: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="M9 5v14"/><path d="M6.5 8h.01M6.5 11h.01M6.5 14h.01"/>' },
  { name: 'refresh', label: 'Refresh', body: '<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v4.5h-4.5"/>' },
  { name: 'trash', label: 'Delete', body: '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6.5 7l1 13h9l1-13"/><path d="M10 11v5M14 11v5"/>' },
  { name: 'clock', label: 'Time', body: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/>' },
  { name: 'link', label: 'Link', body: '<path d="M9 15l6-6"/><path d="M10.5 6.5l1.8-1.8a4 4 0 0 1 5.7 5.7l-1.8 1.8"/><path d="M13.5 17.5l-1.8 1.8a4 4 0 0 1-5.7-5.7l1.8-1.8"/>' },
  { name: 'external', label: 'Open externally', body: '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6"/>' },
  { name: 'copy', label: 'Copy', body: '<rect x="9" y="9" width="11" height="11" rx="1.5"/><path d="M15 9V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h4"/>' },
  { name: 'save', label: 'Save', body: '<path d="M4 5a1 1 0 0 1 1-1h12l3 3v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z"/><path d="M8 4v6h7V4"/><path d="M7 20v-6h10v6"/>' },
  { name: 'undo', label: 'Undo', body: '<path d="M4 9h11a5 5 0 0 1 0 10h-4"/><path d="M8 5 4 9l4 4"/>' },
  { name: 'redo', label: 'Redo', body: '<path d="M20 9H9a5 5 0 0 0 0 10h4"/><path d="M16 5l4 4-4 4"/>' },
  { name: 'info', label: 'Information', body: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 7.5h.01"/>' },
  { name: 'package', label: 'Package', body: '<path d="M4 8l8-4 8 4v8l-8 4-8-4z"/><path d="M4 8l8 4 8-4"/><path d="M12 12v8"/>' },
  { name: 'book', label: 'Documentation', body: '<path d="M12 6c-1.5-1.3-3.4-2-5.5-2H4v14h2.5c2.1 0 4 .7 5.5 2 1.5-1.3 3.4-2 5.5-2H20V4h-2.5c-2.1 0-4 .7-5.5 2z"/><path d="M12 6v14"/>' }
];

const allowedTags = /^(path|rect|circle|ellipse|line)$/;

export const icons = Object.freeze(
  Object.fromEntries(
    definitions.map(definition => [definition.name, Object.freeze(definition)])
  )
);

export const iconNames = Object.freeze(definitions.map(definition => definition.name));

export const iconGrid = Object.freeze({
  viewBox: '0 0 24 24',
  size: 24,
  strokeWidth: 1.75,
  liveArea: 20
});

/** Render one standalone SVG string. Icons are decorative unless a title is given. */
export function iconSvg(name, { size = 24, title, className = 'ag-icon' } = {}) {
  const icon = icons[name];
  if (!icon) throw new TypeError(`Unknown icon: ${name}`);
  if (!Number.isFinite(size) || size <= 0) throw new TypeError('Icon size must be positive');
  const titleId = title ? `ag-icon-title-${name}` : null;
  const label = title
    ? ` role="img" aria-labelledby="${titleId}"`
    : ' aria-hidden="true"';
  const titleElement = title ? `<title id="${titleId}">${escapeText(title)}</title>` : '';
  return `<svg class="${className}" xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="${iconGrid.viewBox}" fill="none" stroke="currentColor" stroke-width="${iconGrid.strokeWidth}" stroke-linecap="round" stroke-linejoin="round"${label}>${titleElement}${icon.body}</svg>`;
}

/** Render the shared sprite. IDs are prefixed to avoid collisions with app markup. */
export function renderSprite() {
  const symbols = definitions
    .map(
      icon =>
        `  <symbol id="ag-${icon.name}" viewBox="${iconGrid.viewBox}" fill="none" stroke="currentColor" stroke-width="${iconGrid.strokeWidth}" stroke-linecap="round" stroke-linejoin="round">${icon.body}</symbol>`
    )
    .join('\n');
  return `<svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true" style="display:none">\n${symbols}\n</svg>\n`;
}

/** A small standalone brand mark, also used as the favicon. */
export function renderFavicon() {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="6" fill="#080d18"/><path d="M12 3.5l1.5 6L19.5 11l-6 1.5L12 18.5l-1.5-6L4.5 11l6-1.5L12 3.5z" fill="none" stroke="#93a2ff" stroke-width="1.75" stroke-linejoin="round"/></svg>\n`;
}

export function escapeText(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

export { definitions, allowedTags };
