"""Deterministic repository diagrams without a renderer dependency.

The diagram is built from source files that are already safe to read through the
bounded code indexer. Imports are resolved only inside the selected project;
third-party imports are ignored. The result is a Mermaid flowchart plus a
standalone, escaped SVG suitable for the dashboard or a downloaded artifact.

No model, browser, Graphviz installation or network access is required.
"""
from __future__ import annotations

import html
import math
import posixpath
import re
from collections import Counter, defaultdict
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import code_index
from .engine import workspace
from .studio import authorize

router = APIRouter(prefix="/api/diagrams", tags=["diagrams"])

MAX_FILES = 800
MAX_NODES = 80
MAX_TEXT_BYTES = 200_000
COLORS = {
    "python": "#7c9cff",
    "typescript": "#63d9ff",
    "javascript": "#f2c14e",
    "rust": "#ff9b70",
    "go": "#4fd1a1",
    "java": "#c9a7ff",
    "csharp": "#9db4ff",
    "cpp": "#f28fad",
    "c": "#f28fad",
    "ruby": "#ff7c7c",
    "php": "#a8b9ff",
    "sql": "#d4b483",
    "html": "#ffb86b",
    "css": "#74c7ec",
    "shell": "#8bd5a8",
}
LANGUAGES = {
    ".py": "python",
    ".pyw": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "java",
    ".kts": "java",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".rb": "ruby",
    ".php": "php",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".sh": "shell",
    ".bash": "shell",
}
PY_IMPORT = re.compile(
    r"^\s*(?:from\s+([.\w]+)\s+import|import\s+([.\w]+))", re.MULTILINE
)
JS_IMPORT = re.compile(
    r"""(?:\bfrom\s*|\brequire\s*\(\s*)["']([^"']+)["']"""
)
RUST_IMPORT = re.compile(r"^\s*use\s+((?:crate|super|self)::[\w:{}*, ]+)", re.MULTILINE)
JAVA_IMPORT = re.compile(r"^\s*import\s+([\w.]+)\s*;", re.MULTILINE)


