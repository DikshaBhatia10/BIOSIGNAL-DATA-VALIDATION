# EEG Validation Pipeline — Setup & Run

Real pipeline: raw EEG file → QC agent (raw pass) → analysis agent (filter + ICA
clean) → cleaned file uploaded to MinIO → QC agent again (cleaned pass) →
raw-vs-cleaned comparison exported for Akansha's Power BI evaluation.

No synthetic/mock data anywhere in this code — every step operates on the
actual file you point it at, and every result written out (QC scores, the
cleaned .fif file, the MinIO object, the comparison CSV) is real output from
that run, not a placeholder.

## 1. Install dependencies
```
pip install -r requirements.txt
```

## 2. Set up MinIO
- Have a MinIO server running and reachable.
- Create the bucket manually (default name: `eeg-pipeline`) — this code
  does not auto-create buckets, on purpose (see comments in
  `storage/minio_client.py`).
- Set these environment variables in your shell before running anything:
  ```
  export MINIO_ENDPOINT=localhost:9000
  export MINIO_ACCESS_KEY=your_access_key
  export MINIO_SECRET_KEY=your_secret_key
  export MINIO_BUCKET=eeg-pipeline
  export MINIO_SECURE=false
  ```

## 3. Start both agent servers (separate terminals)
```
cd qc_agent && uvicorn server:app --port 9001
cd analysis_agent && uvicorn server:app --port 9002
```
Check both are up: `curl http://127.0.0.1:9001/health` and `:9002/health`.

## 4. Run the orchestrator on a real EEG file
```
python orchestrator.py /path/to/your/real_recording.vhdr
```
(Any format `mne.io.read_raw` supports — .vhdr, .edf, .fif, etc.)

## 5. Outputs, all real
- `outputs/<name>_cleaned_raw.fif` — the actual cleaned recording
- MinIO bucket `eeg-pipeline`, object `cleaned/<name>_cleaned_raw.fif` — same
  file, in storage
- `outputs/eeg_pipeline_report.json` — full combined result of this run
- `outputs/akansha_comparison_export.csv` — appends one row per QC check for
  this file; open directly in Power BI. Running the pipeline on more files
  appends more rows to the same CSV, building up a real dataset over time
  rather than one-off snapshots.

## What still needs a manual decision from you
- `qc_agent/agent.py` — the `noise_check` and `baseline_drift_check`
  thresholds are placeholders (see inline comments) and need tuning against
  a few of your actual recordings before the pass/fail results mean anything.
- `analysis_agent/agent.py` — if your recordings have a dedicated EOG
  (eye-movement) channel, pass its name as `eog_channel` for more accurate
  ICA artifact rejection; otherwise it falls back to a kurtosis heuristic,
  which is real but less precise.
- Transport layer note: the two servers use plain FastAPI/HTTP rather than
  the exact `a2a-sdk` server classes your CDAC Orchestrator.py's *client*
  code expects, since I can't verify that package's server-side API for
  your installed version without your environment. The message contract
  (POST a file path, get JSON back) mirrors the same interaction pattern —
  swap the transport for the real SDK's server classes if you have them
  working, the `agent.py` logic in each folder doesn't need to change.
