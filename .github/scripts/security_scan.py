#!/usr/bin/env python3
"""Repository security scan: tracked files must contain no credentials and no secret files.

    python3 .github/scripts/security_scan.py

- **Forbidden files:** environment files other than ``*.env.example``, TLS keys and
  certificates, and anything under ``deploy/certs/``.
- **Credential shapes** in every tracked text file: private keys, AWS access key ids,
  Google OAuth client secrets, access and refresh tokens, OpenAI, GitHub and Slack tokens.
  The test suite's deliberately fake values are allow-listed by exact value below.
- **Example files** (``*.env.example``) may only hold empty values, placeholders or
  non-secret defaults for their secret settings.

Exit status 1 lists every finding by file and line (never the matched value).
"""

import re
import subprocess
import sys
from pathlib import Path

FORBIDDEN_FILES = [
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)\.env\.(?!example$)[^/]+$"),
    re.compile(r"\.(pem|key|p12|pfx|crt)$"),
    re.compile(r"^deploy/certs/"),
]
PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "Google OAuth client secret": re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}"),
    "Google access token": re.compile(r"\bya29\.[A-Za-z0-9_-]{30,}"),
    "Google refresh token": re.compile(r"\b1//0[A-Za-z0-9_-]{40,}"),
    "OpenAI key": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{40,}"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
}
# Fake values the tests use on purpose (they look like credentials so redaction is tested).
ALLOWED = {"AKIAABCDEFGHIJKLMNOP", "AKIAIOSFODNN7EXAMPLE"}
SECRET_SETTINGS = re.compile(
    r"^#?\s*(SECRET_KEY|[A-Z_]*PASSWORD|[A-Z_]*SECRET[A-Z_]*|[A-Z_]*API_KEY|[A-Z_]*TOKEN[A-Z_]*KEY"
    r"|S3_[A-Z_]*ACCESS_KEY[A-Z_]*|GOOGLE_CLIENT_SECRET)=(.*)$"
)
PLACEHOLDER = re.compile(r"^(|replace[-_a-z0-9]*|change[-_a-z0-9]*|test-only-[-a-z0-9]*)$", re.I)


def tracked() -> list[str]:
    output = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    return [name for name in output.decode().split("\0") if name]


def main() -> int:
    findings: list[str] = []
    for name in tracked():
        if any(rule.search(name) for rule in FORBIDDEN_FILES):
            findings.append(f"{name}: secret-bearing file is tracked")
            continue
        path = Path(name)
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary
        for number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS.items():
                for match in pattern.finditer(line):
                    if match.group(0) not in ALLOWED:
                        findings.append(f"{name}:{number}: looks like a {label}")
            if name.endswith(".env.example") and (setting := SECRET_SETTINGS.match(line.strip())):
                if not PLACEHOLDER.match(setting.group(2).strip()):
                    findings.append(f"{name}:{number}: {setting.group(1)} has a non-placeholder value")
    for finding in findings:
        print(finding)
    print(f"security scan: {len(tracked())} tracked files, {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
