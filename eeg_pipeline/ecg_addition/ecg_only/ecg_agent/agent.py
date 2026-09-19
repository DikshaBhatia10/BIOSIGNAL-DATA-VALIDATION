"""
ECG signal-quality agent — core logic.

Same role as qc_agent/agent.py plays for EEG, but for ECG, and combining
cleaning + detection into one module (matching how this was described in
the synopsis) rather than EEG's two-service split. Outputs the SAME shape
of result (a `checks` dict with pass/fail per check, plus `quality_score`)
as the EEG QC agent, on purpose — that consistency is what lets the
correlation layer and Akansha's export treat both signal types the same
way without special-casing either one.

Original implementation for the course project — uses NeuroKit2 (a public,
open-source library) for cleaning and R-peak detection, and the custom
autoencoder in model.py (trained by train_autoencoder.py on real MIT-BIH
data) for anomaly detection. Not copied from any internship codebase.
"""

from __future__ import annotations

import os
import json

import numpy as np
import torch
import wfdb
import neurokit2 as nk

from model import ECGAutoencoder

_MODEL_CACHE: dict = {}  # loaded once per server process, not per-request


def _load_model_and_threshold(model_dir: str):
    """Loads the trained autoencoder + its data-driven threshold once, and
    caches them — re-loading from disk on every request would be wasteful
    and pointless, since nothing about the model changes between calls."""
    if "model" in _MODEL_CACHE:
        return _MODEL_CACHE["model"], _MODEL_CACHE["threshold"], _MODEL_CACHE["window_size"]

    model_path = os.path.join(model_dir, "ecg_autoencoder.pt")
    threshold_path = os.path.join(model_dir, "ecg_threshold.json")

    if not os.path.exists(model_path) or not os.path.exists(threshold_path):
        raise RuntimeError(
            f"Trained model not found in {model_dir}. Run train_autoencoder.py "
            f"first — this agent does not fall back to an untrained model."
        )

    with open(threshold_path) as f:
        cfg = json.load(f)

    model = ECGAutoencoder(input_size=cfg["window_size"])
    model.load_state_dict(torch.load(model_path, map_location="cpu"))
    model.eval()

    _MODEL_CACHE["model"] = model
    _MODEL_CACHE["threshold"] = cfg["threshold"]
    _MODEL_CACHE["window_size"] = cfg["window_size"]
    return model, cfg["threshold"], cfg["window_size"]


def _load_ecg(file_path: str):
    """Loads a real ECG recording. Supports WFDB (.dat/.hea, e.g. MIT-BIH
    format) via the file's base path (no extension), and plain 2-column
    CSV (time_sec, signal) for files this pipeline itself produced."""
    if file_path.lower().endswith(".csv"):
        data = np.loadtxt(file_path, delimiter=",", skiprows=1)
        times = data[:, 0]
        signal = data[:, 1]
        fs = 1.0 / (times[1] - times[0]) if len(times) > 1 else 250.0
        return signal, fs

    base = file_path[:-4] if file_path.lower().endswith((".dat", ".hea")) else file_path
    record = wfdb.rdrecord(base)
    return record.p_signal[:, 0], record.fs


def _flatline_check(signal: np.ndarray, std_threshold: float = 1e-4) -> dict:
    std = float(signal.std())
    return {"passed": std > std_threshold, "signal_std": round(std, 6)}


def _clipping_check(signal: np.ndarray, clip_fraction_threshold: float = 0.01) -> dict:
    lo, hi = signal.min(), signal.max()
    if hi - lo == 0:
        return {"passed": False, "clipped_fraction": 1.0}
    at_extreme = float(np.mean((signal <= lo + 1e-12) | (signal >= hi - 1e-12)))
    return {"passed": at_extreme <= clip_fraction_threshold, "clipped_fraction": round(at_extreme, 4)}


