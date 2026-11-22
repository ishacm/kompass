"""Terminal review queue (works without Slack). Usage: python -m kompass.review.cli --reviewer isha"""
import argparse

from kompass.review.store import pending, record_review


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviewer", default="local")
    args = ap.parse_args()
    queue = pending()
    if not queue:
        print("No drafts waiting for review.")
        return
    for d in queue:
        print("\n" + "=" * 70)
        print(f"{d['name']} ({d['domain']})  prompt {d['prompt_version']}")
        play = d.get("play", {})
        print(f"  send to: {play.get('persona')}  |  channel: {play.get('channel')}  ({play.get('channel_note')})")
        for c in d["why_now"]:
            print(f"  why now: {c['claim']} [{c['source_id']}]")
        for k, v in d["sources"].items():
            print(f"  [{k}] {v}")
        print(f"\n  DRAFT: {d['body']}\n")
        choice = input("  [a]pprove / [e]dit / [r]eject / [s]kip: ").strip().lower()[:1]
        if choice == "a":
            print(record_review(d["draft_id"], "approve", reviewer=args.reviewer))
        elif choice == "e":
            final = input("  final text: ").strip()
            reason = input("  why did you change it? ").strip()
            print(record_review(d["draft_id"], "edit", reviewer=args.reviewer, final_body=final, reason=reason))
        elif choice == "r":
            reason = input("  reason: ").strip()
            print(record_review(d["draft_id"], "reject", reviewer=args.reviewer, reason=reason))


if __name__ == "__main__":
    main()
