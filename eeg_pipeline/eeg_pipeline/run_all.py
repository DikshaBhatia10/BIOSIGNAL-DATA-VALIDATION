"""
One command: simultaneous EDF -> split -> EEG pipeline -> ECG pipeline -> correlation layer.

Usage (from the eeg_pipeline folder, with all agent servers + MinIO running and env vars set):
    python run_all.py PN00-1.edf [--events events.csv] [--win_s 30]

Servers needed: 9001 (QC), 9002 (analysis), 9003 (ECG), 9004 (correlation), and MinIO.
"""
import argparse
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import mne

import split_edf
from storage.minio_client import upload_file as _real_upload
import orchestrator as eeg_orch
import ecg_orchestrator as ecg_orch
import correlation_orchestrator as corr_orch


def _locked(fn, lock, *a, **k):
    with lock:
        return fn(*a, **k)


def fail(step, res):
    if isinstance(res, dict) and ("error" in res or res.get("status") not in (None, "ok")):
        print(f"\n[run_all] STOPPED at {step}: {res}")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("edf")
    ap.add_argument("--events")
    ap.add_argument("--win_s", type=float, default=30)
    a = ap.parse_args()

    edf = os.path.abspath(a.edf)
    raw = mne.io.read_raw_edf(edf, preload=False, verbose=False)
    names = raw.ch_names
    ecg_ch = next((c for c in names if "EKG" in c.upper() or "ECG" in c.upper()), None)
    keep = [c for c in names if c.upper().startswith("EEG ")]
    if not ecg_ch or not keep:
        print(f"[run_all] Could not find ECG/EEG channels automatically. Channels: {names}")
        sys.exit(1)
    print(f"[run_all] ECG channel: '{ecg_ch}' | {len(keep)} EEG channels")

    print("\n[run_all] STEP 1 of 4: splitting EDF")
    out_dir = os.path.abspath("./split")
    eeg_file, ecg_file = split_edf.split(edf, ecg_ch, out_dir, keep)
    eeg_file, ecg_file = os.path.abspath(eeg_file), os.path.abspath(ecg_file)

    # Both pipelines append to the same akansha_comparison_export.csv - serialise that one write
    # so the two parallel runs can't corrupt it.
    csv_lock = threading.Lock()
    for mod in (eeg_orch, ecg_orch):
        orig = mod.build_comparison_csv
        mod.build_comparison_csv = (lambda f: (lambda *a, **k: _locked(f, csv_lock, *a, **k)))(orig)

    # Paired recording => everything goes ONLY to the correlation bucket, grouped per recording:
    #   <recording>/eeg/, <recording>/ecg/, <recording>/results/
    # (Running orchestrator.py / ecg_orchestrator.py on their own still uses the eeg / ecg buckets.)
    rec = os.path.splitext(os.path.basename(edf))[0]
    corr_bucket = corr_orch.CORR_BUCKET

    def _to_corr(sub):
        return lambda f, object_name=None, bucket=None: _real_upload(
            f, object_name=f"{rec}/{sub}/{os.path.basename(f)}", bucket=corr_bucket)

    eeg_orch.upload_file = _to_corr("eeg")
    ecg_orch.upload_file = _to_corr("ecg")
    ecg_orch.ECG_BUCKET = corr_bucket  # so its log line names the right bucket

    print("\n[run_all] STEP 2+3 of 4: EEG and ECG pipelines running SIMULTANEOUSLY")
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_eeg = pool.submit(eeg_orch.run_pipeline, eeg_file)
        f_ecg = pool.submit(ecg_orch.run_pipeline, ecg_file)
        eeg_res, ecg_res = f_eeg.result(), f_ecg.result()
    fail("EEG pipeline", eeg_res)
    fail("ECG pipeline", ecg_res)
    print("[run_all] Both pipelines finished.")

    print("\n[run_all] STEP 4 of 4: correlation layer (needs both results, so it runs after)")
    out = os.path.abspath("./outputs")
    ecg_stem = os.path.splitext(os.path.basename(ecg_file))[0]
    res = corr_orch.run_pipeline(
        eeg_res["analysis"]["cleaned_file"],
        ecg_res["qc_raw"]["cleaned_file"],
        eeg_report=os.path.join(out, "eeg_pipeline_report.json"),
        ecg_report=os.path.join(out, f"{ecg_stem}_ecg_pipeline_report.json"),
        events=a.events, win_s=a.win_s)
    fail("correlation layer", res)
    print("\n[run_all] ALL DONE. Results are in the outputs\\ folder.")


if __name__ == "__main__":
    main()