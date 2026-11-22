"""Signal classifier precision / recall against hand labels.

Hand labels: eval/signal_labels.csv with columns title,location,label  (label one of SIGNAL_TYPES).
Label ~100 real postings yourself, then: python eval/signal_check.py
Runs the real classifier (KOMPASS_LLM=live) on each title; mock mode only tests the harness.
"""
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kompass.signals.classify_signals import classify_posting, SIGNAL_TYPES  # noqa: E402


def evaluate(rows: list[dict]) -> dict:
    tp = Counter(); fp = Counter(); fn = Counter()
    confusions = Counter()
    for r in rows:
        pred = classify_posting({"title": r["title"], "location": r.get("location", "")})["signal_type"]
        gold = r["label"]
        if pred == gold:
            tp[gold] += 1
        else:
            fp[pred] += 1; fn[gold] += 1; confusions[(gold, pred)] += 1
    # "is this a GTM signal at all?" is what decides whether a human sees it
    gold_sig = [r["label"] != "none" for r in rows]
    pred_sig = [classify_posting({"title": r["title"], "location": r.get("location", "")})["signal_type"] != "none"
                for r in rows]
    b_tp = sum(g and p for g, p in zip(gold_sig, pred_sig))
    b_fp = sum((not g) and p for g, p in zip(gold_sig, pred_sig))
    b_fn = sum(g and (not p) for g, p in zip(gold_sig, pred_sig))
    return {
        "n": len(rows),
        "exact_accuracy": round(sum(tp.values()) / len(rows), 3) if rows else None,
        "signal_precision": round(b_tp / (b_tp + b_fp), 3) if (b_tp + b_fp) else None,
        "signal_recall": round(b_tp / (b_tp + b_fn), 3) if (b_tp + b_fn) else None,
        "top_confusions": [f"{g} -> {p}: {n}" for (g, p), n in confusions.most_common(5)],
    }


if __name__ == "__main__":
    path = Path(__file__).parent / "signal_labels.csv"
    if not path.exists():
        sys.exit("Create eval/signal_labels.csv (title,location,label) first.")
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    bad = [r for r in rows if r["label"] not in SIGNAL_TYPES]
    if bad:
        sys.exit(f"Unknown labels: {sorted({r['label'] for r in bad})}")
    print(evaluate(rows))
