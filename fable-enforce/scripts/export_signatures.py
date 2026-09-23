#!/usr/bin/env python3
"""Build the browser scan table directly from the canonical filter.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from filter import SIGNATURES  # noqa: E402


def build() -> list[dict[str, object]]:
    return [
        {
            "sig_id": sig_id,
            "name": name,
            "taxonomy": taxonomy,
            "patterns": patterns,
            "suppressor_flag": suppressor,
        }
        for sig_id, name, taxonomy, patterns, suppressor in SIGNATURES
    ]


def main() -> int:
    output = ROOT / "web" / "signatures.json"
    output.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {output.relative_to(ROOT)} from {len(SIGNATURES)} canonical signatures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
