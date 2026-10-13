#!/usr/bin/env python3
"""Turns the agents' token ledger into the token report the brief asks for.

Usage:
  python3 scripts/token-report.py [/srv/agent-studio/ledger/usage.jsonl] > docs/TOKENS.md

Tables: per agent and per model, each split into planning, coding, review/test and retries,
plus run counts, failures, and how many runs had no usage data (reported as missing, never guessed).
"""
import json
import sys
from collections import defaultdict

PHASES = [("planning", "Planning"), ("coding", "Coding"), ("review/test", "Review / test"), ("retry", "Retries")]
PHASE_OF = {"planning": "planning", "coding": "coding", "review": "review/test", "test": "review/test", "retry": "retry"}


def load(path):
    rows = []
    with open(path) as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"warning: skipped bad line {n}", file=sys.stderr)
    return rows


def fmt(n):
    return f"{n:,}" if n else "0"


def table(rows, key, title):
    agg = defaultdict(lambda: {"runs": 0, "missing": 0, "fail": 0, **{p: 0 for p, _ in PHASES}})
    for r in rows:
        a = agg[r.get(key) or "unknown"]
        a["runs"] += 1
        if r.get("status") != "ok":
            a["fail"] += 1
        tot = r.get("total_tokens")
        if tot is None:
            a["missing"] += 1
            continue
        a[PHASE_OF.get(r.get("phase"), "planning")] += tot
    head = "| " + title + " | " + " | ".join(t for _, t in PHASES) + " | Total | Runs | Failed runs | Runs without usage |"
    out = [head, "|" + "---|" * (len(PHASES) + 5)]
    for name in sorted(agg, key=lambda k: -sum(agg[k][p] for p, _ in PHASES)):
        a = agg[name]
        total = sum(a[p] for p, _ in PHASES)
        out.append(f"| {name} | " + " | ".join(fmt(a[p]) for p, _ in PHASES)
                   + f" | **{fmt(total)}** | {a['runs']} | {a['fail']} | {a['missing']} |")
    return "\n".join(out)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/srv/agent-studio/ledger/usage.jsonl"
    rows = load(path)
    if not rows:
        print("No ledger rows found.")
        return
    grand = sum(r.get("total_tokens") or 0 for r in rows)
    by_phase = defaultdict(int)
    for r in rows:
        by_phase[PHASE_OF.get(r.get("phase"), "planning")] += r.get("total_tokens") or 0
    missing = sum(1 for r in rows if r.get("total_tokens") is None)
    first, last = rows[0].get("ts", "?"), rows[-1].get("ts", "?")

    print("# Token and model report\n")
    print(f"Source: `{path}`, {len(rows)} agent runs from {first} to {last}. "
          f"Numbers come from each runtime's own usage report. {missing} runs reported no usage and are counted "
          "as runs only; their tokens are missing, not estimated.\n")
    print("## By agent\n")
    print(table(rows, "agent", "Agent") + "\n")
    print("## By model\n")
    print(table(rows, "model", "Model") + "\n")
    print("## Share by phase\n")
    for p, t in PHASES:
        share = (by_phase[p] / grand * 100) if grand else 0
        print(f"- **{t}:** {fmt(by_phase[p])} tokens ({share:.0f}%)")
    print(f"- **Total:** {fmt(grand)} tokens\n")
    print("## Where the tokens went, in plain words\n")
    print("_Write 3 to 5 sentences here from the tables above: which roles used most and why, how much went to "
          "retries, and what the wake-up pre-check saved (idle wake-ups cost no tokens)._")


if __name__ == "__main__":
    main()
