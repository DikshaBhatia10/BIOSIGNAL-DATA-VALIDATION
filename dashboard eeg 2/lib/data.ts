import { pool } from './db';
import type { Check, Recording } from './types';

export async function getRecordings(): Promise<Recording[]> {
  const recs = await pool.query<Omit<Recording, 'checks'>>('SELECT * FROM recordings ORDER BY id');
  const checks = await pool.query<Check & { recording_id: number }>(
    `SELECT recording_id, check_name, raw_passed, cleaned_passed, raw_value, cleaned_value
     FROM qc_checks
     ORDER BY recording_id, array_position(
       ARRAY['flatline_check','clipping_check','noise_check','baseline_drift_check','artifact_kurtosis_check'], check_name)`
  );
  return recs.rows.map((r) => ({
    ...r,
    checks: checks.rows
      .filter((c) => c.recording_id === r.id)
      .map(({ recording_id, ...c }) => c),
  }));
}
