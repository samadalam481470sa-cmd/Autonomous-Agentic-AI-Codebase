interface IconProps {
  size?: number;
}

function frame(size = 16) {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.7,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };
}

export function LogoMark({ size = 22 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <path d="M16 2.5 28 9.4v13.2L16 29.5 4 22.6V9.4Z" fill="none" stroke="currentColor" strokeWidth="1.7" />
      <path d="M16 9.2 22.5 22h-4l-2.5-5.6L13.5 22h-4Z" fill="currentColor" opacity="0.92" />
    </svg>
  );
}

export function FilesIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M6 3.5h7.5L19 9v11.5H6z" />
      <path d="M13 3.5V9h6" />
      <path d="M9 13h7M9 16.5h7" />
    </svg>
  );
}

export function SearchIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <circle cx="10.8" cy="10.8" r="6.3" />
      <path d="m15.6 15.6 4.4 4.4" />
    </svg>
  );
}

export function ShieldIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M12 3.2 19.5 6v5.4c0 4.5-3.1 7.8-7.5 9.4-4.4-1.6-7.5-4.9-7.5-9.4V6Z" />
      <path d="m8.8 11.9 2.2 2.2 4.2-4.4" />
    </svg>
  );
}

export function SettingsIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <circle cx="12" cy="12" r="3.1" />
      <path d="M12 3.4v2.2M12 18.4v2.2M4.9 7.9l1.9 1.1M17.2 15l1.9 1.1M4.9 16.1l1.9-1.1M17.2 9l1.9-1.1" />
    </svg>
  );
}

export function SendIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M4.5 12 20 4.5 15.8 20l-4-6.4Z" />
      <path d="M11.8 13.6 20 4.5" />
    </svg>
  );
}

export function PlayIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M7.5 5.5 18.5 12 7.5 18.5Z" />
    </svg>
  );
}

export function PlusIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function RefreshIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M19 8.5A7.5 7.5 0 1 0 19.4 15" />
      <path d="M19 4.5v4h-4" />
    </svg>
  );
}

export function CloseIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="m6 6 12 12M18 6 6 18" />
    </svg>
  );
}

export function CommandIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M8.5 4.5A2.5 2.5 0 1 0 11 7v10a2.5 2.5 0 1 0 2.5-2.5h-6A2.5 2.5 0 1 0 10 17V7a2.5 2.5 0 1 0-1.5-2.5Z" />
    </svg>
  );
}

export function SparkIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M12 3.5v4M12 16.5v4M4.8 12h4M15.2 12h4M6.9 6.9l2.8 2.8M14.3 14.3l2.8 2.8M17.1 6.9l-2.8 2.8M9.7 14.3l-2.8 2.8" />
    </svg>
  );
}

export function ChevronIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

export function BotIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <rect x="4.5" y="8" width="15" height="10.5" rx="3" />
      <path d="M12 4.5V8M9 12.5h.01M15 12.5h.01M9.5 15.5h5" />
    </svg>
  );
}

export function DeviceIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <rect x="7" y="7" width="10" height="10" rx="2" />
      <path d="M9.5 3.5V7M14.5 3.5V7M9.5 17v3.5M14.5 17v3.5M3.5 9.5H7M3.5 14.5H7M17 9.5h3.5M17 14.5h3.5" />
    </svg>
  );
}

export function ThermometerIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M10 14.2V5.5a2 2 0 1 1 4 0v8.7a3.6 3.6 0 1 1-4 0Z" />
      <path d="M12 9v7" />
    </svg>
  );
}

export function BoltIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M13.5 3.5 6.5 13h4.5l-.5 7.5 7-9.5H13Z" />
    </svg>
  );
}

export function LabsIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M9 4.5h6M10 4.5v5.2L5.3 18a1.7 1.7 0 0 0 1.5 2.5h10.4a1.7 1.7 0 0 0 1.5-2.5L14 9.7V4.5" />
      <path d="M7.5 15h9M10.3 12.2h.01M13.7 13.7h.01" />
    </svg>
  );
}

export function DownloadIcon({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M12 4v10M8 10.5l4 4 4-4M5 19h14" />
    </svg>
  );
}
