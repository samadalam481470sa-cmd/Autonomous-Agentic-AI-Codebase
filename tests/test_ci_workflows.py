"""GitHub Actions workflows must not use Node 20 action releases."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# First major release of each action that runs on Node 24 instead of Node 20.
MINIMUM_NODE24_MAJOR = {
    "actions/checkout": 7,
    "actions/download-artifact": 8,
    "actions/setup-node": 7,
    "actions/setup-python": 7,
    "actions/upload-artifact": 7,
}

USE_REF = re.compile(r"^\s*uses:\s*([^@\s]+)@v(\d+)\b", re.MULTILINE)


def test_workflows_use_node24_action_releases():
    violations = []
    for workflow in sorted(WORKFLOWS.glob("*.y*ml")):
        text = workflow.read_text(encoding="utf-8")
        for match in USE_REF.finditer(text):
            action, major = match.group(1), int(match.group(2))
            minimum = MINIMUM_NODE24_MAJOR.get(action)
            if minimum is not None and major < minimum:
                violations.append(
                    f"{workflow.name}: {action}@v{major} (need v{minimum}+)"
                )
    assert not violations, "Node 20 action releases remain:\n" + "\n".join(violations)
