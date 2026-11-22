"""CI gate: fail the build if a candidate run is worse than the baseline.

Usage:
  python eval/gate.py --report eval/reports/candidate.json --version v2 [--model M]
  python eval/gate.py --report ... --version v1 --update-baseline      # after an approved change
Exit code 1 = blocked.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "eval" / "baseline.json"


def compare(candidate: dict, baseline: dict | None, rules: dict) -> list[str]:
    fails = []
    if candidate["cases"] < rules["absolute"]["min_cases"]:
        fails.append(f"only {candidate['cases']} cases (min {rules['absolute']['min_cases']})")
    if candidate["must_not_violations"] > rules["absolute"]["must_not_violations"]:
        fails.append(f"{candidate['must_not_violations']} forbidden-phrase violations")
    if baseline:
        for k, drop in rules["max_drop"].items():
            if candidate[k] < baseline[k] - drop:
                fails.append(f"{k} dropped {baseline[k]} -> {candidate[k]} (allowed -{drop})")
        for k, inc in rules["must_not_increase"].items():
            if candidate[k] > baseline[k] + inc:
                fails.append(f"{k} rose {baseline[k]} -> {candidate[k]}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--model")
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args()
    report = json.loads(args.report.read_text())
    run = next((r for r in report["runs"] if r["version"] == args.version
                and (args.model is None or r["model"] == args.model)), None)
    if not run:
        sys.exit(f"no run for {args.version} in report")
    if args.update_baseline:
        BASELINE.write_text(json.dumps({**run["summary"], "version": run["version"], "model": run["model"],
                                        "llm_mode": report["llm_mode"], "run_at": report["run_at"]}, indent=2))
        print(f"baseline updated to {run['version']} / {run['model']}")
        return
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else None
    if baseline and baseline.get("llm_mode") != report["llm_mode"]:
        sys.exit(f"baseline is {baseline.get('llm_mode')} mode but report is {report['llm_mode']}: not comparable")
    rules = yaml.safe_load((ROOT / "eval" / "gate.yaml").read_text())
    fails = compare(run["summary"], baseline, rules)
    if fails:
        print("GATE FAILED:\n  - " + "\n  - ".join(fails))
        sys.exit(1)
    print(f"GATE PASSED: {args.version} vs baseline {baseline.get('version') if baseline else '(none)'}")


if __name__ == "__main__":
    main()
