"""
EEG pipeline orchestrator.

Full real flow, no synthetic steps:
  1. Raw file -> QC agent (pass 1: "raw")
  2. Raw file -> Analysis agent -> produces a real cleaned .fif file on disk
  3. Cleaned file -> uploaded to MinIO (real object storage, not a stub)
  4. Cleaned file -> QC agent again (pass 2: "cleaned")
  5. Both real QC results -> exported to a CSV Akansha's Power BI reads directly

Follows the same call -> collect -> combine pattern as the CDAC-style
orchestrator you shared (that structure is a generic client pattern, not
proprietary logic), but over plain HTTP against the FastAPI servers in this
project.

MANUAL SETUP REQUIRED BEFORE RUNNING:
  - Start the QC agent server:       uvicorn qc_agent.server:app --port 9001
  - Start the analysis agent server: uvicorn analysis_agent.server:app --port 9002
  - Have MinIO running and the environment variables from
    storage/minio_client.py set (MINIO_ENDPOINT, MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY, MINIO_BUCKET, MINIO_SECURE) — the bucket must already
    exist.
  - Run: python orchestrator.py <path_to_real_eeg_file>

Run with: python orchestrator.py <path_to_eeg_file>
"""

from __future__ import annotations

import json
import sys
import os
import glob
import httpx

from storage.minio_client import upload_file
from akansha_export import build_comparison_csv
from report_agent import generate_report

QC_AGENT_URL = "http://127.0.0.1:9001/message"
ANALYSIS_AGENT_URL = "http://127.0.0.1:9002/message"
OUT_DIR = os.path.abspath("./outputs")  # absolute — the analysis agent runs in a
# different folder (analysis_agent/), so a relative path here would resolve
# against THAT server's working directory, not this script's. This bit us once
# already: the cleaned file existed, just in the wrong place.
TIMEOUT_SECONDS = 3600  # EEG files can be large; give it room


def call_agent(url: str, payload: dict) -> dict:
    try:
        resp = httpx.post(url, json=payload, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


def run_pipeline(file_path: str) -> dict:
    os.makedirs(OUT_DIR, exist_ok=True)

    print("[orchestrator] Running QC on raw file...")
    qc_raw = call_agent(QC_AGENT_URL, {"file_path": file_path, "pass_label": "raw"})
    if qc_raw.get("status") != "ok":
        print(f"[orchestrator] Raw QC failed: {qc_raw.get('error')}")
        return {"error": "raw_qc_failed", "detail": qc_raw}
    print(f"[orchestrator] Raw QC done — quality_score={qc_raw['result']['quality_score']}")

    print("[orchestrator] Running analysis (filter + ICA cleaning)...")
    analysis = call_agent(ANALYSIS_AGENT_URL, {"file_path": file_path, "output_dir": OUT_DIR})
    if analysis.get("status") != "ok":
        print(f"[orchestrator] Analysis failed: {analysis.get('error')}")
        return {"error": "analysis_failed", "detail": analysis}
    cleaned_path = analysis["result"]["cleaned_file"]  # the .vhdr — its .eeg/.vmrk
    # siblings live in the same folder, written by export_raw() in analysis_agent
    print(f"[orchestrator] Analysis done — cleaned file at {cleaned_path}")

    print("[orchestrator] Running QC on cleaned file (second pass)...")
    qc_clean = call_agent(QC_AGENT_URL, {"file_path": cleaned_path, "pass_label": "cleaned"})
    if qc_clean.get("status") != "ok":
        print(f"[orchestrator] Cleaned QC failed: {qc_clean.get('error')}")
        return {"error": "cleaned_qc_failed", "detail": qc_clean}
    print(f"[orchestrator] Cleaned QC done — quality_score={qc_clean['result']['quality_score']}")

    # Folder name in MinIO = the ORIGINAL file's name, as-is (no extension) — so
    # every EEG recording gets its own folder, and the folder name matches the
    # source file you'd recognize it by, not an arbitrary "cleaned/" bucket
    # shared across every run.
    source_stem = os.path.splitext(os.path.basename(file_path))[0]

    print("[orchestrator] Generating Gemini summary report...")
    pre_report = {
        "input_file": file_path,
        "qc_raw": qc_raw["result"],
        "analysis": analysis["result"],
        "qc_cleaned": qc_clean["result"],
    }
    try:
        report_text = generate_report(pre_report)
        report_path = os.path.join(OUT_DIR, f"{source_stem}_gemini_report.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        print(f"[orchestrator] Gemini report saved locally to {report_path}")
    except Exception as e:
        # Not fatal — the pipeline's actual job (validation + storage) already
        # succeeded by this point. A missing/failed report shouldn't discard
        # real QC results, but it's a real failure worth surfacing, not hiding.
        print(f"[orchestrator] Gemini report generation FAILED (continuing anyway): {e}")
        report_path = None

    print(f"[orchestrator] Uploading cleaned BrainVision trio + report to MinIO folder '{source_stem}/'...")
    try:
        cleaned_dir = os.path.dirname(cleaned_path)
        cleaned_stem = os.path.splitext(os.path.basename(cleaned_path))[0]
        sibling_files = sorted(glob.glob(os.path.join(cleaned_dir, cleaned_stem + ".*")))
        if len(sibling_files) < 3:
            # Real check, not decorative — if export_raw() didn't produce all
            # three files, uploading just the .vhdr would silently ship a
            # broken, unopenable set to MinIO.
            raise RuntimeError(
                f"Expected 3 BrainVision files (.vhdr/.eeg/.vmrk) for '{cleaned_stem}', "
                f"found {len(sibling_files)}: {sibling_files}. Check that pybv is "
                f"installed and export_raw() completed successfully."
            )
        files_to_upload = list(sibling_files)
        if report_path:
            files_to_upload.append(report_path)

        uploaded_objects = []
        for f in files_to_upload:
            obj = upload_file(f, object_name=f"{source_stem}/{os.path.basename(f)}")
            uploaded_objects.append(obj)
        print(f"[orchestrator] Uploaded to MinIO under '{source_stem}/': {uploaded_objects}")
        object_name = uploaded_objects  # keep the full set in the combined report
    except Exception as e:
        # Real failure, not swallowed — a failed upload means the "clean data
        # goes to MinIO" claim in the pipeline didn't actually happen this run.
        print(f"[orchestrator] MinIO upload FAILED: {e}")
        return {"error": "minio_upload_failed", "detail": str(e)}

    print("[orchestrator] Building Akansha comparison export...")
    csv_path = build_comparison_csv(qc_raw["result"], qc_clean["result"], OUT_DIR)
    print(f"[orchestrator] Comparison CSV for Akansha written to {csv_path}")

    combined = {
        "input_file": file_path,
        "qc_raw": qc_raw["result"],
        "analysis": analysis["result"],
        "minio_folder": source_stem,
        "minio_objects": object_name,
        "qc_cleaned": qc_clean["result"],
        "gemini_report_file": report_path,
        "akansha_export": csv_path,
    }

    report_path = os.path.join(OUT_DIR, "eeg_pipeline_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, default=str)
    print(f"\n[orchestrator] Combined report saved to {report_path}")
    print(
        f"[orchestrator] Quality score: {qc_raw['result']['quality_score']} (raw) "
        f"→ {qc_clean['result']['quality_score']} (cleaned)"
    )

    return combined


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python orchestrator.py <path_to_eeg_file>")
        sys.exit(1)
    run_pipeline(sys.argv[1])
