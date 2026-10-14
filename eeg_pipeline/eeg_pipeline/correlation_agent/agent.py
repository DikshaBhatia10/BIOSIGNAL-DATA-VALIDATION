"""
Correlation agent - core logic.

Consumes the OUTPUTS of the two existing pipelines:
  - cleaned EEG  (BrainVision .vhdr from analysis_agent, or any file mne can read)
  - cleaned ECG  (2-column CSV time_sec,cleaned_signal from ecg_agent)
and asks: do heart (HR/HRV) and brain (EEG band power) features move together over time?

Optional events file (CSV: start_s,end_s,label) lets you ask the sharper question:
"do HR/HRV/EEG features differ during / before events (e.g. seizures) vs baseline?"

PRECONDITION: both signals must come from the SAME recording session, same clock, t=0 aligned
(e.g. EEG + ECG channels of one CHB-MIT EDF, split with split_edf.py). Otherwise results are meaningless.
"""
from __future__ import annotations

import csv
import json
import os

import numpy as np
from scipy import signal, stats

# Cleaned EEG is band-passed 1-40 Hz by analysis_agent, so delta starts at 1 Hz here.
BANDS = {"delta": (1, 4), "theta": (4, 8), "alpha": (8, 13), "beta": (13, 30)}
ECG_FEATS = ["hr", "rmssd", "sdnn"]


# ------------------------------------------------------------------ loading
def load_eeg(path: str):
    import mne
    raw = mne.io.read_raw(path, preload=True, verbose=False)
    data = raw.get_data(picks="eeg")
    if data.shape[0] == 0:
        raise ValueError(f"No EEG channels found in {path}")
    return data, float(raw.info["sfreq"])


def load_ecg(path: str):
    """Loads the cleaned ECG signal. The ECG agent now writes WFDB (.hea/.dat)
    rather than CSV — this reads that format by default, with CSV kept as a
    fallback for any older files still around from before that change."""
    if path.lower().endswith(".csv"):
        data = np.loadtxt(path, delimiter=",", skiprows=1)
        t, x = data[:, 0], data[:, 1]
        return x, 1.0 / float(t[1] - t[0])

    import wfdb
    base = path[:-4] if path.lower().endswith((".dat", ".hea")) else path
    record = wfdb.rdrecord(base)
    return record.p_signal[:, 0], record.fs


# ------------------------------------------------------------------ ECG
def _builtin_rpeaks(ecg, fs):
    sos = signal.butter(2, [5, 15], btype="band", fs=fs, output="sos")
    x = np.diff(signal.sosfiltfilt(sos, ecg), prepend=0) ** 2
    w = max(1, int(0.12 * fs))
    x = np.convolve(x, np.ones(w) / w, mode="same")
    pk, _ = signal.find_peaks(x, distance=int(0.3 * fs), height=0.3 * np.percentile(x, 99))
    return pk


def rpeak_times(ecg, fs):
    """R-peak times (s). Uses NeuroKit2 (same library as ecg_agent) with a built-in fallback."""
    try:
        import neurokit2 as nk
        _, info = nk.ecg_peaks(ecg, sampling_rate=fs)
        pk = np.asarray(info["ECG_R_Peaks"])
        if len(pk) < 5:
            raise RuntimeError("too few peaks")
    except Exception:
        pk = _builtin_rpeaks(ecg, fs)
    return pk / fs


def ecg_features(peaks_t, t0, t1):
    rr = np.diff(peaks_t[(peaks_t >= t0) & (peaks_t < t1)])
    rr = rr[(rr > 0.3) & (rr < 2.0)]
    if len(rr) < 5:
        return None
    return dict(hr=60.0 / rr.mean(), sdnn=rr.std(ddof=1) * 1000,
                rmssd=float(np.sqrt(np.mean(np.diff(rr) ** 2)) * 1000))


# ------------------------------------------------------------------ EEG
def eeg_features(eeg, fs, t0, t1):
    seg = eeg[:, int(t0 * fs):int(t1 * fs)]
    f, p = signal.welch(seg, fs=fs, nperseg=min(seg.shape[1], int(4 * fs)), axis=-1)
    tot = p[:, (f >= 1) & (f <= 30)].sum(-1)
    return {b: float(np.mean(p[:, (f >= lo) & (f < hi)].sum(-1) / tot)) for b, (lo, hi) in BANDS.items()}


def eeg_window_bad_mask(eeg, fs, starts, win_s):
    """Local window-level QC (the QC agent only scores whole files).
    A window is bad if >30% of channels are flat or >5x their typical amplitude."""
    stds = np.array([[eeg[c, int(t * fs):int((t + win_s) * fs)].std() for t in starts]
                     for c in range(eeg.shape[0])])
    med = np.median(stds, axis=1, keepdims=True) + 1e-30
    abnormal = (stds > 5 * med) | (stds < 0.1 * med)
    return abnormal.mean(axis=0) > 0.3