def run_check(file_path: str, model_dir: str, pass_label: str = "raw") -> dict:
    """
    Runs the full ECG check + (on the raw pass) cleaning pipeline.

    pass_label: "raw" or "cleaned" — same convention as the EEG QC agent,
    so the orchestrator/Akansha's export can tell passes apart the same way.
    """
    signal, fs = _load_ecg(file_path)

    flatline = _flatline_check(signal)
    clipping = _clipping_check(signal)

    # NeuroKit2 cleaning (baseline wander + noise removal) — this is the
    # "cleaning" half of this agent's job, same role as EEG's filter+ICA step.
    cleaned = nk.ecg_clean(signal, sampling_rate=fs)

    # R-peak detection — the basis for heart-rate and beat-level checks below.
    _, info = nk.ecg_peaks(cleaned, sampling_rate=fs)
    rpeaks = info["ECG_R_Peaks"]

    n_beats = len(rpeaks)
    duration_sec = len(signal) / fs
    implied_hr = (n_beats / duration_sec) * 60 if duration_sec > 0 else 0

    r_peak_check = {
        # 30-220 bpm is a generous physiologically-plausible range — this is
        # a sanity check that peak detection found something real, not a
        # clinical judgment about what's a "normal" heart rate (tachycardia
        # from a real event, e.g. ictal tachycardia, should still pass this).
        "passed": 30 <= implied_hr <= 220 and n_beats >= 3,
        "n_beats_detected": int(n_beats),
        "implied_heart_rate_bpm": round(implied_hr, 1),
    }

    # NeuroKit2's built-in signal quality index (template-matching against
    # the average QRS shape) — real, established method, not something we
    # invented. NOTE: exact function signature can vary slightly across
    # NeuroKit2 versions; if this errors for your installed version, check
    # https://neurokit2.readthedocs.io for the current ecg_quality() signature.
    try:
        quality_index = nk.ecg_quality(cleaned, rpeaks=rpeaks, sampling_rate=fs)
        mean_quality = float(np.mean(quality_index))
    except Exception as e:
        mean_quality = None
        print(f"[ecg_agent] nk.ecg_quality failed ({e}); skipping that sub-metric")

    quality_check = {
        "passed": (mean_quality is not None and mean_quality > 0.5),
        "mean_signal_quality_index": round(mean_quality, 4) if mean_quality is not None else None,
    }

    # Autoencoder anomaly detection — the real ML component. Extracts a
    # window around each detected beat, scores it against the model trained
    # by train_autoencoder.py on real normal beats, and flags what fraction
    # of beats in THIS recording reconstruct badly (i.e. don't look like the
    # normal beats the model learned from).
    model, threshold, window_size = _load_model_and_threshold(model_dir)
    half = window_size // 2
    beat_windows = []
    for peak in rpeaks:
        start, end = peak - half, peak + half
        if start < 0 or end > len(cleaned):
            continue
        beat = cleaned[start:end]
        std = beat.std()
        if std == 0:
            continue
        beat_windows.append((beat - beat.mean()) / std)

    if beat_windows:
        X = torch.tensor(np.array(beat_windows), dtype=torch.float32)
        with torch.no_grad():
            reconstructed = model(X)
            errors = ((reconstructed - X) ** 2).mean(dim=1).numpy()
        anomalous_fraction = float(np.mean(errors > threshold))
    else:
        anomalous_fraction = 1.0  # no usable beats extracted — treat as fully anomalous, not silently 0

    autoencoder_check = {
        # <20% anomalous beats passes — a threshold you should revisit once
        # you've run this on a few real files, same as every other threshold
        # in this pipeline.
        "passed": anomalous_fraction < 0.2,
        "anomalous_beat_fraction": round(anomalous_fraction, 4),
        "beats_scored": len(beat_windows),
    }

    checks = {
        "flatline_check": flatline,
        "clipping_check": clipping,
        "r_peak_detection_check": r_peak_check,
        "signal_quality_index_check": quality_check,
        "autoencoder_anomaly_check": autoencoder_check,
    }
    checks_passed = sum(1 for c in checks.values() if c["passed"])

    result = {
        "pass_label": pass_label,
        "file": file_path,
        "sampling_rate": fs,
        "duration_sec": round(duration_sec, 2),
        "checks": checks,
        "checks_passed": checks_passed,
        "checks_total": len(checks),
        "quality_score": round(checks_passed / len(checks), 3),
    }

    if pass_label == "raw":
        result["cleaned_signal"] = cleaned  # returned only for the caller to
        # optionally save — not included in the JSON result sent back over
        # HTTP (see server.py), since it's a large array, not metadata.

    return result


def save_cleaned_csv(cleaned_signal: np.ndarray, fs: float, output_dir: str, base_name: str) -> str:
    """Saves the cleaned signal as a simple, clearly-labeled 2-column CSV
    (time_sec, cleaned_signal). NOTE: this is a simplification — MIT-BIH's
    native WFDB format could be written back out instead (via wfdb.wrsamp)
    for full consistency with the input format, the way the EEG agent
    round-trips BrainVision. CSV is used here to keep this agent's first
    version simple; upgrading to WFDB output is a reasonable next step if
    format consistency with the original ECG files matters for your report."""
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{base_name}_CLEANED.csv")
    times = np.arange(len(cleaned_signal)) / fs
    header = "time_sec,cleaned_signal"
    np.savetxt(out_path, np.column_stack([times, cleaned_signal]), delimiter=",", header=header, comments="")
    return out_path
