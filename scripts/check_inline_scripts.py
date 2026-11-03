"""Check inline browser JavaScript syntax with the installed Node.js runtime."""
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside=False
        self.scripts=[]
    def handle_starttag(self,tag,attrs):
        if tag=="script" and not dict(attrs).get("src"):
            self.inside=True
            self.scripts.append("")
    def handle_data(self,data):
        if self.inside:
            self.scripts[-1]+=data
    def handle_endtag(self,tag):
        if tag=="script":
            self.inside=False

def check(path):
    parser=Scripts()
    parser.feed(Path(path).read_text(encoding="utf-8"))
    for index,source in enumerate(parser.scripts):
        with tempfile.TemporaryDirectory() as temporary:
            file=Path(temporary)/"inline.js"
            file.write_text(source,encoding="utf-8")
            run=subprocess.run(["node","--check",str(file)],capture_output=True,text=True)
            if run.returncode:
                raise RuntimeError(f"{path} script {index}: {run.stderr}")
    return len(parser.scripts)

if __name__=="__main__":
    for name in ("apps/web/index.html","apps/web/studio.html","apps/web/control.html"):
        print(name,check(name),"inline scripts validated")
