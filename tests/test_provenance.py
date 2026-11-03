from pathlib import Path

from scripts.check_provenance import audit, find_forbidden_references

ROOT = Path(__file__).resolve().parents[1]


def test_repository_provenance_boundary_passes():
    result = audit(ROOT)
    assert result["passed"], result["violations"]
    assert result["submodules"]["upstream/agenticseek"]
    assert result["submodules"]["upstream/code-oss"]


def test_first_party_code_cannot_import_or_package_agenticseek():
    violations = find_forbidden_references(
        {
            "services/api/bad.py": "from agenticseek import query\n",
            "Dockerfile": "COPY upstream/agenticseek ./agenticseek\n",
            "apps/desktop/package.json": '"extraResources": [{"from": "../../upstream/agenticseek"}]',
        }
    )
    assert len(violations) == 3


def test_docs_and_ui_labels_may_reference_the_optional_agent():
    violations = find_forbidden_references(
        {
            "docs/AGENTICSEEK_INTEGRATION.md": "optional upstream/agenticseek submodule",
            "README.md": "AgenticSeek is GPL-3.0",
            "apps/web/index.html": "Browse with AgenticSeek",
            "tests/test_agenticseek.py": "from services.api.agenticseek import config",
        }
    )
    assert violations == []
