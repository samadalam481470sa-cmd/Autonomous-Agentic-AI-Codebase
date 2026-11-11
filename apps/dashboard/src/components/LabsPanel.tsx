import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from '../api';
import type { DiagramResponse, GithubSearchResult, GithubSource } from '../types';
import { DownloadIcon, LabsIcon, RefreshIcon, SearchIcon, SparkIcon } from '../icons';

type Tab = 'github' | 'diagram';

interface Props {
  project: string;
  notify: (message: string) => void;
  onLocked: () => void;
  onOpenProject: (project: string) => void;
}

function humanBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export default function LabsPanel({ project, notify, onLocked, onOpenProject }: Props) {
  const [tab, setTab] = useState<Tab>('github');
  const [sources, setSources] = useState<GithubSource[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [repo, setRepo] = useState('');
  const [branch, setBranch] = useState('');
  const [query, setQuery] = useState('');
  const [matches, setMatches] = useState<GithubSearchResult[]>([]);
  const [diagram, setDiagram] = useState<DiagramResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fail = useCallback(
    (problem: unknown) => {
      if (problem instanceof ApiError && (problem.status === 401 || problem.status === 403)) {
        onLocked();
        return;
      }
      setError(problem instanceof Error ? problem.message : 'Labs request failed');
    },
    [onLocked],
  );

  const loadSources = useCallback(async () => {
    try {
      const data = await api.githubSources();
      setSources(data.sources);
      setEnabled(data.enabled);
    } catch (problem) {
      fail(problem);
    }
  }, [fail]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  async function learn() {
    const value = repo.trim();
    if (value.length < 3) {
      setError('Enter a public GitHub repository as owner/name.');
      return;
    }
    setBusy('Downloading repository…');
    setError(null);
    try {
      const result = await api.learnGithub(value, branch.trim() || undefined);
      setRepo('');
      setBranch('');
      setSources((previous) => [result.source, ...previous]);
      setEnabled(true);
      notify(
        `Learned ${result.source.repo} · ${result.source.files} files · ${result.index.vectors ?? 0} vectors`,
      );
      onOpenProject(result.source.project);
    } catch (problem) {
      fail(problem);
    } finally {
      setBusy(null);
    }
  }

  async function searchLearned() {
    if (!query.trim()) return;
    setBusy('Searching learned repositories…');
    setError(null);
    try {
      const data = await api.githubSearch(query.trim());
      setMatches(data.results);
      notify(`${data.results.length} learned-repository matches`);
    } catch (problem) {
      fail(problem);
    } finally {
      setBusy(null);
    }
  }

  async function buildDiagram() {
    setBusy('Tracing imports and rendering…');
    setError(null);
    try {
      const data = await api.diagram(project);
      setDiagram(data);
      notify(`Diagram: ${data.stats.files_shown} files · ${data.stats.edges} links`);
    } catch (problem) {
      fail(problem);
    } finally {
      setBusy(null);
    }
  }

  function download(format: 'svg' | 'mermaid') {
    if (!diagram) return;
    const value = format === 'svg' ? diagram.svg : diagram.mermaid;
    const type = format === 'svg' ? 'image/svg+xml' : 'text/plain';
    const extension = format === 'svg' ? 'svg' : 'mmd';
    const url = URL.createObjectURL(new Blob([value], { type }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${project}-architecture.${extension}`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const svgSrc = diagram
    ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(diagram.svg)}`
    : null;

  return (
    <div className="page labs-page">
      <div className="page-head">
        <div>
          <h1>
            <LabsIcon size={18} /> Labs
          </h1>
          <p className="muted">
            Import public repositories into the local retrieval index, trace project
            architecture, and launch bounded autonomous agent loops.
          </p>
        </div>
        <div className="labs-tabs" role="tablist" aria-label="Labs views">
          <button
            role="tab"
            aria-selected={tab === 'github'}
            className={tab === 'github' ? 'active' : ''}
            onClick={() => setTab('github')}
          >
            GitHub learning
          </button>
          <button
            role="tab"
            aria-selected={tab === 'diagram'}
            className={tab === 'diagram' ? 'active' : ''}
            onClick={() => setTab('diagram')}
          >
            Diagrams
          </button>
        </div>
      </div>

      {error && <p className="error labs-error">{error}</p>}
      {busy && <p className="muted small">{busy}</p>}

      {tab === 'github' ? (
        <div className="lab-grid">
          <section className="lab-card">
            <h2>
              <SparkIcon size={14} /> Learn a public repository
            </h2>
            <p className="muted small">
              Downloads source from GitHub, keeps repository/branch/commit/license
              metadata, and indexes it locally. It never uploads project code or
              model weights. {enabled ? 'Enabled' : 'Disabled'}.
            </p>
            {!enabled && (
              <p className="labs-note">
                Set <code>GITHUB_LEARNING=1</code> on the API process to enable
                public-repository downloads.
              </p>
            )}
            <form
              className="lab-form"
              onSubmit={(event) => {
                event.preventDefault();
                void learn();
              }}
            >
              <label className="field">
                <span>Repository</span>
                <input
                  value={repo}
                  onChange={(event) => setRepo(event.target.value)}
                  placeholder="owner/repository or GitHub URL"
                  maxLength={180}
                />
              </label>
              <label className="field">
                <span>Branch (optional)</span>
                <input
                  value={branch}
                  onChange={(event) => setBranch(event.target.value)}
                  placeholder="main"
                  maxLength={100}
                />
              </label>
              <button className="primary" type="submit" disabled={busy !== null || !enabled}>
                <DownloadIcon size={14} /> Learn repository
              </button>
            </form>
            <p className="muted small">
              Only source and documentation suffixes are stored. Symlinks, archives
              outside the size limits, and path traversal are rejected.
            </p>
          </section>

          <section className="lab-card">
            <div className="lab-card-head">
              <h2>
                <SearchIcon size={14} /> Search learned repositories
              </h2>
              <button className="ghost icon" onClick={() => void loadSources()} title="Refresh learned sources">
                <RefreshIcon size={14} />
              </button>
            </div>
            <form
              className="lab-form lab-search-form"
              onSubmit={(event) => {
                event.preventDefault();
                void searchLearned();
              }}
            >
              <label className="field">
                <span>Query</span>
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Find a pattern across learned projects"
                  maxLength={200}
                />
              </label>
              <button className="ghost" type="submit" disabled={busy !== null || !enabled}>
                Search learned
              </button>
            </form>
            <div className="learned-results">
              {matches.map((match) => (
                <button
                  key={`${match.project}:${match.path}:${match.line}`}
                  className="result"
                  onClick={() => onOpenProject(match.project)}
                >
                  <span className="result-path">
                    {match.repo} · {match.path}:{match.line}
                  </span>
                  <span className="result-excerpt">{match.excerpt}</span>
                  <span className="run-meta">
                    {match.sources.join(' + ')} · {match.license}
                  </span>
                </button>
              ))}
              {matches.length === 0 && (
                <p className="muted small">
                  Learned-repository search uses the same local hybrid index as the
                  current project.
                </p>
              )}
            </div>
          </section>

          <section className="lab-card lab-wide">
            <div className="lab-card-head">
              <h2>
                <LabsIcon size={14} /> Learned sources
              </h2>
              <span className="pill">{sources.length} sources</span>
            </div>
            <div className="source-list">
              {sources.map((source) => (
                <article className="source-item" key={source.id}>
                  <div>
                    <strong>{source.repo}</strong>
                    <span className="run-meta">
                      {source.branch} · {source.commit.slice(0, 10)} · {source.license} ·{' '}
                      {source.files} files · {humanBytes(source.bytes)}
                    </span>
                  </div>
                  <div className="source-actions">
                    <button className="ghost" onClick={() => onOpenProject(source.project)}>
                      Open project
                    </button>
                    <a className="link" href={source.url} target="_blank" rel="noreferrer">
                      GitHub ↗
                    </a>
                  </div>
                </article>
              ))}
              {sources.length === 0 && (
                <p className="muted small">No repositories learned yet.</p>
              )}
            </div>
          </section>
        </div>
      ) : (
        <div className="lab-grid">
          <section className="lab-card lab-wide">
            <div className="lab-card-head">
              <h2>
                <LabsIcon size={14} /> {project} architecture
              </h2>
              <div className="run-actions">
                <button className="primary" onClick={() => void buildDiagram()} disabled={busy !== null}>
                  <SparkIcon size={14} /> Generate diagram
                </button>
                {diagram && (
                  <>
                    <button className="ghost" onClick={() => download('svg')}>
                      <DownloadIcon size={14} /> SVG
                    </button>
                    <button className="ghost" onClick={() => download('mermaid')}>
                      Mermaid
                    </button>
                  </>
                )}
              </div>
            </div>
            <p className="muted small">
              Resolves local Python, JavaScript/TypeScript, Rust, Java and Kotlin
              imports into a focused architecture map. Third-party imports are
              omitted; no Graphviz or network renderer is required.
            </p>
            {svgSrc ? (
              <>
                <div className="diagram-frame">
                  <img src={svgSrc} alt={`Architecture diagram for ${project}`} />
                </div>
                <div className="diagram-stats">
                  <span>{diagram?.stats.files_shown} files shown</span>
                  <span>{diagram?.stats.files_scanned} scanned</span>
                  <span>{diagram?.stats.edges} resolved links</span>
                  {diagram?.stats.truncated && <span className="pill">focused view</span>}
                </div>
                <details className="mermaid-source">
                  <summary>Mermaid source</summary>
                  <pre className="step-output">{diagram?.mermaid}</pre>
                </details>
              </>
            ) : (
              <div className="diagram-empty">
                <LabsIcon size={32} />
                <p className="muted">Generate a map of this project’s local import graph.</p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
