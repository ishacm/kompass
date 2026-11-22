#!/usr/bin/env python3
"""Block commits that contain API keys or other secrets.

Runs in CI on every push and pull request, and can run as a local git hook:
  cp scripts/check_secrets.py .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
Usage: python scripts/check_secrets.py [--all]     (--all scans every tracked file; default: staged files)
Exit code 1 = secret found.
"""
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "Anthropic key": r"sk-ant-[A-Za-z0-9_\-]{20,}",
    "OpenAI-style key": r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}",
    "Groq key": r"\bgsk_[A-Za-z0-9]{20,}",
    "Google API key": r"\bAIza[0-9A-Za-z_\-]{30,}",
    "Perplexity key": r"\bpplx-[A-Za-z0-9]{20,}",
    "Slack token": r"\bxox[abposr]-[A-Za-z0-9\-]{10,}",
    "Slack webhook": r"hooks\.slack\.com/services/[A-Za-z0-9/]{20,}",
    "HubSpot token": r"\bpat-(?:na|eu)\d?-[a-f0-9\-]{30,}",
    "GitHub token": r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}",
    "Private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "Hard-coded secret": r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*[\"'][A-Za-z0-9_\-/+]{20,}[\"']",
}
FORBIDDEN_FILES = re.compile(r"(^|/)(\.env(\..*)?|.*\.pem|.*\.p12|id_rsa.*|credentials\.json|.*\.duckdb(\.wal)?)$")
ALLOWED_FILES = {".env.example"}


def files(all_files: bool) -> list[str]:
    cmd = ["git", "ls-files"] if all_files else ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]
    return [f for f in subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.splitlines() if f]


def scan(paths: list[str]) -> list[str]:
    hits = []
    for p in paths:
        if Path(p).name not in ALLOWED_FILES and FORBIDDEN_FILES.search(p):
            hits.append(f"{p}: this file type must never be committed")
            continue
        try:
            text = Path(p).read_text(encoding="utf-8", errors="ignore")
        except (FileNotFoundError, IsADirectoryError):
            continue
        for name, pat in PATTERNS.items():
            for m in re.finditer(pat, text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{p}:{line}: possible {name}")
    return hits


if __name__ == "__main__":
    found = scan(files("--all" in sys.argv))
    if found:
        print("SECRET CHECK FAILED. Remove these, rotate any real key, and use environment variables / secrets:")
        print("\n".join(f"  - {h}" for h in found))
        sys.exit(1)
    print("secret check passed")