class DiagramRequest(BaseModel):
    project: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    max_nodes: int = Field(default=60, ge=1, le=MAX_NODES)
    max_files: int = Field(default=MAX_FILES, ge=1, le=MAX_FILES)


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return None
        data = path.read_bytes()
        if b"\x00" in data:
            return None
        return data.decode("utf-8")
    except (OSError, UnicodeError):
        return None


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _mermaid(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', "'").replace("\n", " ")


def _python_module_map(paths: set[str]) -> dict[str, str]:
    modules: dict[str, str] = {}
    for relative in paths:
        if not relative.endswith(".py"):
            continue
        parts = list(Path(relative).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            modules[".".join(parts)] = relative
    return modules


def _resolve_python(current: str, raw: str, modules: dict[str, str]) -> str | None:
    value = (raw or "").strip()
    if not value:
        return None
    dots = len(value) - len(value.lstrip("."))
    rest = value.lstrip(".")
    if dots:
        base = Path(current).parent
        for _ in range(max(0, dots - 1)):
            base = base.parent
        parts = [item for item in rest.split(".") if item]
        candidate = base.joinpath(*parts)
        for option in (candidate.with_suffix(".py"), candidate / "__init__.py"):
            text = option.as_posix()
            if text in modules.values():
                return text
    return modules.get(rest)


def _resolve_js(current: str, raw: str, paths: set[str]) -> str | None:
    value = (raw or "").strip()
    if value.startswith("@/"):
        base = ""
        value = value[2:]
    elif value.startswith("."):
        base = posixpath.dirname(current)
    else:
        return None
    candidate = posixpath.normpath(posixpath.join(base, value))
    if candidate.startswith("../") or candidate == "..":
        return None
    options = [candidate]
    for suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        options.append(candidate + suffix)
    for suffix in (".ts", ".tsx", ".js", ".jsx"):
        options.append(posixpath.join(candidate, "index" + suffix))
    for option in options:
        if option in paths:
            return option
    return None


def _resolve_rust(current: str, raw: str, paths: set[str]) -> str | None:
    value = (raw or "").strip()
    value = value.split("{", 1)[0].strip().rstrip(",; ")
    value = value.replace("crate::", "").replace("super::", "").replace("self::", "")
    parts = [item for item in value.split("::") if item]
    if not parts:
        return None
    base = Path(current).parent
    candidates = [
        base.joinpath(*parts).with_suffix(".rs"),
        base.joinpath(*parts) / "mod.rs",
        Path("src").joinpath(*parts).with_suffix(".rs"),
        Path("src").joinpath(*parts) / "mod.rs",
    ]
    for candidate in candidates:
        text = candidate.as_posix()
        if text in paths:
            return text
    return None


def _references(relative: str, text: str, paths: set[str],
                modules: dict[str, str]) -> set[str]:
    suffix = Path(relative).suffix.lower()
    result: set[str] = set()
    if suffix == ".py":
        for match in PY_IMPORT.finditer(text):
            raw = match.group(1) or match.group(2)
            target = _resolve_python(relative, raw, modules)
            if target and target != relative:
                result.add(target)
    elif suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
        for match in JS_IMPORT.finditer(text):
            target = _resolve_js(relative, match.group(1), paths)
            if target and target != relative:
                result.add(target)
    elif suffix == ".rs":
        for match in RUST_IMPORT.finditer(text):
            target = _resolve_rust(relative, match.group(1), paths)
            if target and target != relative:
                result.add(target)
    elif suffix in {".java", ".kt", ".kts"}:
        for match in JAVA_IMPORT.finditer(text):
            dotted = match.group(1)
            candidate = Path(*dotted.split(".")).with_suffix(".java").as_posix()
            if candidate in paths and candidate != relative:
                result.add(candidate)
    return result


def _human_label(path: str, limit: int = 30) -> str:
    return path if len(path) <= limit else "…" + path[-(limit - 1):]


def _svg(nodes: list[dict], edges: list[dict], project: str) -> str:
    if not nodes:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 180" '
            'role="img" aria-label="No diagram nodes">'
            '<rect width="760" height="180" rx="18" fill="#0b1018"/>'
            '<text x="380" y="92" text-anchor="middle" fill="#8b95a5" '
            'font-family="ui-sans-serif,system-ui,sans-serif" font-size="15">'
            "No supported source files found in this project.</text></svg>"
        )
    columns = min(5, max(1, int(math.ceil(math.sqrt(len(nodes))))))
    width = columns * 224 + 64
    rows = math.ceil(len(nodes) / columns)
    height = 154 + rows * 108
    positions: dict[str, tuple[float, float]] = {}
    for index, node in enumerate(nodes):
        row, column = divmod(index, columns)
        positions[node["path"]] = (32 + column * 224, 116 + row * 108)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="Architecture diagram for {_escape(project)}">',
        "<defs>",
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0" stop-color="#0a0e15"/><stop offset="1" stop-color="#101a2c"/>',
        "</linearGradient>",
        '<radialGradient id="halo" cx="50%" cy="0%" r="80%">',
        '<stop offset="0" stop-color="#7c9cff" stop-opacity=".20"/>',
        '<stop offset="1" stop-color="#7c9cff" stop-opacity="0"/>',
        "</radialGradient>",
        '<filter id="glow" x="-40%" y="-40%" width="180%" height="180%">',
        '<feGaussianBlur stdDeviation="5" result="blur"/>',
        '<feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>',
        "</filter>",
        '<marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">',
        '<path d="M0,0 L8,4 L0,8 z" fill="#5c719b"/></marker>',
        "</defs>",
        f'<rect width="100%" height="100%" fill="url(#bg)"/>',
        f'<rect width="100%" height="100%" fill="url(#halo)"/>',
        f'<text x="32" y="38" fill="#e6e9ef" font-family="ui-sans-serif,system-ui,sans-serif" '
        f'font-size="18" font-weight="600">{_escape(project)} <tspan fill="#7c9cff">/ architecture</tspan></text>',
        f'<text x="32" y="60" fill="#8b95a5" font-family="ui-monospace,monospace" '
        f'font-size="11">{len(nodes)} files · {len(edges)} resolved links · local import graph</text>',
    ]
    for edge in edges:
        source = positions.get(edge["source"])
        target = positions.get(edge["target"])
        if not source or not target:
            continue
        x1, y1 = source[0] + 92, source[1] + 52
        x2, y2 = target[0] + 92, target[1]
        if abs(x1 - x2) < 4:
            path = f"M{x1},{y1} C{x1 + 34},{y1 + 22} {x2 + 34},{y2 - 24} {x2},{y2}"
        else:
            path = f"M{x1},{y1} C{x1},{y1 + 34} {x2},{y2 - 34} {x2},{y2}"
        parts.append(
            f'<path d="{path}" fill="none" stroke="#3d4f70" stroke-width="1.15" '
            f'stroke-opacity=".7" marker-end="url(#arrow)"/>'
        )
    for node in nodes:
        x, y = positions[node["path"]]
        color = COLORS.get(node["language"], "#7c9cff")
        label = _escape(_human_label(node["path"]))
        group = _escape(node["group"])
        parts.extend([
            f'<g transform="translate({x},{y})">',
            f'<title>{_escape(node["path"])}</title>',
            f'<rect width="184" height="52" rx="10" fill="{color}" fill-opacity=".10" '
            f'stroke="{color}" stroke-opacity=".65" filter="url(#glow)"/>',
            f'<rect width="4" height="52" rx="2" fill="{color}"/>',
            f'<text x="14" y="21" fill="#e6e9ef" font-family="ui-monospace,monospace" '
            f'font-size="11.5">{label}</text>',
            f'<text x="14" y="38" fill="#8b95a5" font-family="ui-sans-serif,system-ui,sans-serif" '
            f'font-size="9.5">{group} · {_escape(node["language"])} · {node["lines"]} lines</text>',
            "</g>",
        ])
    legend_y = height - 24
    parts.append(
        f'<text x="32" y="{legend_y}" fill="#5c719b" font-family="ui-monospace,monospace" '
        f'font-size="10">arrow = resolved in-project import · max {MAX_NODES} nodes</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def build(project: str, max_nodes: int = 60, max_files: int = MAX_FILES) -> dict:
    root = workspace(project)
    max_nodes = max(1, min(int(max_nodes), MAX_NODES))
    max_files = max(1, min(int(max_files), MAX_FILES))
    paths: set[str] = set()
    text_by_path: dict[str, str] = {}
    for item in code_index.sources(root):
        if len(paths) >= max_files:
            break
        relative = item.relative_to(root).as_posix()
        if relative.startswith(".agent/"):
            continue
        if Path(relative).suffix.lower() not in LANGUAGES:
            continue
        text = _read_text(item)
        if text is None:
            continue
        paths.add(relative)
        text_by_path[relative] = text
    modules = _python_module_map(paths)
    resolved: dict[str, set[str]] = {
        path: _references(path, text_by_path[path], paths, modules) for path in paths
    }
    degree: Counter[str] = Counter()
    for source, targets in resolved.items():
        for target in targets:
            degree[source] += 1
            degree[target] += 1
    selected_paths = set(sorted(paths, key=lambda item: (-degree[item], item))[:max_nodes])
    ordered = sorted(selected_paths)
    node_index = {path: index for index, path in enumerate(ordered)}
    nodes = []
    for path in ordered:
        language = LANGUAGES.get(Path(path).suffix.lower(), "other")
        parts = Path(path).parts
        nodes.append({
            "id": f"n{node_index[path]}",
            "path": path,
            "label": _human_label(path),
            "group": parts[0] if len(parts) > 1 else "root",
            "language": language,
            "lines": len(text_by_path[path].splitlines()),
            "degree": degree[path],
        })
    edge_pairs = set()
    for source in ordered:
        for target in resolved[source]:
            if target in selected_paths and source != target:
                edge_pairs.add((source, target))
    edges = sorted(edge_pairs)
    mermaid = ["flowchart LR"]
    groups: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        groups[node["group"]].append(node["id"])
    for index, (group, ids) in enumerate(sorted(groups.items())):
        mermaid.append(f'  subgraph g{index}["{_mermaid(group)}"]')
        for node_id in ids:
            node = nodes[int(node_id[1:])]
            mermaid.append(f'    {node_id}["{_mermaid(node["path"])}"]')
        mermaid.append("  end")
    for source, target in edges:
        mermaid.append(f'  n{node_index[source]} --> n{node_index[target]}')
    return {
        "project": project,
        "nodes": nodes,
        "edges": [{"source": source, "target": target} for source, target in edges],
        "mermaid": "\n".join(mermaid),
        "svg": _svg(nodes, [{"source": source, "target": target}
                           for source, target in edges], project),
        "stats": {
            "files_scanned": len(paths),
            "files_shown": len(nodes),
            "edges": len(edges),
            "truncated": len(paths) > max_nodes,
        },
    }


@router.post("/architecture")
def architecture(body: DiagramRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    try:
        return build(body.project, body.max_nodes, body.max_files)
    except ValueError as error:
        raise HTTPException(400, str(error))
