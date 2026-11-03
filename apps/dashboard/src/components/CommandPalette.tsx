import { useEffect, useMemo, useRef, useState } from 'react';
import { CommandIcon, FilesIcon } from '../icons';

export interface PaletteAction {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

interface Item {
  key: string;
  label: string;
  hint: string;
  kind: 'action' | 'file';
  run: () => void;
}

interface Props {
  open: boolean;
  actions: PaletteAction[];
  files: string[];
  onClose: () => void;
  onOpenFile: (path: string) => void;
}

export default function CommandPalette({ open, actions, files, onClose, onOpenFile }: Props) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQuery('');
    setActive(0);
    const timer = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const needle = query.trim().toLowerCase();
    const actionItems = actions
      .filter((action) => {
        if (!needle) return true;
        return (
          action.label.toLowerCase().includes(needle) ||
          (action.hint ?? '').toLowerCase().includes(needle)
        );
      })
      .map<Item>((action) => ({
        key: `action:${action.id}`,
        label: action.label,
        hint: action.hint ?? '',
        kind: 'action',
        run: action.run,
      }));
    const fileItems = needle
      ? files
          .filter((file) => file.toLowerCase().includes(needle))
          .slice(0, 40)
          .map<Item>((file) => ({
            key: `file:${file}`,
            label: file,
            hint: 'Open file',
            kind: 'file',
            run: () => onOpenFile(file),
          }))
      : [];
    return [...actionItems, ...fileItems];
  }, [actions, files, query, onOpenFile]);

  useEffect(() => {
    setActive((current) => Math.min(current, Math.max(0, items.length - 1)));
  }, [items.length]);

  if (!open) return null;

  function choose(index: number) {
    const item = items[index];
    if (!item) return;
    item.run();
    onClose();
  }

  return (
    <div
      className="palette-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="palette">
        <div className="palette-input">
          <CommandIcon size={16} />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search commands and files"
            aria-label="Search commands and files"
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                onClose();
              } else if (event.key === 'ArrowDown') {
                event.preventDefault();
                setActive((index) => Math.min(index + 1, Math.max(0, items.length - 1)));
              } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                setActive((index) => Math.max(index - 1, 0));
              } else if (event.key === 'Enter') {
                event.preventDefault();
                choose(active);
              }
            }}
          />
          <kbd>Esc</kbd>
        </div>
        <div className="palette-list">
          {items.length === 0 ? (
            <p className="palette-empty">No matching commands or files.</p>
          ) : (
            items.map((item, index) => (
              <button
                key={item.key}
                className={`palette-item ${index === active ? 'active' : ''}`}
                onMouseEnter={() => setActive(index)}
                onClick={() => choose(index)}
              >
                {item.kind === 'file' ? <FilesIcon size={15} /> : <CommandIcon size={15} />}
                <span className="palette-label">{item.label}</span>
                <span className="palette-hint">{item.hint}</span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
