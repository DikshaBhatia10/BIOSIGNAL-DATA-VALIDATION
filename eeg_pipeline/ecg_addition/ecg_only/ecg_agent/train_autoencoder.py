"""
Trains the ECG autoencoder on REAL normal heartbeats — no synthetic/simulated
data. Uses the MIT-BIH Normal Sinus Rhythm Database (confirmed normal-only
recordings, freely downloadable, no credentialing required).

MANUAL SETUP REQUIRED BEFORE RUNNING:
1. Download the MIT-BIH Normal Sinus Rhythm Database:
   https://physionet.org/content/nsrdb/1.0.0/
   Easiest: use the "Download the ZIP file" link on that page, or:
     pip install wfdb
     python -c "import wfdb; wfdb.dl_database('nsrdb', 'nsrdb_data')"
   Either way, end up with a local folder containing .dat/.hea files
   (e.g. 16265.dat, 16265.hea, ...).
2. Set NSRDB_DIR below (or pass --data_dir) to that folder.
3. Run: python train_autoencoder.py --data_dir path/to/nsrdb_data

WHAT THIS ACTUALLY DOES, no shortcuts:
- Loads each real record with wfdb
- Cleans the signal and detects REAL R-peaks with NeuroKit2
- Extracts a real fixed-length window around each detected R-peak
- Normalizes each beat (zero mean, unit variance) — standard practice so the
  network learns beat SHAPE, not amplitude, which varies by patient/lead
- Trains the autoencoder to reconstruct these real normal beats
- Computes a REAL data-driven anomaly threshold from the trained model's
  reconstruction error distribution on this same normal data (mean + 2*std)
  — not a guessed constant — and saves it alongside the model weights so
  the agent doesn't have to guess either.

Output: ecg_autoencoder.pt (model weights) and ecg_threshold.json (the
computed anomaly threshold + the window size used, so inference stays
consistent with training).
"""

from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np
import torch
import torch.nn as nn
import wfdb
import neurokit2 as nk

from model import ECGAutoencoder

WINDOW_SIZE = 200  # samples around each R-peak (100 before, 100 after) — a
# common, reasonable window for a single heartbeat at typical ECG sampling
# rates; if your dataset's sampling rate is very different from ~250-360 Hz,
# reconsider this.
HALF_WINDOW = WINDOW_SIZE // 2


def extract_beats(record_path: str) -> list[np.ndarray]:
    """Loads one real WFDB record, cleans it, detects real R-peaks, and
    extracts a normalized window around each one. Returns a list of beats
    (each a WINDOW_SIZE-length array), or an empty list if this record
    couldn't be processed (logged, not silently skipped)."""
    try:
        record = wfdb.rdrecord(record_path)
        signal = record.p_signal[:, 0]  # first channel
        fs = record.fs

        cleaned = nk.ecg_clean(signal, sampling_rate=fs)
        _, info = nk.ecg_peaks(cleaned, sampling_rate=fs)
        rpeaks = info["ECG_R_Peaks"]

        beats = []
        for peak in rpeaks:
            start, end = peak - HALF_WINDOW, peak + HALF_WINDOW
            if start < 0 or end > len(cleaned):
                continue  # real edge case — beat too close to recording start/end, skip it honestly
            beat = cleaned[start:end]
            std = beat.std()
            if std == 0:
                continue  # flat segment, not a real beat — skip rather than divide by zero
            beat_norm = (beat - beat.mean()) / std
            beats.append(beat_norm)
        return beats
    except Exception as e:
        print(f"[train] Skipping {record_path} — could not process: {e}")
        return []


def main(data_dir: str, epochs: int, output_dir: str):
    hea_files = sorted(glob.glob(os.path.join(data_dir, "*.hea")))
    if not hea_files:
        raise RuntimeError(
            f"No .hea files found in {data_dir}. Did you download the NSR "
            f"database and point --data_dir at the right folder?"
        )

    print(f"[train] Found {len(hea_files)} records. Extracting real beats...")
    all_beats: list[np.ndarray] = []
    for hea in hea_files:
        record_path = hea[:-4]  # strip .hea, wfdb wants the base path
        beats = extract_beats(record_path)
        all_beats.extend(beats)
        print(f"[train]   {os.path.basename(record_path)}: {len(beats)} beats extracted")

    if len(all_beats) < 100:
        raise RuntimeError(
            f"Only {len(all_beats)} beats extracted total — too few to train "
            f"on meaningfully. Check that your data_dir actually contains "
            f"readable ECG records."
        )

    print(f"[train] Total real normal beats: {len(all_beats)}")
    X = torch.tensor(np.array(all_beats), dtype=torch.float32)

    model = ECGAutoencoder(input_size=WINDOW_SIZE)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()

    model.train()
    for epoch in range(epochs):
        optimizer.zero_grad()
        reconstructed = model(X)
        loss = loss_fn(reconstructed, X)
        loss.backward()
        optimizer.step()
        if epoch % max(1, epochs // 10) == 0 or epoch == epochs - 1:
            print(f"[train] Epoch {epoch+1}/{epochs} — MSE loss: {loss.item():.6f}")

    # Real, data-driven threshold — not guessed — from THIS trained model's
    # actual reconstruction error on the real normal training data.
    model.eval()
    with torch.no_grad():
        reconstructed = model(X)
        per_beat_error = ((reconstructed - X) ** 2).mean(dim=1).numpy()
    threshold = float(per_beat_error.mean() + 2 * per_beat_error.std())
    print(f"[train] Computed anomaly threshold (mean + 2*std of training error): {threshold:.6f}")

    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, "ecg_autoencoder.pt")
    threshold_path = os.path.join(output_dir, "ecg_threshold.json")

    torch.save(model.state_dict(), model_path)
    with open(threshold_path, "w") as f:
        json.dump({"threshold": threshold, "window_size": WINDOW_SIZE}, f, indent=2)

    print(f"[train] Saved model to {model_path}")
    print(f"[train] Saved threshold config to {threshold_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", required=True, help="Folder containing MIT-BIH NSR .dat/.hea files")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--output_dir", default=".")
    args = parser.parse_args()
    main(args.data_dir, args.epochs, args.output_dir)
