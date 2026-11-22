"""Measure LLM segment-label accuracy against hand labels.

Hand labels: eval/hand_labels.csv with columns domain,segment (label 50-100 accounts yourself).
Usage: python eval/label_check.py
Report the accuracy number and the confusion pairs in the Module 1 case study.
"""
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kompass.db import connect  # noqa: E402

labels_path = Path(__file__).parent / "hand_labels.csv"
if not labels_path.exists():
    sys.exit("Create eval/hand_labels.csv (domain,segment) first.")

hand = {r["domain"].strip().lower(): r["segment"].strip() for r in csv.DictReader(open(labels_path))}
con = connect(read_only=True)
pred = dict(con.execute("SELECT domain, segment FROM accounts WHERE segment IS NOT NULL").fetchall())

pairs = [(hand[d], pred[d]) for d in hand if d in pred]
if not pairs:
    sys.exit("No overlap between hand labels and classified accounts.")
correct = sum(h == p for h, p in pairs)
print(f"accounts compared: {len(pairs)}")
print(f"accuracy: {correct / len(pairs):.1%}")
print("most common confusions (hand -> llm):")
for (h, p), n in Counter((h, p) for h, p in pairs if h != p).most_common(5):
    print(f"  {h} -> {p}: {n}")
