export type CheckName =
  | 'flatline_check'
  | 'clipping_check'
  | 'noise_check'
  | 'baseline_drift_check'
  | 'artifact_kurtosis_check';

export interface Check {
  check_name: CheckName;
  raw_passed: boolean;
  cleaned_passed: boolean;
  raw_value: number;
  cleaned_value: number;
}

export interface Recording {
  id: number;
  name: string;
  raw_score: number;
  cleaned_score: number;
  n_channels: number | null;
  sampling_rate: number | null;
  duration_sec: number | null;
  filter_low: number | null;
  filter_high: number | null;
  ica_fit: number | null;
  ica_removed: number | null;
  epochs: number | null;
  checks: Check[];
}
