-- EEG pipeline QC data (from eeg_pipeline_report.json + akansha_comparison_export.csv)
DROP TABLE IF EXISTS qc_checks;
DROP TABLE IF EXISTS recordings;

CREATE TABLE recordings (
  id             INTEGER PRIMARY KEY,
  name           TEXT UNIQUE NOT NULL,
  raw_score      DOUBLE PRECISION NOT NULL,
  cleaned_score  DOUBLE PRECISION NOT NULL,
  n_channels     INTEGER,
  sampling_rate  DOUBLE PRECISION,
  duration_sec   DOUBLE PRECISION,
  filter_low     DOUBLE PRECISION,
  filter_high    DOUBLE PRECISION,
  ica_fit        INTEGER,
  ica_removed    INTEGER,
  epochs         INTEGER
);

CREATE TABLE qc_checks (
  id             SERIAL PRIMARY KEY,
  recording_id   INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
  check_name     TEXT NOT NULL,
  raw_passed     BOOLEAN NOT NULL,
  cleaned_passed BOOLEAN NOT NULL,
  raw_value      DOUBLE PRECISION NOT NULL,
  cleaned_value  DOUBLE PRECISION NOT NULL,
  UNIQUE (recording_id, check_name)
);

INSERT INTO recordings (id, name, raw_score, cleaned_score, n_channels, sampling_rate, duration_sec, filter_low, filter_high, ica_fit, ica_removed, epochs) VALUES
  (1, '10_Gratification000004.vhdr', 0.6, 1.0, 32, 500, 192.64, 1, 40, 15, 1, 96),
  (2, 'S001R01.edf',                 0.8, 1.0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
  (3, 'S001R01_CLEANED.vhdr',        1.0, 1.0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
  (4, 'S017R10.edf',                 0.6, 1.0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
  (5, 'S017R14.edf',                 0.6, 1.0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);

-- flatline/clipping value = number of flagged channels; noise = high/low band ratio;
-- baseline drift = drift power; kurtosis = mean absolute kurtosis
INSERT INTO qc_checks (recording_id, check_name, raw_passed, cleaned_passed, raw_value, cleaned_value) VALUES
  (1, 'flatline_check',          true,  true, 0, 0),
  (1, 'clipping_check',          true,  true, 0, 0),
  (1, 'noise_check',             false, true, 0.8496, 0.0546),
  (1, 'baseline_drift_check',    false, true, 1.404402815924549e-09, 1.542220529113053e-11),
  (1, 'artifact_kurtosis_check', true,  true, 1.5134, 2.0634),
  (2, 'flatline_check',          true,  true, 0, 0),
  (2, 'clipping_check',          true,  true, 0, 0),
  (2, 'noise_check',             true,  true, 0.0343, 0.0076),
  (2, 'baseline_drift_check',    false, true, 1.38e-09, 5.23e-11),
  (2, 'artifact_kurtosis_check', true,  true, 2.4736, 0.5004),
  (3, 'flatline_check',          true,  true, 0, 0),
  (3, 'clipping_check',          true,  true, 0, 0),
  (3, 'noise_check',             true,  true, 0.0076, 0.0059),
  (3, 'baseline_drift_check',    true,  true, 5.23e-11, 7.78e-12),
  (3, 'artifact_kurtosis_check', true,  true, 0.5004, 0.4235),
  (4, 'flatline_check',          true,  true, 0, 0),
  (4, 'clipping_check',          true,  true, 0, 0),
  (4, 'noise_check',             false, true, 1.1785, 0.0268),
  (4, 'baseline_drift_check',    false, true, 6.90e-09, 2.84e-10),
  (4, 'artifact_kurtosis_check', true,  true, 0.9740, 2.5572),
  (5, 'flatline_check',          true,  true, 0, 0),
  (5, 'clipping_check',          true,  true, 0, 0),
  (5, 'noise_check',             false, true, 0.6651, 0.0326),
  (5, 'baseline_drift_check',    false, true, 8.00e-09, 2.95e-10),
  (5, 'artifact_kurtosis_check', true,  true, 1.0559, 1.5064);
