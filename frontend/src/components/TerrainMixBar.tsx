import React, { useRef } from 'react';
import type { TerrainPreference } from '../types';

const GROUPS: { key: keyof TerrainPreference; label: string; color: string }[] = [
  { key: 'singletrack', label: 'Singletrack', color: '#2E6F40' },
  { key: 'doubletrack', label: 'Doubletrack', color: '#C9A227' },
  { key: 'gravel', label: 'Gravel', color: '#8D6E63' },
  { key: 'paved', label: 'Paved', color: '#78909C' }
];
const STEP = 0.05;

interface Props {
  value: TerrainPreference;
  onChange: (next: TerrainPreference) => void;
}

/** Moves divider `i` (between group i and i+1) to `pos`, a fraction of the bar, without crossing its neighbours. */
export function moveDivider(value: TerrainPreference, i: number, pos: number): TerrainPreference {
  const w = GROUPS.map((g) => value[g.key]);
  const before = w.slice(0, i).reduce((a, b) => a + b, 0);
  const pair = w[i] + w[i + 1];
  const snapped = Math.round(pos / STEP) * STEP;
  const left = Math.min(pair, Math.max(0, snapped - before));
  const next = [...w];
  next[i] = left;
  next[i + 1] = pair - left;
  return Object.fromEntries(GROUPS.map((g, k) => [g.key, Math.round(next[k] * 100) / 100])) as unknown as TerrainPreference;
}

export const TerrainMixBar: React.FC<Props> = ({ value, onChange }) => {
  const barRef = useRef<HTMLDivElement>(null);
  const cum: number[] = [];
  GROUPS.reduce((acc, g) => { cum.push(acc + value[g.key]); return acc + value[g.key]; }, 0);

  const dragTo = (i: number, clientX: number) => {
    const rect = barRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;
    onChange(moveDivider(value, i, (clientX - rect.left) / rect.width));
  };

  return (
    <div>
      <div
        ref={barRef}
        data-testid="terrain-bar"
        style={{ position: 'relative', display: 'flex', height: 28, borderRadius: 6, overflow: 'visible', marginBottom: 10, touchAction: 'none', userSelect: 'none' }}
      >
        {GROUPS.map((g, k) => (
          <div
            key={g.key}
            title={`${g.label} ${Math.round(value[g.key] * 100)}%`}
            style={{
              width: `${value[g.key] * 100}%`, backgroundColor: g.color,
              borderRadius: k === 0 ? '6px 0 0 6px' : k === GROUPS.length - 1 ? '0 6px 6px 0' : 0
            }}
          />
        ))}
        {cum.slice(0, -1).map((c, i) => (
          <div
            key={i}
            role="slider"
            tabIndex={0}
            aria-label={`${GROUPS[i].label} / ${GROUPS[i + 1].label} divider`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(c * 100)}
            data-testid={`terrain-divider-${i}`}
            onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); }}
            onPointerMove={(e) => { if ((e.currentTarget as HTMLElement).hasPointerCapture(e.pointerId)) dragTo(i, e.clientX); }}
            onKeyDown={(e) => {
              const d = e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -STEP : e.key === 'ArrowRight' || e.key === 'ArrowUp' ? STEP : 0;
              if (d) { e.preventDefault(); onChange(moveDivider(value, i, c + d)); }
            }}
            style={{
              position: 'absolute', left: `${c * 100}%`, top: -4, bottom: -4, width: 24, marginLeft: -12,
              cursor: 'ew-resize', display: 'flex', alignItems: 'center', justifyContent: 'center'
            }}
          >
            <div style={{ width: 6, height: '100%', borderRadius: 3, background: '#FFFFFF', border: '1px solid #1D3B34', boxShadow: '0 1px 3px rgba(0,0,0,0.35)' }} />
          </div>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        {GROUPS.map((g) => (
          <span key={g.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, backgroundColor: g.color }} />
            {g.label}
            <span className="num-tabular" style={{ fontWeight: 600, marginLeft: 'auto' }}>{Math.round(value[g.key] * 100)}%</span>
          </span>
        ))}
      </div>
    </div>
  );
};

export default TerrainMixBar;
