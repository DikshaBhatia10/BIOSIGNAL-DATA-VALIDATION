'use client';
import { useMemo, useState } from 'react';
import { LineChart, PassBars } from './Charts';
import type { CheckName, Recording } from '@/lib/types';

const LABELS: Record<CheckName, string> = {
  flatline_check: 'Flatline',
  clipping_check: 'Clipping',
  noise_check: 'Noise ratio',
  baseline_drift_check: 'Baseline drift',
  artifact_kurtosis_check: 'Artifact kurtosis',
};
const ORDER = Object.keys(LABELS) as CheckName[];
const RED = '#ff2a2a';
const GREY = '#8a8d94';

function reading(name: CheckName, v: number) {
  if (name === 'flatline_check' || name === 'clipping_check') return `${v} flagged`;
  if (name === 'baseline_drift_check') return v.toExponential(2);
  if (name === 'noise_check') return `ratio ${v.toFixed(4)}`;
  return `kurt ${v.toFixed(4)}`;
}
const avg = (a: number[]) => a.reduce((s, v) => s + v, 0) / a.length;
const get = (r: Recording, n: CheckName) => r.checks.find((c) => c.check_name === n)!;

export default function Dashboard({ recordings }: { recordings: Recording[] }) {
  const [sel, setSel] = useState(0);
  const rec = recordings[sel];

  const s = useMemo(() => {
    const all = recordings.flatMap((r) => r.checks);
    const rawAvg = avg(recordings.map((r) => r.raw_score));
    const cleanAvg = avg(recordings.map((r) => r.cleaned_score));
    return {
      rawAvg, cleanAvg,
      uplift: ((cleanAvg - rawAvg) / rawAvg) * 100,
      rawPass: all.filter((c) => c.raw_passed).length,
      cleanPass: all.filter((c) => c.cleaned_passed).length,
      total: all.length,
      bars: ORDER.map((n) => ({
        label: LABELS[n],
        raw: recordings.filter((r) => get(r, n).raw_passed).length,
        cleaned: recordings.filter((r) => get(r, n).cleaned_passed).length,
        total: recordings.length,
      })),
      noiseRaw: recordings.map((r) => get(r, 'noise_check').raw_value),
      noiseClean: recordings.map((r) => get(r, 'noise_check').cleaned_value),
    };
  }, [recordings]);

  const short = recordings.map((_, i) => `R${i + 1}`);
  const names = recordings.map((r, i) => `R${i + 1} · ${r.name}`);
  const noiseMax = Math.ceil(Math.max(...s.noiseRaw) * 1.1 * 10) / 10;

  return (
    <main className="wrap">
      <p className="kicker">BIOSIGNAL-DATA-VALIDATION · EEG PIPELINE</p>
      <h1>QC <span className="red">Dashboard</span></h1>
      <p className="sub">
        Automated quality checks on {recordings.length} EEG recordings, before and after filtering and ICA artifact removal.
        Live from PostgreSQL.
      </p>

      <div className="grid kpis">
        <div className="panel kpi"><div className="label">RECORDINGS</div><div className="num">{recordings.length}</div><div className="note">processed by the pipeline</div></div>
        <div className="panel kpi"><div className="label">AVG SCORE · RAW</div><div className="num">{s.rawAvg.toFixed(2)}</div><div className="note">before cleaning</div></div>
        <div className="panel kpi"><div className="label">AVG SCORE · CLEANED</div><div className="num">{s.cleanAvg.toFixed(2)}</div><div className="note">after cleaning</div></div>
        <div className="panel kpi"><div className="label">UPLIFT</div><div className="num">+{s.uplift.toFixed(0)}%</div><div className="note">average score gain</div></div>
        <div className="panel kpi"><div className="label">CHECKS PASSED</div><div className="num">{s.rawPass}→{s.cleanPass}</div><div className="note">of {s.total} · raw → cleaned</div></div>
      </div>

      <div className="grid two">
        <div className="panel">
          <p className="kicker">QUALITY SCORE</p>
          <h2>Raw vs cleaned, per recording</h2>
          <LineChart
            id="score" labels={short} tips={names} yMax={1} digits={2}
            series={[
              { name: 'raw', values: recordings.map((r) => r.raw_score), color: GREY, dashed: true },
              { name: 'cleaned', values: recordings.map((r) => r.cleaned_score), color: RED, fill: true },
            ]}
          />
        </div>
        <div className="panel">
          <p className="kicker">NOISE RATIO · HIGH / LOW BAND</p>
          <h2>Noise drops after cleaning</h2>
          <LineChart
            id="noise" labels={short} tips={names} yMax={noiseMax} digits={1}
            series={[
              { name: 'raw', values: s.noiseRaw, color: GREY, dashed: true },
              { name: 'cleaned', values: s.noiseClean, color: RED, fill: true },
            ]}
          />
        </div>
      </div>

      <div className="grid two">
        <div className="panel">
          <p className="kicker">PASS RATE BY CHECK</p>
          <h2>Which checks fail on raw data</h2>
          <PassBars rows={s.bars} />
        </div>
        <div className="panel">
          <p className="kicker">RECORDING DETAIL</p>
          <h2>Per-check readings</h2>
          <div className="pills">
            {recordings.map((r, i) => (
              <button key={r.id} className={`pillbtn ${i === sel ? 'on' : ''}`} onClick={() => setSel(i)}>R{i + 1}</button>
            ))}
          </div>
          <div className="chips">
            <span className="chip">{rec.name}</span>
            <span className="chip">score <b>{rec.raw_score.toFixed(1)}</b> → <b>{rec.cleaned_score.toFixed(1)}</b></span>
            {rec.n_channels !== null && <span className="chip"><b>{rec.n_channels}</b> ch</span>}
            {rec.sampling_rate !== null && <span className="chip"><b>{rec.sampling_rate}</b> Hz</span>}
            {rec.duration_sec !== null && <span className="chip"><b>{rec.duration_sec}</b> s</span>}
            {rec.filter_low !== null && <span className="chip">band <b>{rec.filter_low}–{rec.filter_high}</b> Hz</span>}
            {rec.ica_removed !== null && <span className="chip">ICA <b>{rec.ica_removed}/{rec.ica_fit}</b> removed</span>}
            {rec.epochs !== null && <span className="chip"><b>{rec.epochs}</b> epochs</span>}
          </div>
          <div className="scroll">
            <table>
              <thead><tr><th>CHECK</th><th>RAW</th><th></th><th>CLEANED</th><th></th></tr></thead>
              <tbody>
                {rec.checks.map((c) => (
                  <tr key={c.check_name}>
                    <td>{LABELS[c.check_name]}</td>
                    <td className="val">{reading(c.check_name, c.raw_value)}</td>
                    <td><span className={`status ${c.raw_passed ? 'pass' : 'fail'}`}>{c.raw_passed ? 'PASS' : 'FAIL'}</span></td>
                    <td className="val">{reading(c.check_name, c.cleaned_value)}</td>
                    <td><span className={`status ${c.cleaned_passed ? 'pass' : 'fail'}`}>{c.cleaned_passed ? 'PASS' : 'FAIL'}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="panel">
        <p className="kicker">FULL VALIDATION LOG</p>
        <h2>Every check, every file</h2>
        <div className="scroll">
          <table>
            <thead><tr><th>FILE</th><th>CHECK</th><th>RAW</th><th>CLEANED</th><th>RAW READING</th><th>CLEANED READING</th></tr></thead>
            <tbody>
              {recordings.flatMap((r) =>
                r.checks.map((c) => (
                  <tr key={`${r.id}-${c.check_name}`}>
                    <td>{r.name}</td>
                    <td>{LABELS[c.check_name]}</td>
                    <td><span className={`status ${c.raw_passed ? 'pass' : 'fail'}`}>{c.raw_passed ? 'PASS' : 'FAIL'}</span></td>
                    <td><span className={`status ${c.cleaned_passed ? 'pass' : 'fail'}`}>{c.cleaned_passed ? 'PASS' : 'FAIL'}</span></td>
                    <td className="val">{reading(c.check_name, c.raw_value)}</td>
                    <td className="val">{reading(c.check_name, c.cleaned_value)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}
