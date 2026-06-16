"""CI guard: arm files must compute holdout_passed conditionally, not hardcode 1."""
import re
from pathlib import Path


def test_no_arm_hardcodes_holdout_passed_unconditionally():
    arm_dir = Path(__file__).parents[1] / "cosmu" / "research"
    arm_files = list(arm_dir.glob("*_arm.py"))
    assert arm_files, "no arm files found — check path"

    bad_lines = []
    for f in arm_files:
        for i, line in enumerate(f.read_text().splitlines(), 1):
            stripped = line.strip()
            # Match: "holdout_passed": 1 (bare literal, no ' if ' on the same line)
            if re.search(r'"holdout_passed"\s*:\s*1\b', stripped) and " if " not in stripped:
                bad_lines.append(f"{f.name}:{i}: {stripped}")

    assert not bad_lines, (
        "arm files hardcode holdout_passed:1 without a conditional — add '1 if <oos_metric> > 0 else 0':\n"
        + "\n".join(bad_lines)
    )
