"""Merge two LLM raters' ratings into the blank sheets: rater A -> _r1, rater B -> _r2.

  python3 eval/rating/llm/merge.py /tmp/mianbi-rating/A /tmp/mianbi-rating/B

Writes eval/rating/llm/<sheet>.csv. Run `eval/run.py stats` on these after copying the answer keys next to them.
"""
import csv
import json
import sys
from pathlib import Path

csv.field_size_limit(10**9)
HERE = Path(__file__).resolve().parent
for sheet in sorted(HERE.parent.glob("*_rating.csv")) + sorted(HERE.parent.glob("*_labels.csv")) + [HERE.parent / "evaluator_citations.csv"]:
    rows = list(csv.DictReader(open(sheet, encoding="utf-8")))
    cols = [c for c in rows[0] if c.endswith(("_r1", "_r2"))]
    for src, suffix in zip(sys.argv[1:3], ("_r1", "_r2")):
        f = Path(src) / f"{sheet.stem}.ratings.jsonl"
        got = {}
        for line in (f.read_text(encoding="utf-8").splitlines() if f.exists() else []):
            if line.strip():
                d = json.loads(line)
                got[int(d.pop("item"))] = d  # a later line for the same item wins
        for r in rows:
            d = got.get(int(r["item"]), {})
            for c in cols:
                if c.endswith(suffix) and d.get(c[:-3]) is not None:
                    r[c] = d[c[:-3]]
        print(f"{sheet.name:<26} {suffix}: {len(got)}/{len(rows)}")
    with open(HERE / sheet.name, "w", encoding="utf-8", newline="") as out:
        w = csv.DictWriter(out, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
