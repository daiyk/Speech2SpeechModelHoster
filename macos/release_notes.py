"""Read the desktop version and GitHub release description from CHANGELOG.md."""

import argparse
import re
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
NUMBER = r"(?:0|[1-9][0-9]*)"
TAG = rf"v{NUMBER}\.{NUMBER}\.{NUMBER}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="select the changelog entry for this Git tag")
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args()
    if args.tag is not None and not re.fullmatch(TAG, args.tag):
        parser.error("expected a tag such as v0.2.0")
    sections = re.split(r"^## (.+)$", CHANGELOG.read_text(encoding="utf-8"), flags=re.M)
    entries = {}
    for heading, body in zip(sections[1::2], sections[2::2]):
        match = re.fullmatch(rf"({TAG}) — [0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}", heading)
        if match:
            tag = match[1]
            if tag in entries:
                parser.error(f"duplicate entry for {tag} in CHANGELOG.md")
            entries[tag] = body.strip()
    tag = args.tag or next(iter(entries), None)
    if not entries.get(tag):
        parser.error(f"missing release notes for {tag} in CHANGELOG.md")
    print(tag[1:] if args.version_only else entries[tag])


if __name__ == "__main__":
    main()
