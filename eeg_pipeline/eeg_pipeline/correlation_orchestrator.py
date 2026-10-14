"""
Correlation-layer orchestrator. Run AFTER the EEG and ECG pipelines have finished on the SAME recording.

  1. Reads the cleaned EEG (.vhdr) and cleaned ECG (_CLEANED.csv) the two pipelines produced
  2. Pulls each pipeline's cleaned quality_score from their JSON reports (if given)
  3. Calls the correlation agent (HTTP, port 9004)
  4. Uploads report + aligned feature CSV to MinIO bucket 'correlation' (folder = recording name)

MANUAL SETUP:
  - Create MinIO bucket 'correlation' (or set MINIO_CORR_BUCKET) - not auto-created, same rule as the others
  - Start the agent:  cd correlation_agent && python -m uvicorn server:app --port 9004
  - Run:
      python correlation_orchestrator.py <cleaned_eeg.vhdr> <cleaned_ecg.csv> \
          [--eeg_report outputs/eeg_pipeline_report.json] \
          [--ecg_report outputs/<stem>_ecg_pipeline_report.json] \
          [--events events.csv] [--win_s 30] [--min_quality 0.0]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import httpx

from storage.minio_client import upload_file

CORR_AGENT_URL = "http://127.0.0.1:9004/message"
CORR_BUCKET = os.environ.get("MINIO_CORR_BUCKET", "correlation")
OUT_DIR = os.path.abspath("./outputs")
TIMEOUT_SECONDS = 3600


def _cleaned_score(report_path):
    if not report_path:
        return None
    with open(report_path, encoding="utf-8") as f:
        return json.load(f)["qc_cleaned"]["quality_score"]


def run_pipeline(eeg_file, ecg_file, eeg_report=None, ecg_report=None, events=None, win_s=30, min_quality=0.0):
    os.makedirs(OUT_DIR, exist_ok=True)
    payload = dict(eeg_file=os.path.abspath(eeg_file), ecg_file=os.path.abspath(ecg_file), output_dir=OUT_DIR,
                   win_s=win_s, step_s=win_s, events_file=os.path.abspath(events) if events else None,
                   eeg_quality=_cleaned_score(eeg_report), ecg_quality=_cleaned_score(ecg_report),
                   min_quality=min_quality)
    print("[corr_orchestrator] Running correlation agent...")
    try:
        resp = httpx.post(CORR_AGENT_URL, json=payload, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        out = resp.json()
    except Exception as e:
        return {"error": "agent_call_failed", "detail": f"{type(e).__name__}: {e}"}
    if out.get("status") != "ok":
        print(f"[corr_orchestrator] FAILED: {out.get('error')}")
        return {"error": "correlation_failed", "detail": out}
    result = out["result"]
    if result.get("status") != "ok":
        print(f"[corr_orchestrator] {result.get('status')}: {result.get('message')}")
        return result

    # Correlation results go to <recording>/results/ in the 'correlation' bucket.
    # (When run via run_all.py the cleaned EEG/ECG of the same recording are already stored in
    #  <recording>/eeg/ and <recording>/ecg/ of this bucket - one copy, no duplicates elsewhere.)
    rec = os.path.splitext(os.path.basename(eeg_file))[0].removesuffix("_CLEANED").removesuffix("_eeg")

    def siblings(path):
        return sorted(glob.glob(os.path.splitext(path)[0] + ".*"))

    plan = [(p, "results") for p in (result["report_file"], result.get("features_file")) if p]
    try:
        uploaded = [upload_file(p, object_name=f"{rec}/{sub}/{os.path.basename(p)}", bucket=CORR_BUCKET)
                    for p, sub in plan]
        print(f"[corr_orchestrator] Uploaded {len(uploaded)} files to bucket '{CORR_BUCKET}' under '{rec}/' "
              "(results/)")
        result["minio_objects"] = uploaded
    except Exception as e:
        print(f"[corr_orchestrator] MinIO upload FAILED: {e}")
        return {"error": "minio_upload_failed", "detail": str(e)}

    c = result["correlation"]
    if c["status"] == "ok":
        top = c["pairs"][0]
        print(f"[corr_orchestrator] {c['n_windows']} windows. Strongest pair: ECG {top['ecg']} vs EEG {top['eeg']} "
              f"rho={top['rho']:.2f}, p={top['p']:.3f} (Bonferroni {top['p_bonferroni']:.3f})")
    else:
        print(f"[corr_orchestrator] {c['message']}")
    for w in result.get("warnings", []):
        print(f"[corr_orchestrator] WARNING: {w}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("eeg_file"); ap.add_argument("ecg_file")
    ap.add_argument("--eeg_report"); ap.add_argument("--ecg_report"); ap.add_argument("--events")
    ap.add_argument("--win_s", type=float, default=30); ap.add_argument("--min_quality", type=float, default=0.0)
    a = ap.parse_args()
    run_pipeline(a.eeg_file, a.ecg_file, a.eeg_report, a.ecg_report, a.events, a.win_s, a.min_quality)