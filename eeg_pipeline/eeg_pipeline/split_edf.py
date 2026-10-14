"""
Splits ONE simultaneous recording (e.g. a CHB-MIT .edf with an ECG channel) into the two files
your existing pipelines expect:
    <stem>_eeg.vhdr (+ .vmrk, .eeg) -> BrainVision, for the EEG pipeline (orchestrator.py)
    <stem>_ecg.hea  (+ .dat)        -> WFDB, for the ECG pipeline (ecg_orchestrator.py)

Usage: python split_edf.py file.edf [--ecg_channel EKG] [--keep Fp1,Fp2,...] [--out_dir ./split]
"""
import argparse, os
import numpy as np
import mne


def split(path, ecg_channel=None, out_dir="./split", keep=None):
    raw = mne.io.read_raw_edf(path, preload=True, verbose=False)
    names = raw.ch_names
    cands = [c for c in names if c.upper() in ("ECG", "EKG")] if ecg_channel is None else [ecg_channel]
    cands = [c for c in cands if c in names]
    if not cands:
        raise RuntimeError(f"No ECG channel found in {path}. Channels: {names}. "
                           "This recording can't be used for the correlation layer - pick one that has ECG.")
    ecg_ch = cands[0]
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]

    import wfdb
    from mne.export import export_raw

    # ECG -> WFDB (.hea + .dat), the same native format the ECG agent reads and writes
    ecg = raw.get_data(picks=[ecg_ch])[0] * 1e3  # volts -> mV
    fs = raw.info["sfreq"]
    wfdb.wrsamp(record_name=f"{stem}_ecg", fs=fs, units=["mV"], sig_name=["ECG"],
                p_signal=ecg.reshape(-1, 1), fmt=["16"], write_dir=out_dir)
    ecg_path = os.path.join(out_dir, f"{stem}_ecg.hea")

    # EEG only (drop ECG + any non-EEG channels) -> BrainVision (.vhdr + .vmrk + .eeg)
    if keep:  # explicit EEG channel list (e.g. from Siena's Seizures-list-PNxx.txt)
        missing = [c for c in keep if c not in names]
        if missing:
            raise RuntimeError(f"--keep channels not found: {missing}. Available: {names}")
        raw.pick(keep)
    else:
        drop = [c for c in names if c == ecg_ch or c.upper() in ("VNS", "-", "EKG")]
        raw.drop_channels([c for c in drop if c in raw.ch_names])
    eeg_path = os.path.join(out_dir, f"{stem}_eeg.vhdr")
    export_raw(eeg_path, raw, fmt="brainvision", overwrite=True, verbose=False)
    print(f"EEG ({len(raw.ch_names)} ch) -> {eeg_path}\nECG ('{ecg_ch}', {fs:.0f} Hz) -> {ecg_path}")
    return eeg_path, ecg_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("edf"); ap.add_argument("--ecg_channel"); ap.add_argument("--out_dir", default="./split")
    ap.add_argument("--keep", help="comma-separated EEG channel names to keep (all others ignored)")
    a = ap.parse_args()
    split(a.edf, a.ecg_channel, a.out_dir, a.keep.split(",") if a.keep else None)