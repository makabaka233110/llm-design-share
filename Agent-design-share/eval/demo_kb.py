"""Load the demo knowledge base into a running app: the 167 good passages of eval/data (the 33 deliberately
flawed ones, used by the retrieval experiment, are left out). Creates the computing / business / science domains.
Runs through the HTTP API, so it goes into the normal data dir of the running app.

  bash start.sh                                  # in another terminal
  python3 eval/demo_kb.py [--user default] [--base http://127.0.0.1:8000]

The knowledge base is empty by default: learners bring their own reviewed material (proposal §2).
"""
import argparse
import json
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "passages.jsonl"
NAMES = {"computing": "计算机", "business": "商业管理", "science": "基础科学"}


def call(base, user, method, path, body=None):
    req = urllib.request.Request(base + path, method=method, headers={"X-User": user, "Content-Type": "application/json"},
                                 data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="default", help="learner id shown at the bottom left of the app")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    a = ap.parse_args()
    have = {d["title"] for d in call(a.base, a.user, "GET", "/api/kb/docs")}
    domains = {d["name"]: d["id"] for d in call(a.base, a.user, "GET", "/api/domains")}
    for name in NAMES.values():
        if name not in domains:
            domains[name] = call(a.base, a.user, "POST", "/api/domains", {"name": name})["id"]
    added = 0
    for p in map(json.loads, DATA.read_text(encoding="utf-8").splitlines()):
        if p["quality"] != "good" or p["title"] in have:
            continue
        call(a.base, a.user, "POST", "/api/kb/docs", {"title": p["title"], "body": p["text"], "topic": p["topic"],
             "source": p["source"], "reviewed": True, "domain_id": domains[NAMES[p["domain"]]], "structure": False})
        added += 1
    print(f"added {added} reviewed passages for user '{a.user}' (skipped existing titles: {len(have)})")


if __name__ == "__main__":
    main()
