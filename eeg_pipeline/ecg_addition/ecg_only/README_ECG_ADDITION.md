# ECG Addition — Drop-In Instructions

This is ONLY the new ECG pieces, meant to be added into your existing,
already-working `eeg_pipeline` folder — not a replacement for it.

## What's in this zip and where it goes

- `ecg_agent/` (whole folder, new) → copy into your existing `eeg_pipeline/`
  folder, so you end up with `eeg_pipeline\ecg_agent\...`
- `ecg_orchestrator.py` (new) → copy into `eeg_pipeline\` (same level as your
  existing `orchestrator.py`)
- `akansha_export.py` (UPDATED — replaces your existing one) → this now
  supports a `signal_type` column so EEG and ECG rows can share one CSV.
  Your existing EEG orchestrator.py still works with it unchanged.
- `requirements.txt` (UPDATED — replaces your existing one) → adds
  neurokit2, torch, and wfdb for ECG. Your existing EEG dependencies
  (mne, pybv, etc.) are still in here too, nothing removed.

## Steps

1. Copy `ecg_agent/` into your existing `eeg_pipeline` folder
2. Copy `ecg_orchestrator.py` into your existing `eeg_pipeline` folder
3. Replace your existing `akansha_export.py` with the one in this zip
4. Replace your existing `requirements.txt` with the one in this zip
5. Install the new dependencies:
   ```
   pip install neurokit2 torch wfdb
   ```
6. Train the ECG autoencoder (one-time):
   ```
   cd eeg_pipeline\ecg_agent
   python train_autoencoder.py --data_dir path\to\nsrdb_data
   ```
7. Create a new MinIO bucket named `ecg` (your existing `eeg-pipeline` bucket
   is untouched — ECG uploads go to this separate one)
8. Start the ECG agent server (new terminal):
   ```
   cd eeg_pipeline\ecg_agent
   python -m uvicorn server:app --port 9003
   ```
9. Run it, same env vars as before, from your usual terminal:
   ```
   cd eeg_pipeline
   python ecg_orchestrator.py path\to\real_ecg_file
   ```

Your existing EEG setup (qc_agent, analysis_agent, orchestrator.py) is
untouched by any of this — same commands, same ports, same bucket, as before.
