"""
EEG Analysis agent — core logic.

Cleans an EEG recording (filtering + ICA-based artifact removal) and saves
the cleaned file so the QC agent can re-run its checks on it (this is what
produces the "raw vs cleaned" comparison Akansha's evaluation layer needs).

Original implementation for the course project — standard MNE preprocessing
steps (bandpass filtering, ICA), not copied from any internship codebase.
"""

from __future__ import annotations

import os
import mne
from mne.preprocessing import ICA


def clean_eeg(
    file_path: str,
    output_dir: str,
    l_freq: float = 1.0,
    h_freq: float = 40.0,
    n_ica_components: int = 15,
    eog_channel: str | None = None,
) -> dict:
    """
    Bandpass-filter the recording and remove artifact components via ICA.

    If `eog_channel` is provided and present in the recording, ICA components
    correlated with it are removed automatically (standard eye-blink removal).
    Otherwise, falls back to a kurtosis heuristic to flag likely artifact
    components — less precise, but doesn't require a dedicated EOG channel.
    """
    raw = mne.io.read_raw(file_path, preload=True, verbose=False)
    raw.filter(l_freq=l_freq, h_freq=h_freq, verbose=False)

    ica = ICA(n_components=n_ica_components, random_state=42, verbose=False)
    ica.fit(raw, verbose=False)

    removed_components: list[int] = []

    if eog_channel and eog_channel in raw.ch_names:
        eog_indices, _ = ica.find_bads_eog(raw, ch_name=eog_channel, verbose=False)
        removed_components = eog_indices
    else:
        # Fallback: flag components with unusually high kurtosis (peaky, spike-like
        # signals typical of blink/muscle artifacts) rather than smooth brain rhythms.
        sources = ica.get_sources(raw).get_data()
        from scipy.stats import kurtosis

        k = kurtosis(sources, axis=1)
        threshold = k.mean() + 2 * k.std()
        removed_components = [i for i, val in enumerate(k) if val > threshold]

    ica.exclude = removed_components
    raw_clean = ica.apply(raw.copy(), verbose=False)

    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(file_path))[0]

    # Saved as BrainVision format (.vhdr + .eeg + .vmrk) — same 3-file structure
    # as the original input — rather than MNE's own .fif format, so the cleaned
    # output opens the same way the raw file does, and downstream tools/graders
    # expecting BrainVision don't need anything MNE-specific to open it.
    # Requires the `pybv` package (pip install pybv).
    from mne.export import export_raw
    out_vhdr_path = os.path.join(output_dir, f"{base}_CLEANED.vhdr")
    export_raw(out_vhdr_path, raw_clean, fmt="brainvision", overwrite=True, verbose=False)
    # This call also writes {base}_CLEANED.eeg and {base}_CLEANED.vmrk alongside
    # the .vhdr, in the same output_dir — all three are required together; don't
    # move or rename just the .vhdr without its matching .eeg/.vmrk siblings.
    out_path = out_vhdr_path

    # Fixed-length epoching as a simple usability/quality signal — no event
    # markers assumed, since this is a generic pipeline, not tied to one task.
    epochs = mne.make_fixed_length_epochs(raw_clean, duration=2.0, preload=True, verbose=False)

    return {
        "input_file": file_path,
        "cleaned_file": out_path,
        "filter_band_hz": [l_freq, h_freq],
        "ica_components_fit": n_ica_components,
        "ica_components_removed": removed_components,
        "n_components_removed": len(removed_components),
        "epochs_total": len(epochs),
    }
