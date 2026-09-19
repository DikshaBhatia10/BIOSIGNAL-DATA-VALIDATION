"""
ECG pipeline orchestrator. Same real, no-synthetic-steps flow as
orchestrator.py (EEG), adapted for the single combined ECG agent:

  1. Raw file -> ECG agent (pass 1: "raw") -> real checks + a real cleaned
     signal saved to disk as CSV
  2. Cleaned file -> uploaded to MinIO, in its own folder named after the
     source file (same convention as the EEG pipeline)
  3. Cleaned file -> ECG agent again (pass 2: "cleaned")
  4. Real Gemini summary report generated and uploaded alongside the cleaned
     file
  5. Both real check results -> appended to the SAME akansha_comparison_export.csv
     the EEG pipeline writes to, tagged signal_type="ECG" so rows from both
     signal types coexist without being confused for each other

MANUAL SETUP REQUIRED BEFORE RUNNING:
  - Train the autoencoder first (one-time, or whenever you retrain):
      cd ecg_agent
      python train_autoencoder.py --data_dir path/to/nsrdb_data
    This produces ecg_autoencoder.pt and ecg_threshold.json in ecg_agent/.
  - Start the ECG agent server:  uvicorn server:app --port 9003  (from ecg_agent/)
  - Same MinIO and GEMINI_API_KEY environment variables as the EEG pipeline —
    see eeg_pipeline_startup_commands.md. ECG uploads go to a SEPARATE MinIO
    bucket, named "ecg" by default (set MINIO_ECG_BUCKET to override) — you
    must create this bucket manually first, same rule as the EEG one.
  - Run: python ecg_orchestrator.py <path_to_real_ecg_file>
    (a WFDB record's base path/.dat/.hea, or a .csv this pipeline produced)
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

ECG_AGENT_URL = "http://127.0.0.1:9003/message"
ECG_BUCKET = os.environ.get("MINIO_ECG_BUCKET", "ecg")  # separate bucket from
# the EEG pipeline's — set MINIO_ECG_BUCKET to override. Must be created
# manually in MinIO first, same rule as the EEG bucket (see storage/minio_client.py).
OUT_DIR = os.path.abspath("./outputs")  # absolute — same reasoning as the EEG
# orchestrator: the agent server runs in a different folder, so a relative
# path here would resolve against ITS working directory, not this script's.
TIMEOUT_SECONDS = 3600


def call_agent(url: str, payload: dict) -> dict:
    try:
        resp = httpx.post(url, json=payload, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


def run_pipeline(file_path: str) -> dict:
    os.makedirs(OUT_DIR, exist_ok=True)

    print("[ecg_orchestrator] Running ECG agent on raw file...")
    raw_result = call_agent(ECG_AGENT_URL, {"file_path": file_path, "pass_label": "raw", "output_dir": OUT_DIR})
    if raw_result.get("status") != "ok":
        print(f"[ecg_orchestrator] Raw pass failed: {raw_result.get('error')}")
        return {"error": "raw_check_failed", "detail": raw_result}
    print(f"[ecg_orchestrator] Raw pass done — quality_score={raw_result['result']['quality_score']}")

    cleaned_path = raw_result["result"]["cleaned_file"]
    print(f"[ecg_orchestrator] Cleaned file at {cleaned_path}")

    print("[ecg_orchestrator] Running ECG agent on cleaned file (second pass)...")
    clean_result = call_agent(ECG_AGENT_URL, {"file_path": cleaned_path, "pass_label": "cleaned", "output_dir": OUT_DIR})
    if clean_result.get("status") != "ok":
        print(f"[ecg_orchestrator] Cleaned pass failed: {clean_result.get('error')}")
        return {"error": "cleaned_check_failed", "detail": clean_result}
    print(f"[ecg_orchestrator] Cleaned pass done — quality_score={clean_result['result']['quality_score']}")

    source_stem = os.path.splitext(os.path.basename(file_path))[0]

    print("[ecg_orchestrator] Generating Gemini summary report...")
    pre_report = {
        "input_file": file_path,
        "qc_raw": raw_result["result"],
        "qc_cleaned": clean_result["result"],
    }
    try:
        report_text = generate_report(pre_report)
        report_path = os.path.join(OUT_DIR, f"{source_stem}_gemini_report.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        print(f"[ecg_orchestrator] Gemini report saved locally to {report_path}")
    except Exception as e:
        print(f"[ecg_orchestrator] Gemini report generation FAILED (continuing anyway): {e}")
        report_path = None

    print(f"[ecg_orchestrator] Uploading cleaned CSV + report to MinIO folder '{source_stem}/'...")
    try:
        files_to_upload = [cleaned_path]
        if report_path:
            files_to_upload.append(report_path)
        uploaded_objects = []
        for f in files_to_upload:
            obj = upload_file(f, object_name=f"{source_stem}/{os.path.basename(f)}", bucket=ECG_BUCKET)
            uploaded_objects.append(obj)
        print(f"[ecg_orchestrator] Uploaded to MinIO bucket '{ECG_BUCKET}' under '{source_stem}/': {uploaded_objects}")
    except Exception as e:
        print(f"[ecg_orchestrator] MinIO upload FAILED: {e}")
        return {"error": "minio_upload_failed", "detail": str(e)}

    print("[ecg_orchestrator] Appending to Akansha comparison export...")
    csv_path = build_comparison_csv(raw_result["result"], clean_result["result"], OUT_DIR, signal_type="ECG")
    print(f"[ecg_orchestrator] Comparison CSV updated at {csv_path}")

    combined = {
        "input_file": file_path,
        "qc_raw": raw_result["result"],
        "qc_cleaned": clean_result["result"],
        "minio_folder": source_stem,
        "minio_objects": uploaded_objects,
        "gemini_report_file": report_path,
        "akansha_export": csv_path,
    }

    report_out_path = os.path.join(OUT_DIR, f"{source_stem}_ecg_pipeline_report.json")
    with open(report_out_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, default=str)
    print(f"\n[ecg_orchestrator] Combined report saved to {report_out_path}")
    print(
        f"[ecg_orchestrator] Quality score: {raw_result['result']['quality_score']} (raw) "
        f"→ {clean_result['result']['quality_score']} (cleaned)"
    )

    return combined


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ecg_orchestrator.py <path_to_ecg_file>")
        sys.exit(1)
    run_pipeline(sys.argv[1])
