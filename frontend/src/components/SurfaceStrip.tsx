import React, { useState } from 'react';
import type { SurfaceSegment } from '../types';

interface SurfaceStripProps {
  strip: SurfaceSegment[];
  breakdown: Record<string, number>;
  totalMiles?: number;
  compact?: boolean;
  onHoverIndex?: (index: number | null) => void;
}

const SURFACE_COLORS: Record<string, { bg: string; label: string }> = {
  singletrack: { bg: '#2E6F40', label: 'Singletrack' },
  doubletrack: { bg: '#C9A227', label: 'Doubletrack' },
  gravel: { bg: '#8D6E63', label: 'Gravel' },
  paved: { bg: '#78909C', label: 'Paved' },
  unpaved: { bg: '#B0BEC5', label: 'Unpaved' },
  unknown: { bg: '#CFD8DC', label: 'Trail' }
};

export const SurfaceStrip: React.FC<SurfaceStripProps> = ({
  strip,
  breakdown,
  totalMiles,
  compact = false,
  onHoverIndex
}) => {
  const [activeTooltip, setActiveTooltip] = useState<{
    text: string;
    pct: string;
    x: number;
  } | null>(null);

  if (!strip || strip.length === 0) {
    return (
      <div style={{ height: compact ? 6 : 12, backgroundColor: 'var(--color-divider, #E0E0E0)', borderRadius: 4 }} />
    );
  }

  const totalPoints = strip[strip.length - 1].end_index || 1;
  const unriddenPoints = strip
    .filter((s) => s.is_unridden)
    .reduce((acc, s) => acc + Math.max(s.end_index - s.start_index, 1), 0);
  const unriddenPct = Math.round((unriddenPoints / totalPoints) * 100);

  return (
    <div data-testid="surface-strip" style={{ display: 'flex', flexDirection: 'column', gap: compact ? 4 : 8, width: '100%' }}>
      {/* Segmented Horizontal Bar */}
      <div
        style={{
          display: 'flex',
          width: '100%',
          height: compact ? 8 : 14,
          borderRadius: 6,
          overflow: 'hidden',
          backgroundColor: 'var(--color-divider, #CFD8DC)',
          position: 'relative',
          boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.1)'
        }}
        onMouseLeave={() => {
          setActiveTooltip(null);
          onHoverIndex?.(null);
        }}
      >
        {strip.map((seg, idx) => {
          const segPoints = Math.max(seg.end_index - seg.start_index, 1);
          const pct = (segPoints / totalPoints) * 100;
          const conf = SURFACE_COLORS[seg.surface_type] || SURFACE_COLORS.unknown;
          const segMiles = totalMiles ? ((segPoints / totalPoints) * totalMiles).toFixed(1) : null;
          const unriddenSuffix = seg.is_unridden ? ' • ✨ New to you' : '';

          return (
            <div
              key={idx}
              style={{
                width: `${pct}%`,
                height: '100%',
                backgroundColor: conf.bg,
                transition: 'opacity 0.1s ease',
                cursor: 'pointer',
                borderTop: seg.is_unridden ? '3px solid #38BDF8' : 'none',
                boxSizing: 'border-box'
              }}
              onMouseEnter={(e) => {
                const rect = e.currentTarget.parentElement?.getBoundingClientRect();
                const xPos = rect ? e.clientX - rect.left : 0;
                setActiveTooltip({
                  text: `${conf.label}${segMiles ? ` (${segMiles} mi)` : ''}${unriddenSuffix}`,
                  pct: `${pct.toFixed(0)}%`,
                  x: xPos
                });
                onHoverIndex?.(Math.floor((seg.start_index + seg.end_index) / 2));
              }}
            />
          );
        })}

        {/* Hover Tooltip */}
        {activeTooltip && !compact && (
          <div
            style={{
              position: 'absolute',
              top: -30,
              left: Math.min(Math.max(activeTooltip.x - 45, 10), 280),
              backgroundColor: 'var(--color-header-bg, #1D3B34)',
              color: 'var(--color-header-text, #FFFFFF)',
              fontSize: 12,
              fontWeight: 600,
              padding: '2px 8px',
              borderRadius: 4,
              border: '1px solid var(--color-divider, rgba(255,255,255,0.2))',
              pointerEvents: 'none',
              whiteSpace: 'nowrap',
              zIndex: 10,
              boxShadow: '0 2px 6px rgba(0,0,0,0.2)'
            }}
          >
            {activeTooltip.text} • {activeTooltip.pct}
          </div>
        )}
      </div>

      {/* Surface Breakdown Legend */}
      {!compact && (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: '10px 14px',
            fontSize: 13,
            color: 'var(--color-text-primary, #1D3B34)'
          }}
        >
          {Object.entries(breakdown).map(([surfaceKey, pct]) => {
            if (pct <= 0) return null;
            const conf = SURFACE_COLORS[surfaceKey] || SURFACE_COLORS.unknown;
            return (
              <div key={surfaceKey} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                <span
                  style={{
                    display: 'inline-block',
                    width: 10,
                    height: 10,
                    borderRadius: 2,
                    backgroundColor: conf.bg
                  }}
                />
                <span style={{ fontWeight: 600 }}>{conf.label}:</span>
                <span className="num-tabular" style={{ color: 'var(--color-text-secondary, #42675E)' }}>{pct}%</span>
              </div>
            );
          })}
          {unriddenPct > 0 && (
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span
                style={{
                  display: 'inline-block',
                  width: 10,
                  height: 10,
                  borderRadius: 2,
                  backgroundColor: '#38BDF8'
                }}
              />
              <span style={{ fontWeight: 600, color: 'var(--color-slate, #0369A1)' }}>✨ New to you:</span>
              <span className="num-tabular" style={{ color: 'var(--color-slate, #0369A1)', fontWeight: 700 }}>{unriddenPct}%</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