# ------------------------------------------------------------------ statistics
def _perm_p(x, y, n_perm, seed=0):
    """Spearman rho + two-sided p from circular shifts (valid under autocorrelation)."""
    rng = np.random.default_rng(seed)
    obs = stats.spearmanr(x, y)[0]
    n, lo = len(x), max(2, len(x) // 10)
    null = np.array([stats.spearmanr(x, np.roll(y, rng.integers(lo, n - lo)))[0] for _ in range(n_perm)])
    return float(obs), float((np.sum(np.abs(null) >= abs(obs)) + 1) / (n_perm + 1))


def _lag_scan(x, y, max_lag):
    out = {}
    for lag in range(-max_lag, max_lag + 1):
        a, b = (x[lag:], y[:len(y) - lag]) if lag >= 0 else (x[:lag], y[-lag:])
        if len(a) >= 8:
            out[lag] = float(stats.spearmanr(a, b)[0])
    return out


def correlate(rows, max_lag=3, n_perm=1000, min_windows=15):
    if len(rows) < min_windows:
        return dict(status="insufficient_data", n_windows=len(rows),
                    message=f"Need >= {min_windows} clean windows, got {len(rows)}.")
    pairs, n_tests = [], len(ECG_FEATS) * len(BANDS)
    for ef in ECG_FEATS:
        x = np.array([r[ef] for r in rows])
        for bf in BANDS:
            y = np.array([r[bf] for r in rows])
            rho, p = _perm_p(x, y, n_perm)
            lags = _lag_scan(x, y, max_lag)
            best = max(lags, key=lambda k: abs(lags[k]))
            pairs.append(dict(ecg=ef, eeg=bf, rho=rho, p=p, p_bonferroni=min(1.0, p * n_tests),
                              best_lag_windows=best, best_lag_rho=lags[best]))
    pairs.sort(key=lambda d: d["p"])
    return dict(status="ok", n_windows=len(rows), n_tests=n_tests, pairs=pairs)


# ------------------------------------------------------------------ events (optional)
def load_events(path):
    with open(path, newline="") as f:
        return [(float(r["start_s"]), float(r["end_s"]), r.get("label", "event")) for r in csv.DictReader(f)]


def label_windows(rows, events, pre_s=300):
    for r in rows:
        lab = "baseline"
        for s, e, _ in events:
            if s < r["t_end"] and e > r["t_start"]:
                lab = "event"; break
            if s - pre_s <= r["t_start"] < s:
                lab = "pre_event"
        r["label"] = lab
    return rows


def event_comparison(rows, min_n=3):
    base = [r for r in rows if r["label"] == "baseline"]
    out = {"n_baseline": len(base), "comparisons": []}
    for grp in ("event", "pre_event"):
        g = [r for r in rows if r["label"] == grp]
        out[f"n_{grp}"] = len(g)
        if len(g) < min_n or len(base) < min_n:
            out["comparisons"].append(dict(group=grp, status="insufficient_windows"))
            continue
        for feat in ECG_FEATS + list(BANDS):
            a, b = np.array([r[feat] for r in g]), np.array([r[feat] for r in base])
            u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
            out["comparisons"].append(dict(group=grp, feature=feat, median_group=float(np.median(a)),
                                           median_baseline=float(np.median(b)), p=float(p)))
    return out


# ------------------------------------------------------------------ entry point
def run_correlation(eeg_file, ecg_file, output_dir, out_prefix=None, win_s=30, step_s=30,
                    events_file=None, eeg_quality=None, ecg_quality=None, min_quality=0.0, n_perm=1000):
    os.makedirs(output_dir, exist_ok=True)
    prefix = out_prefix or os.path.splitext(os.path.basename(eeg_file))[0]
    warnings = []

    # Gate on file-level scores from the existing agents (default off: their thresholds are untuned).
    for name, q in (("EEG", eeg_quality), ("ECG", ecg_quality)):
        if q is not None and q < min_quality:
            return dict(status="skipped_low_quality",
                        message=f"{name} cleaned quality_score {q} < min_quality {min_quality}")

    eeg, fs_e = load_eeg(eeg_file)
    ecg, fs_c = load_ecg(ecg_file)
    dur_e, dur_c = eeg.shape[1] / fs_e, len(ecg) / fs_c
    common = min(dur_e, dur_c)
    if abs(dur_e - dur_c) > 2.0:
        warnings.append(f"EEG ({dur_e:.1f}s) and ECG ({dur_c:.1f}s) durations differ by >2s - "
                        "confirm both came from the same recording with t=0 aligned.")

    peaks = rpeak_times(ecg, fs_c)
    starts = np.arange(0, common - win_s + 1e-9, step_s)
    bad = eeg_window_bad_mask(eeg, fs_e, starts, win_s)

    rows, dropped_eeg, dropped_ecg = [], int(bad.sum()), 0
    for t0, is_bad in zip(starts, bad):
        if is_bad:
            continue
        ef = ecg_features(peaks, t0, t0 + win_s)
        if ef is None:
            dropped_ecg += 1
            continue
        row = dict(t_start=float(t0), t_end=float(t0 + win_s), **ef, **eeg_features(eeg, fs_e, t0, t0 + win_s))
        rows.append(row)

    report = dict(
        eeg_file=eeg_file, ecg_file=ecg_file, win_s=win_s, step_s=step_s,
        qc=dict(duration_eeg_s=round(dur_e, 2), duration_ecg_s=round(dur_c, 2), n_windows_total=len(starts),
                dropped_bad_eeg=dropped_eeg, dropped_unusable_ecg=dropped_ecg, n_rpeaks=int(len(peaks)),
                eeg_cleaned_quality_score=eeg_quality, ecg_cleaned_quality_score=ecg_quality),
        warnings=warnings,
        correlation=correlate(rows, n_perm=n_perm),
        notes=["Spearman rho; p from circular-shift permutation test at lag 0; Bonferroni across all pairs.",
               "Lag scan is exploratory and uncorrected. Association within one session, not a clinical finding."],
    )
    if events_file:
        rows = label_windows(rows, load_events(events_file))
        report["event_analysis"] = event_comparison(rows)

    rep_path = os.path.join(output_dir, f"{prefix}_correlation_report.json")
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    feat_path = None
    if rows:
        feat_path = os.path.join(output_dir, f"{prefix}_correlation_features.csv")
        with open(feat_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
    report.update(status="ok", report_file=rep_path, features_file=feat_path)
    return report