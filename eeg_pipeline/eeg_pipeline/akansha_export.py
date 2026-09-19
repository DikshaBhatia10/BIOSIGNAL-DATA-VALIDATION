"""
Builds the comparison export Akansha's Power BI evaluation layer consumes.

Takes the two REAL QC results already produced by the pipeline (one run on
the raw file, one run on the cleaned file — both from qc_agent.agent.run_qc,
not fabricated) and writes them out as a flat CSV: one row per check, so
Power BI can directly compute pass-rate-before vs pass-rate-after per check
type without any reshaping on her end.

This module does not invent, simulate, or estimate any values — it only
reformats whatever the QC agent actually returned for this specific file.
"""

from __future__ import annotations

import csv
import os


def build_comparison_csv(qc_raw: dict, qc_cleaned: dict, output_dir: str) -> str:
    """
    qc_raw / qc_cleaned: the `result` dicts returned by qc_agent.agent.run_qc()
    for the same recording — one from the raw pass, one from the cleaned pass.
    """
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "akansha_comparison_export.csv")

    file_exists = os.path.isfile(out_path)

    fieldnames = [
        "source_file",
        "check_name",
        "raw_passed",
        "cleaned_passed",
        "raw_detail",
        "cleaned_detail",
        "raw_quality_score",
        "cleaned_quality_score",
    ]

    with open(out_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        raw_checks = qc_raw["checks"]
        clean_checks = qc_cleaned["checks"]

        # Only writes rows for checks that genuinely exist in both real results —
        # if the two dicts ever disagree on which checks ran, that's a real bug
        # to notice, not something to paper over with a default value.
        for check_name in raw_checks:
            if check_name not in clean_checks:
                raise KeyError(
                    f"Check '{check_name}' present in raw QC result but missing "
                    f"from cleaned QC result — investigate before exporting, "
                    f"do not silently skip."
                )
            writer.writerow({
                "source_file": qc_raw["file"],
                "check_name": check_name,
                "raw_passed": raw_checks[check_name]["passed"],
                "cleaned_passed": clean_checks[check_name]["passed"],
                "raw_detail": {k: v for k, v in raw_checks[check_name].items() if k != "passed"},
                "cleaned_detail": {k: v for k, v in clean_checks[check_name].items() if k != "passed"},
                "raw_quality_score": qc_raw["quality_score"],
                "cleaned_quality_score": qc_cleaned["quality_score"],
            })

    return out_path
