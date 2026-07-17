"""Emit scripted JSONL provider events for driver tests."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main() -> int:
    """Emit one scripted provider scenario as JSONL on stdout."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="ok")
    args = parser.parse_args()

    if args.scenario == "ok":
        print(json.dumps({"kind": "tool_call", "label": "Edit src/foo.py"}))
        print(json.dumps({"kind": "output_chunk", "label": "", "text": "working"}))
        print(json.dumps({"kind": "tool_call", "label": "Bash uv run pytest"}))
        return 0
    if args.scenario == "garbage":
        print("this is not json")
        print(json.dumps({"kind": "tool_call", "label": "Read README.md"}))
        print(json.dumps(["a", "list", "not", "a", "dict"]))
        print(json.dumps({"kind": "unknown_kind", "label": "x"}))
        return 0
    if args.scenario == "fail":
        print(json.dumps({"kind": "tool_call", "label": "Bash failing"}))
        print("boom", file=sys.stderr)
        return 3
    if args.scenario == "hang":
        print(json.dumps({"kind": "tool_call", "label": "thinking"}), flush=True)
        time.sleep(60)
        return 0
    if args.scenario == "spawn_hang":
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        Path("child.pid").write_text(str(child.pid), encoding="utf-8")
        print(
            json.dumps({"kind": "tool_call", "label": f"child {os.getpid()}"}),
            flush=True,
        )
        time.sleep(60)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
