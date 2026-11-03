"""Report tracked source lines with separate first-party and licensed upstream totals.

Count only committed source files, excluding generated bundles, build outputs
and dependencies. Vendored source is real code but never represented as
first-party original authorship.
"""
import json
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXTENSIONS={".py",".rs",".js",".cjs",".mjs",".ts",".tsx",".jsx",".sql",".html",".css",".sh",".yml",".yaml"}
EXCLUDED={"node_modules","dist","build","target",".venv",".git","__pycache__","assets"}
GENERATED_FILES={"packages/ui/tokens.css","packages/ui/icons.svg","packages/ui/favicon.svg"}
def report():
    paths=subprocess.check_output(["git","ls-files","-z"],cwd=ROOT).decode("utf-8").split("\0")
    counts={"first_party":{"files":0,"lines":0},"third_party":{"files":0,"lines":0}}
    by_ext={}
    for name in paths:
        if not name:continue
        path=Path(name)
        if path.suffix.lower() not in EXTENSIONS or any(part in EXCLUDED for part in path.parts):
            continue
        if path.as_posix() in GENERATED_FILES:
            continue
        try:content=(ROOT/path).read_text(encoding="utf-8")
        except (OSError,UnicodeError):continue
        lines=len(content.splitlines())
        group="third_party" if path.parts[0]=="third_party" else "first_party"
        counts[group]["files"]+=1
        counts[group]["lines"]+=lines
        by_ext[path.suffix.lower()]=by_ext.get(path.suffix.lower(),0)+lines
    return {
        "authored_source_files":counts["first_party"]["files"],
        "authored_source_lines":counts["first_party"]["lines"],
        "licensed_third_party_source_files":counts["third_party"]["files"],
        "licensed_third_party_source_lines":counts["third_party"]["lines"],
        "total_repository_source_lines":counts["first_party"]["lines"]+counts["third_party"]["lines"],
        "lines_by_extension":dict(sorted(by_ext.items())),
        "excludes_generated_and_dependencies":True,
        "third_party_not_claimed_as_authored":True
    }
if __name__=="__main__":print(json.dumps(report(),indent=2))
