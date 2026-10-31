"""Count tracked authored source lines, excluding dependencies and generated files."""
import json
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXTENSIONS={".py",".rs",".js",".cjs",".mjs",".ts",".tsx",".jsx",".sql",".html",".css",".sh",".yml",".yaml"}
EXCLUDED={"node_modules","dist","build","target",".venv","vendor",".git","__pycache__"}
def report():
    paths=subprocess.check_output(["git","ls-files","-z"],cwd=ROOT).decode().split("\0")
    files=lines=0
    by_ext={}
    for name in paths:
        if not name:continue
        p=Path(name)
        if p.suffix.lower() not in EXTENSIONS or any(part in EXCLUDED for part in p.parts):continue
        try:
            data=(ROOT/p).read_text(encoding="utf-8")
        except (OSError,UnicodeError):continue
        count=len(data.splitlines())
        files+=1
        lines+=count
        by_ext[p.suffix.lower()]=by_ext.get(p.suffix.lower(),0)+count
    return {"authored_source_files":files,"authored_source_lines":lines,"lines_by_extension":dict(sorted(by_ext.items())),"excludes_generated_and_dependencies":True}
if __name__=="__main__":print(json.dumps(report(),indent=2))
