"""
Autoencoder architecture for ECG beat anomaly detection.

Small, fully-connected autoencoder over fixed-length heartbeat windows
(centered on each R-peak). Trained ONLY on normal beats — it learns to
reconstruct normal heartbeat shapes; anything it reconstructs badly
(high error) is flagged as anomalous. Same core idea as the kurtosis-based
artifact check in the EEG agent — measuring "how well does this match what
we know to be normal" — just implemented as a neural net instead of a
statistical moment, because beat-shape anomalies are more naturally
captured this way than a single summary statistic.
"""

import torch
import torch.nn as nn


class ECGAutoencoder(nn.Module):
    def __init__(self, input_size: int = 200, latent_size: int = 16):
        super().__init__()
        self.input_size = input_size
        self.encoder = nn.Sequential(
            nn.Linear(input_size, 64), nn.ReLU(),
            nn.Linear(64, 32), nn.ReLU(),
            nn.Linear(32, latent_size), nn.ReLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(latent_size, 32), nn.ReLU(),
            nn.Linear(32, 64), nn.ReLU(),
            nn.Linear(64, input_size),
        )

    def forward(self, x):
        z = self.encoder(x)
        return self.decoder(z)
