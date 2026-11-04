import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { ApiError, api, setCredentials } from './api';
import type { IndexStats, RagPacket, SearchResult } from './types';
import {
  CloseIcon,
  CommandIcon,
  DeviceIcon,
  FilesIcon,
  LogoMark,
  RefreshIcon,
  SearchIcon,
  SettingsIcon,
  ShieldIcon,
  SparkIcon,
} from './icons';
import AssistantPanel from './components/AssistantPanel';
import CommandPalette, { type PaletteAction } from './components/CommandPalette';
import DevicePanel from './components/DevicePanel';
import LearningPanel from './components/LearningPanel';
import SecurityPanel from './components/SecurityPanel';

type View = 'files' | 'search' | 'device' | 'learning' | 'security' | 'settings';
type AssistantTab = 'chat' | 'ask' | 'agents';
type OpenFile = { path: string; content: string; lines: number };

export default function App() {
  const [credentials, setCredState] = useState({ token: '', totp: '' });
  const [unlocked, setUnlocked] = useState(false);
  const [lockError, setLockError] = useState<string | null>(null);
  const [project, setProject] = useState(
    () => localStorage.getItem('omniforge.project') || 'demo',
  );
  const [projectDraft, setProjectDraft] = useState(project);
  const [view, setView] = useState<View>('files');
  const [assistantTab, setAssistantTab] = useState<AssistantTab>('chat');
  const [files, setFiles] = useState<string[]>([]);
  const [fileFilter, setFileFilter] = useState('');
  const [tabs, setTabs] = useState<OpenFile[]>([]);
  const [activePath, setActivePath] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchRag, setSearchRag] = useState<RagPacket | null>(null);
  const [searching, setSearching] = useState(false);
  const [stats, setStats] = useState<IndexStats | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState('Ready');
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [explorerOpen, setExplorerOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);

  const notify = useCallback((message: string) => setStatus(message), []);

  const lock = useCallback(() => {
    setUnlocked(false);
    setCredState({ token: '', totp: '' });
    setCredentials({ token: '', totp: '' });
    setTabs([]);
    setActivePath(null);
    setFiles([]);
    setStats(null);
    setStatus('Workspace locked');
  }, []);

  const handleError = useCallback((error: unknown) => {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      setCredentials({ token: '', totp: '' });
      setUnlocked(false);
      setLockError(error.message);
      return;
    }
    setStatus(error instanceof Error ? error.message : 'Request failed');
  }, []);

  const openFile = useCallback(
    async (path: string, line?: number) => {
      try {
        const file = await api.readFile(project, path);
        const entry: OpenFile = {
          path,
          content: file.content,
          lines: file.content.split('\n').length,
        };
        setTabs((previous) => [...previous.filter((tab) => tab.path !== path), entry]);
        setActivePath(path);
        setView('files');
        setStatus(line ? `Opened ${path}:${line}` : `Opened ${path}`);
      } catch (error) {
        handleError(error);
      }
    },
    [project, handleError],
  );

  const refreshFiles = useCallback(async () => {
    try {
      const data = await api.files(project);
      setFiles(data.files);
      setStatus(`${data.files.length} files in ${project}`);
    } catch (error) {
      handleError(error);
    }
  }, [project, handleError]);

  const indexProject = useCallback(async () => {
    setBusy('Indexing changed files…');
    try {
      const report = await api.index(project);
      setStats(await api.indexStats(project));
      setStatus(
        `Indexed ${report.embedded_files} changed files · ${report.vectors} vectors in ${report.elapsed_seconds}s`,
      );
    } catch (error) {
      handleError(error);
    } finally {
      setBusy(null);
    }
  }, [project, handleError]);

  const runSearch = useCallback(async () => {
    const query = searchQuery.trim();
    if (!query) return;
    setSearching(true);
    try {
      const data = await api.search(project, query);
      setSearchResults(data.results);
      setSearchRag(data.rag ?? null);
      setView('search');
      setStatus(
        `${data.results.length} matches for “${query}”` +
          (data.retrieval?.learned_rerank ? ' · learned rerank' : ''),
      );
    } catch (error) {
      handleError(error);
    } finally {
      setSearching(false);
    }
  }, [project, searchQuery, handleError]);

  useEffect(() => {
    if (!unlocked) return;
    let cancelled = false;
    setTabs([]);
    setActivePath(null);
    setSearchResults([]);
    setSearchRag(null);
    (async () => {
      try {
        const [fileData, indexStats] = await Promise.all([
          api.files(project),
          api.indexStats(project),
        ]);
        if (cancelled) return;
        setFiles(fileData.files);
        setStats(indexStats);
        if (fileData.files.length > 0) void openFile(fileData.files[0]);
      } catch (error) {
        if (!cancelled) handleError(error);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [unlocked, project, openFile, handleError]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPaletteOpen(true);
      }
      if (event.key === 'Escape') setPaletteOpen(false);
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  async function handleUnlock(next: { token: string; totp: string; project: string }) {
    setCredentials(next);
    setCredState({ token: next.token, totp: next.totp });
    setProject(next.project);
    setProjectDraft(next.project);
    localStorage.setItem('omniforge.project', next.project);
    setLockError(null);
    try {
      await api.security();
      setUnlocked(true);
      setStatus(`Unlocked ${next.project}`);
    } catch (error) {
      setLockError(error instanceof Error ? error.message : 'Authentication failed');
    }
  }

  const actions = useMemo<PaletteAction[]>(
    () => [
      { id: 'index', label: 'Index project', hint: 'Embed changed files', run: () => void indexProject() },
      { id: 'refresh', label: 'Refresh files', hint: 'Reload the explorer', run: () => void refreshFiles() },
      {
        id: 'ask',
        label: 'Ask the codebase',
        hint: 'Assistant · ask',
        run: () => {
          setRightOpen(true);
          setAssistantTab('ask');
        },
      },
      {
        id: 'agents',
        label: 'New multi-agent run',
        hint: 'Assistant · agents',
        run: () => {
          setRightOpen(true);
          setAssistantTab('agents');
        },
      },
      { id: 'search', label: 'Search code', hint: 'Hybrid retrieval', run: () => setView('search') },
      {
        id: 'device',
        label: 'Device runtime',
        hint: 'GPU, thermals, keep-awake',
        run: () => setView('device'),
      },
      {
        id: 'learning',
        label: 'Continuous learning',
        hint: 'Learned retrieval and feedback',
        run: () => setView('learning'),
      },
      { id: 'security', label: 'Security posture', hint: 'Auth, lockouts, audit', run: () => setView('security') },
      { id: 'settings', label: 'Settings', hint: 'Credentials and project', run: () => setView('settings') },
      { id: 'lock', label: 'Lock workspace', hint: 'Clear credentials', run: lock },
    ],
    [indexProject, refreshFiles, lock],
  );

  const activeFile = tabs.find((tab) => tab.path === activePath) ?? null;

  const filteredFiles = useMemo(() => {
    const needle = fileFilter.trim().toLowerCase();
    const list = needle ? files.filter((file) => file.toLowerCase().includes(needle)) : files;
    return list.slice(0, 500);
  }, [files, fileFilter]);

  function closeTab(path: string) {
    const next = tabs.filter((tab) => tab.path !== path);
    setTabs(next);
    if (activePath === path) {
      setActivePath(next.length > 0 ? next[next.length - 1].path : null);
    }
  }

  if (!unlocked) {
    return <LockScreen initialProject={project} error={lockError} onUnlock={handleUnlock} />;
  }

  return (
    <div className="shell">
      <header className="titlebar">
        <div className="brand" title="Aetherion OmniForge">
          <LogoMark size={22} />
          <span className="brand-name">
            Aetherion <strong>OmniForge</strong>
          </span>
          <span className="version">AI</span>
        </div>

        <form
          className="project-form"
          onSubmit={(event) => {
            event.preventDefault();
            const next = projectDraft.trim();
            if (!/^[A-Za-z0-9_-]{1,64}$/.test(next)) {
              notify('Project names use letters, numbers, dashes or underscores.');
              return;
            }
            setProject(next);
            localStorage.setItem('omniforge.project', next);
          }}
        >
          <span className="crumb">project</span>
          <input
            value={projectDraft}
            onChange={(event) => setProjectDraft(event.target.value)}
            maxLength={64}
            aria-label="Project name"
          />
          <button className="ghost" type="submit">
            Open
          </button>
        </form>

        <div className="title-actions">
          <button className="ghost" onClick={() => setPaletteOpen(true)} title="Command palette">
            <CommandIcon size={14} /> <kbd>Ctrl K</kbd>
          </button>
          <button className="ghost" onClick={() => void indexProject()} disabled={busy !== null}>
            <SparkIcon size={14} /> Index
          </button>
          <button
            className="ghost"
            onClick={() => setExplorerOpen((open) => !open)}
            aria-pressed={explorerOpen}
            title="Toggle explorer"
          >
            Explorer
          </button>
          <button
            className="ghost"
            onClick={() => setRightOpen((open) => !open)}
            aria-pressed={rightOpen}
            title="Toggle assistant"
          >
            Assistant
          </button>
          <button className="ghost" onClick={lock} title="Lock workspace">
            <ShieldIcon size={14} /> Lock
          </button>
        </div>
      </header>

      <div
        className={`workspace ${explorerOpen ? '' : 'explorer-hidden'} ${
          rightOpen ? '' : 'assistant-hidden'
        }`}
      >
        <nav className="rail" aria-label="Primary navigation">
          <RailButton active={view === 'files'} label="Explorer" onClick={() => setView('files')}>
            <FilesIcon size={18} />
          </RailButton>
          <RailButton active={view === 'search'} label="Search" onClick={() => setView('search')}>
            <SearchIcon size={18} />
          </RailButton>
          <RailButton
            active={view === 'device'}
            label="Device runtime"
            onClick={() => setView('device')}
          >
            <DeviceIcon size={18} />
          </RailButton>
          <RailButton
            active={view === 'learning'}
            label="Continuous learning"
            onClick={() => setView('learning')}
          >
            <SparkIcon size={18} />
          </RailButton>
          <RailButton
            active={view === 'security'}
            label="Security"
            onClick={() => setView('security')}
          >
            <ShieldIcon size={18} />
          </RailButton>
          <span className="rail-spacer" />
          <RailButton
            active={view === 'settings'}
            label="Settings"
            onClick={() => setView('settings')}
          >
            <SettingsIcon size={18} />
          </RailButton>
        </nav>

        {explorerOpen && (
          <aside className="explorer" aria-label="Explorer">
            <div className="explorer-head">
              <span>
                {view === 'files'
                  ? 'Explorer'
                  : view === 'search'
                    ? 'Search'
                    : view === 'device'
                      ? 'Device'
                      : view === 'learning'
                        ? 'Learning'
                        : view === 'security'
                        ? 'Security'
                        : 'Settings'}
              </span>
              <button className="ghost icon" onClick={() => void refreshFiles()} title="Refresh files">
                <RefreshIcon size={14} />
              </button>
            </div>

            {view === 'files' && (
              <>
                <div className="filter">
                  <SearchIcon size={14} />
                  <input
                    value={fileFilter}
                    onChange={(event) => setFileFilter(event.target.value)}
                    placeholder="Filter files"
                    aria-label="Filter project files"
                  />
                </div>
                <div className="file-list">
                  {filteredFiles.map((file) => (
                    <button
                      key={file}
                      className={`file ${activePath === file ? 'active' : ''}`}
                      onClick={() => void openFile(file)}
                      title={file}
                    >
                      {file}
                    </button>
                  ))}
                  {filteredFiles.length === 0 && <p className="muted small">No files match.</p>}
                </div>
                <div className="explorer-foot">
                  <button className="ghost" onClick={() => void indexProject()} disabled={busy !== null}>
                    <SparkIcon size={14} /> Index project
                  </button>
                  <span className="muted small">
                    {stats ? `${stats.vectors} vectors · ${stats.dimensions}d` : 'not indexed'}
                  </span>
                </div>
              </>
            )}

            {view === 'search' && (
              <div className="search-pane">
                <div className="filter">
                  <SearchIcon size={14} />
                  <input
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') void runSearch();
                    }}
                    placeholder="Describe the code you need"
                    aria-label="Search code"
                  />
                </div>
                <button className="primary wide" onClick={() => void runSearch()} disabled={searching}>
                  {searching ? 'Searching…' : 'Search'}
                </button>
                <div className="search-results">
                  {searchResults.map((result) => (
                    <button
                      key={`${result.path}:${result.line}`}
                      className="result"
                      onClick={() => void openFile(result.path, result.line)}
                    >
                      <span className="result-path">
                        {result.path}:{result.line}
                      </span>
                      <span className="result-excerpt">{result.excerpt}</span>
                      <span className="run-meta">
                        {result.sources.join(' + ')}
                        {typeof result.learned_boost === 'number' && result.learned_boost !== 0
                          ? ` · learned ${result.learned_boost > 0 ? '+' : ''}${result.learned_boost}`
                          : ''}
                      </span>
                    </button>
                  ))}
                  {searchResults.length === 0 && (
                    <p className="muted small">
                      Hybrid vector and keyword search across the indexed project.
                    </p>
                  )}
                  {searchRag && searchRag.citations.length > 0 && (
                    <div className="rag-packet">
                      <span className="rag-title">RAG packet</span>
                      <p className="muted small">
                        {searchRag.results} excerpts · {searchRag.used_chars} chars ·{' '}
                        {searchRag.safety.risk} risk
                      </p>
                      {searchRag.citations.slice(0, 6).map((citation) => (
                        <button
                          key={`${citation.path}:${citation.line}`}
                          className="link"
                          onClick={() => void openFile(citation.path, citation.line)}
                        >
                          {citation.path}:{citation.line}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {view === 'device' && (
              <p className="muted small">
                Hardware, temperatures and the keep-awake hold are shown in the main panel. Agent
                steps pause automatically when the device runs hot.
              </p>
            )}

            {view === 'security' && (
              <p className="muted small">
                Lockouts, rate limits and the audit trail are shown in the main panel. The token is
                held in memory for this tab only.
              </p>
            )}

            {view === 'settings' && (
              <p className="muted small">
                Update the administrator token, optional TOTP code and project in the main panel.
              </p>
            )}
          </aside>
        )}

        <main className="center">
          {view === 'device' ? (
            <DevicePanel notify={notify} onLocked={lock} />
          ) : view === 'learning' ? (
            <LearningPanel project={project} notify={notify} onLocked={lock} />
          ) : view === 'security' ? (
            <SecurityPanel notify={notify} onLocked={lock} />
          ) : view === 'settings' ? (
            <SettingsView
              credentials={credentials}
              project={project}
              stats={stats}
              onSave={handleUnlock}
              onIndex={() => void indexProject()}
            />
          ) : activeFile ? (
            <>
              <div className="tabs" role="tablist" aria-label="Open files">
                {tabs.map((tab) => (
                  <div key={tab.path} className={`tab ${tab.path === activePath ? 'active' : ''}`}>
                    <button
                      role="tab"
                      aria-selected={tab.path === activePath}
                      onClick={() => setActivePath(tab.path)}
                      title={tab.path}
                    >
                      {tab.path.split('/').pop()}
                    </button>
                    <button
                      className="tab-close"
                      aria-label={`Close ${tab.path}`}
                      onClick={() => closeTab(tab.path)}
                    >
                      <CloseIcon size={12} />
                    </button>
                  </div>
                ))}
              </div>
              <CodeView file={activeFile} />
            </>
          ) : (
            <WelcomeView
              project={project}
              stats={stats}
              fileCount={files.length}
              onIndex={() => void indexProject()}
              onAsk={() => {
                setRightOpen(true);
                setAssistantTab('ask');
              }}
              onSearch={() => setView('search')}
            />
          )}
        </main>

        {rightOpen && (
          <AssistantPanel
            project={project}
            tab={assistantTab}
            onTab={setAssistantTab}
            onOpenFile={(path, line) => void openFile(path, line)}
            onLocked={lock}
            notify={notify}
          />
        )}
      </div>

      <footer className="statusbar">
        <span className={`status-dot ${busy ? 'busy' : 'ok'}`} />
        <span className="status-text">{busy ?? status}</span>
        <span className="spacer" />
        <span>{project}</span>
        <span>{files.length} files</span>
        {stats && (
          <span>
            {stats.vectors} vectors · {stats.dimensions}d · {stats.backend}
          </span>
        )}
        {stats?.feedback && (
          <span>
            👍 {stats.feedback.positive} · 👎 {stats.feedback.negative}
          </span>
        )}
        <span className="pill ok">authenticated</span>
      </footer>

      <CommandPalette
        open={paletteOpen}
        actions={actions}
        files={files}
        onClose={() => setPaletteOpen(false)}
        onOpenFile={(path) => void openFile(path)}
      />
    </div>
  );
}

function RailButton({
  active,
  label,
  onClick,
  children,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      className={`rail-button ${active ? 'active' : ''}`}
      onClick={onClick}
      aria-label={label}
      aria-pressed={active}
      title={label}
    >
      {children}
    </button>
  );
}

function CodeView({ file }: { file: OpenFile }) {
  const lines = useMemo(() => file.content.split('\n'), [file.content]);
  const shown = lines.length > 4000 ? lines.slice(0, 4000) : lines;
  return (
    <div className="editor">
      <div className="editor-meta">
        <span className="mono">{file.path}</span>
        <span className="muted">
          {file.lines} lines · read-only
          <a className="link" href="/studio" target="_blank" rel="noreferrer">
            Edit in Studio ↗
          </a>
        </span>
      </div>
      <div className="code-scroll">
        <div className="code-lines">
          <div className="gutter" aria-hidden="true">
            {shown.map((_, index) => (
              <span key={index}>{index + 1}</span>
            ))}
          </div>
          <pre className="code">{shown.join('\n')}</pre>
        </div>
      </div>
      {lines.length > 4000 && (
        <p className="truncated">Preview limited to the first 4,000 lines. Open in Studio for the rest.</p>
      )}
    </div>
  );
}

function WelcomeView({
  project,
  stats,
  fileCount,
  onIndex,
  onAsk,
  onSearch,
}: {
  project: string;
  stats: IndexStats | null;
  fileCount: number;
  onIndex: () => void;
  onAsk: () => void;
  onSearch: () => void;
}) {
  return (
    <div className="welcome">
      <LogoMark size={40} />
      <h1>
        Aetherion <strong>OmniForge</strong>
      </h1>
      <p className="muted">
        A local-first agent workspace. Pick a file, ask a question, or start a bounded multi-agent
        run. Nothing here writes or executes without your approval.
      </p>
      <div className="welcome-grid">
        <article className="welcome-card">
          <h2>Project</h2>
          <p className="mono">{project}</p>
          <p className="muted small">{fileCount} files indexed in the explorer</p>
          <button className="ghost" onClick={onIndex}>
            <SparkIcon size={14} /> Index project
          </button>
        </article>
        <article className="welcome-card">
          <h2>Retrieval</h2>
          <p>{stats ? `${stats.vectors} vectors · ${stats.indexed_files} files` : 'Not indexed yet'}</p>
          <p className="muted small">{stats?.model ?? 'local hashed embeddings'}</p>
          <button className="ghost" onClick={onSearch}>
            <SearchIcon size={14} /> Search code
          </button>
        </article>
        <article className="welcome-card">
          <h2>Assistant</h2>
          <p>Grounded answers with citations and secret redaction.</p>
          <p className="muted small">Multi-agent runs are bounded and human-advanced.</p>
          <button className="ghost" onClick={onAsk}>
            <CommandIcon size={14} /> Ask the codebase
          </button>
        </article>
      </div>
      <p className="muted small">
        Shortcuts: <kbd>Ctrl</kbd>+<kbd>K</kbd> command palette · <kbd>Esc</kbd> closes it.
      </p>
    </div>
  );
}

function SettingsView({
  credentials,
  project,
  stats,
  onSave,
  onIndex,
}: {
  credentials: { token: string; totp: string };
  project: string;
  stats: IndexStats | null;
  onSave: (next: { token: string; totp: string; project: string }) => Promise<void>;
  onIndex: () => void;
}) {
  const [token, setToken] = useState(credentials.token);
  const [totp, setTotp] = useState(credentials.totp);
  const [draftProject, setDraftProject] = useState(project);
  const [message, setMessage] = useState<string | null>(null);

  return (
    <div className="page settings">
      <div className="page-head">
        <div>
          <h1>
            <SettingsIcon size={18} /> Settings
          </h1>
          <p className="muted">Credentials live in this tab's memory only. They are never written to storage.</p>
        </div>
      </div>
      <form
        className="settings-form"
        onSubmit={async (event) => {
          event.preventDefault();
          await onSave({ token, totp, project: draftProject });
          setMessage('Credentials updated for this tab.');
        }}
      >
        <label className="field">
          <span>Administrator token</span>
          <input
            type="password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            placeholder="AGENT_ADMIN_TOKEN"
            autoComplete="off"
          />
        </label>
        <label className="field">
          <span>Optional TOTP code</span>
          <input
            value={totp}
            onChange={(event) => setTotp(event.target.value)}
            inputMode="numeric"
            maxLength={6}
            placeholder="6-digit code if enabled"
            autoComplete="one-time-code"
          />
        </label>
        <label className="field">
          <span>Project</span>
          <input
            value={draftProject}
            onChange={(event) => setDraftProject(event.target.value)}
            maxLength={64}
          />
        </label>
        <button className="primary" type="submit">
          Save credentials
        </button>
        {message && <p className="muted small">{message}</p>}
      </form>
      <div className="settings-links">
        <a className="link" href="/studio" target="_blank" rel="noreferrer">
          Open Code Studio ↗
        </a>
        <a className="link" href="/" target="_blank" rel="noreferrer">
          Open classic chat ↗
        </a>
      </div>
      <div className="settings-stats">
        <h2 className="section-title">Retrieval index</h2>
        {stats ? (
          <p className="muted">
            {stats.indexed_files} files · {stats.vectors} vectors · {stats.dimensions} dimensions ·{' '}
            {stats.backend} · feedback {stats.feedback?.positive ?? 0}↑/{stats.feedback?.negative ?? 0}↓
          </p>
        ) : (
          <p className="muted">No index metadata available.</p>
        )}
        <button className="ghost" onClick={onIndex}>
          <SparkIcon size={14} /> Reindex now
        </button>
      </div>
    </div>
  );
}

function LockScreen({
  initialProject,
  error,
  onUnlock,
}: {
  initialProject: string;
  error: string | null;
  onUnlock: (next: { token: string; totp: string; project: string }) => Promise<void>;
}) {
  const [token, setToken] = useState('');
  const [totp, setTotp] = useState('');
  const [project, setProject] = useState(initialProject);
  const [busy, setBusy] = useState(false);

  return (
    <div className="lock">
      <form
        className="lock-card"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!token.trim()) return;
          setBusy(true);
          await onUnlock({ token, totp, project });
          setBusy(false);
        }}
      >
        <div className="lock-brand">
          <LogoMark size={34} />
          <h1>
            Aetherion <strong>OmniForge</strong>
          </h1>
          <p className="muted">Local-first multi-agent engineering workspace</p>
        </div>
        <label className="field">
          <span>Administrator token</span>
          <input
            type="password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            placeholder="AGENT_ADMIN_TOKEN"
            autoFocus
          />
        </label>
        <label className="field">
          <span>Optional TOTP code</span>
          <input
            value={totp}
            onChange={(event) => setTotp(event.target.value)}
            inputMode="numeric"
            maxLength={6}
            placeholder="6-digit code if enabled"
            autoComplete="one-time-code"
          />
        </label>
        <label className="field">
          <span>Project</span>
          <input
            value={project}
            onChange={(event) => setProject(event.target.value)}
            maxLength={64}
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="primary wide" type="submit" disabled={busy}>
          {busy ? 'Unlocking…' : 'Unlock workspace'}
        </button>
        <p className="muted small">
          The token stays in page memory. Configure it with <code>AGENT_ADMIN_TOKEN</code> on the
          local service. TOTP is required when <code>AGENT_TOTP_SECRET</code> is set.
        </p>
      </form>
    </div>
  );
}
