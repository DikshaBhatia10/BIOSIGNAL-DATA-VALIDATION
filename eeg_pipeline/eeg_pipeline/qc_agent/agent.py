"""
EEG Signal-Quality-Check (QC) agent — core logic.

Loads a raw EEG recording and runs a set of independent quality checks,
returning a structured JSON-able result. Designed to be called twice by
the orchestrator: once on the raw file, once on the cleaned output from
the analysis agent, so their results can be compared (retention rate,
per-check pass-rate improvement, etc.).

This is an original implementation for the course project — it is not
copied from any internship codebase, though it follows standard,
well-documented EEG QC practices (flatline/clipping/noise/drift checks
are common techniques in EEG preprocessing literature, not proprietary).
"""

from __future__ import annotations

import numpy as np
import mne


def _flatline_channels(raw: mne.io.BaseRaw, std_threshold: float = 1e-7) -> list[str]:
    """Channels whose signal barely varies — likely a dead/disconnected electrode."""
    data = raw.get_data()
    stds = data.std(axis=1)
    return [ch for ch, s in zip(raw.ch_names, stds) if s < std_threshold]


def _clipping_channels(raw: mne.io.BaseRaw, clip_fraction_threshold: float = 0.01) -> list[str]:
    """Channels where a suspicious fraction of samples sit at the signal's min/max —
    a sign the amplifier saturated (clipped) rather than recorded real signal."""
    data = raw.get_data()
    flagged = []
    for ch, series in zip(raw.ch_names, data):
        lo, hi = series.min(), series.max()
        if hi - lo == 0:
            continue
        at_extreme = np.mean((series <= lo + 1e-12) | (series >= hi - 1e-12))
        if at_extreme > clip_fraction_threshold:
            flagged.append(ch)
    return flagged


def _noise_score(raw: mne.io.BaseRaw, low_band=(1, 40), high_band=(40, 100)) -> float:
    """Ratio of high-frequency (likely noise/muscle) power to the physiological band.
    Higher = noisier. Requires a sampling rate that supports the high band."""
    nyquist = raw.info["sfreq"] / 2
    if high_band[1] >= nyquist:
        high_band = (high_band[0], max(high_band[0] + 1, nyquist - 1))

    psd_low = raw.compute_psd(fmin=low_band[0], fmax=low_band[1], verbose=False)
    psd_high = raw.compute_psd(fmin=high_band[0], fmax=high_band[1], verbose=False)

    low_power = psd_low.get_data().mean()
    high_power = psd_high.get_data().mean()
    if low_power <= 0:
        return float("inf")
    return float(high_power / low_power)


def _baseline_drift_score(raw: mne.io.BaseRaw, drift_band=(0.0, 0.5)) -> float:
    """Power in the very-low-frequency band — high values indicate slow baseline
    wander rather than genuine brain activity."""
    fmin = max(drift_band[0], 0.1)  # MNE psd needs fmin > 0
    psd = raw.compute_psd(fmin=fmin, fmax=drift_band[1], verbose=False)
    return float(psd.get_data().mean())


def _artifact_kurtosis_score(raw: mne.io.BaseRaw) -> float:
    """Mean absolute kurtosis across channels — a measure of 'spikiness' in the
    signal. Blink/muscle artifacts are peaky/non-Gaussian and drive kurtosis up;
    clean brain rhythms are closer to Gaussian. This is the same property ICA
    component rejection targets (see analysis_agent's kurtosis-based fallback),
    so unlike the noise/drift checks above — which mostly just reflect the
    bandpass filter's own frequency cutoffs — this one actually reflects
    whether artifact-like signal content was removed, not just filtered."""
    from scipy.stats import kurtosis
    data = raw.get_data()
    k = kurtosis(data, axis=1)
    return float(np.mean(np.abs(k)))


def run_qc(file_path: str, pass_label: str = "raw") -> dict:
    """
    Run the full QC check suite on an EEG file.

    pass_label: "raw" or "cleaned" — tags this run so the orchestrator/Akansha's
    evaluation layer can tell which pass a given result belongs to.
    """
    raw = mne.io.read_raw(file_path, preload=True, verbose=False)

    flatline = _flatline_channels(raw)
    clipping = _clipping_channels(raw)
    noise = _noise_score(raw)
    drift = _baseline_drift_score(raw)
    artifact_kurtosis = _artifact_kurtosis_score(raw)

    n_channels = len(raw.ch_names)
    bad_channel_fraction = len(set(flatline + clipping)) / max(n_channels, 1)

    checks = {
        "flatline_check": {
            "passed": len(flatline) == 0,
            "flagged_channels": flatline,
        },
        "clipping_check": {
            "passed": len(clipping) == 0,
            "flagged_channels": clipping,
        },
        "noise_check": {
            "passed": noise < 0.5,
            "high_to_low_band_ratio": round(noise, 4),
        },
        "baseline_drift_check": {
            "passed": drift < 1e-9,  # threshold is data/unit dependent — tune against your dataset
            "drift_power": drift,
        },
        "artifact_kurtosis_check": {
            "passed": artifact_kurtosis < 5.0,  # >5 is a common rule-of-thumb cutoff for
            # non-Gaussian/artifact-heavy channels — tune against your own data too
            "mean_abs_kurtosis": round(artifact_kurtosis, 4),
        },
    }

    checks_passed = sum(1 for c in checks.values() if c["passed"])
    quality_score = round(checks_passed / len(checks), 3)

    return {
        "pass_label": pass_label,
        "file": file_path,
        "n_channels": n_channels,
        "sampling_rate": raw.info["sfreq"],
        "duration_sec": round(raw.times[-1], 2),
        "bad_channel_fraction": round(bad_channel_fraction, 4),
        "checks": checks,
        "checks_passed": checks_passed,
        "checks_total": len(checks),
        "quality_score": quality_score,
    }
