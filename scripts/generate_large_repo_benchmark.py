"""Generate a disposable million-line project for indexing performance tests.

Run explicitly, never from app startup. This is benchmark DATA, not source code
added to the application. Output is outside the repository by default.
"""
import argparse
import json
import time
from pathlib import Path

def generate(destination,files=1000,lines_per_file=1000):
    destination=Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=True)
    start=time.monotonic()
    for index in range(files):
        path=destination/f"module_{index:05d}.py"
        with path.open("w",encoding="utf-8") as stream:
            for line in range(lines_per_file):
                stream.write(f"item_{index}_{line} = {index} + {line}\n")
    return {"files":files,"lines":files*lines_per_file,"seconds":round(time.monotonic()-start,3),"destination":str(destination)}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--destination",default="./benchmark-output")
    parser.add_argument("--files",type=int,default=1000)
    parser.add_argument("--lines-per-file",type=int,default=1000)
    args=parser.parse_args()
    if not (1<=args.files<=10000 and 1<=args.lines_per_file<=10000):
        parser.error("Each dimension must be between 1 and 10,000")
    print(json.dumps(generate(args.destination,args.files,args.lines_per_file),indent=2))
