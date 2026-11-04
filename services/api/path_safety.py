"""Cross-platform validation for repository-relative file targets."""
from pathlib import Path, PurePosixPath, PureWindowsPath


def unsafe_relative_path(value: str) -> bool:
    """Return True for empty, rooted, drive-qualified or escaping paths.

    A target that is valid on one host must not become an absolute path when
    the same request is handled on Windows. Check both path grammars instead
    of relying only on the host's Path implementation.
    """
    if not isinstance(value, str) or not value or "\x00" in value:
        return True
    for path in (Path(value), PurePosixPath(value), PureWindowsPath(value)):
        if path.is_absolute() or getattr(path, "drive", "") or getattr(path, "root", ""):
            return True
        if ".." in path.parts:
            return True
    return False
