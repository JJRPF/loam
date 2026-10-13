import React, { useState } from 'react';
import type { RouteResponse } from '../types';
import { formatGain } from '../format';

interface CandidateCardProps {
  route: RouteResponse;
  isSelected: boolean;
  onSelect: () => void;
  onHover?: (route: RouteResponse | null) => void;
  /** Passed only when signed in: adds the overflow menu with "Report bad route". */
  onReportBad?: () => void;
}

export const CandidateCard: React.FC<CandidateCardProps> = ({
  route,
  isSelected,
  onSelect,
  onHover,
  onReportBad
}) => {
  const [menuOpen, setMenuOpen] = useState(false);
  const durationMins = route.duration_minutes ?? 0;
  const hours = Math.floor(durationMins / 60);
  const mins = Math.round(durationMins % 60);
  const durationText = hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;

  const distMi = route.distance_miles ?? 0;
  const stPct = Math.round(route.surface_breakdown?.singletrack || 0);

  return (
    <article
      onClick={onSelect}
      onMouseEnter={() => onHover?.(route)}
      onMouseLeave={() => onHover?.(null)}
      style={{
        backgroundColor: 'var(--color-card-bg, #FFFFFF)',
        borderRadius: 8,
        padding: '12px 14px',
        border: isSelected ? '2px solid var(--color-blaze, #FF5B14)' : '1px solid var(--color-divider, #D1D8D8)',
        boxShadow: isSelected ? '0 3px 10px rgba(255, 91, 20, 0.16)' : '0 1px 3px rgba(0,0,0,0.04)',
        cursor: 'pointer',
        transition: 'all 0.18s ease-in-out',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        position: 'relative'
      }}
    >
      {/* Header Row: Sector Chip, Title, Score */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, flex: 1, marginRight: 8 }}>
          {route.sector && (
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                backgroundColor: isSelected ? 'var(--color-header-bg, #1D3B34)' : 'var(--color-slate-light, #E2ECF3)',
                color: isSelected ? '#FFFFFF' : 'var(--color-text-primary, #1D3B34)',
                padding: '2px 6px',
                borderRadius: 4,
                flexShrink: 0
              }}
            >
              {route.sector}
            </span>
          )}
          <span
            style={{
              fontSize: 14,
              fontWeight: 700,
              color: 'var(--color-text-primary, #1D3B34)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis'
            }}
            title={route.name}
          >
            {route.name || 'Loam Option'}
          </span>
        </div>

        {/* Match Score Badge */}
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 4,
            padding: '3px 8px',
            borderRadius: 6,
            backgroundColor: isSelected ? 'var(--color-blaze, #FF5B14)' : 'var(--color-bg-subtle, #F3F7F7)',
            color: isSelected ? '#FFFFFF' : 'var(--color-text-primary, #1D3B34)',
            flexShrink: 0
          }}
        >
          <span style={{ fontSize: 10, fontWeight: 600, opacity: 0.85, textTransform: 'uppercase' }}>Match</span>
          <span className="num-tabular" style={{ fontSize: 15, fontWeight: 700 }}>
            {route.match_score ?? 90}
          </span>
        </div>

        {onReportBad && (
          <div style={{ position: 'relative', marginLeft: 6, flexShrink: 0 }}>
            <button
              type="button"
              aria-label="More actions"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={(e) => { e.stopPropagation(); setMenuOpen((o) => !o); }}
              style={{ minWidth: 32, minHeight: 32, border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 18, lineHeight: 1, color: 'var(--color-text-primary, #1D3B34)' }}
            >
              ⋯
            </button>
            {menuOpen && (
              <div
                role="menu"
                style={{ position: 'absolute', right: 0, top: 34, zIndex: 20, background: 'var(--color-card-bg, #FFFFFF)', border: '1px solid var(--color-divider, #D1D8D8)', borderRadius: 6, boxShadow: '0 4px 12px rgba(0,0,0,0.2)', whiteSpace: 'nowrap' }}
              >
                <button
                  type="button"
                  role="menuitem"
                  onClick={(e) => { e.stopPropagation(); setMenuOpen(false); onReportBad(); }}
                  style={{ display: 'block', padding: '8px 12px', minHeight: 36, border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 13, color: 'var(--color-text-primary, #1D3B34)' }}
                >
                  Report bad route
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Main Stats & Inline SVG Minimap */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
            <span
              className="num-tabular"
              style={{
                fontSize: 24,
                fontWeight: 700,
                color: isSelected ? 'var(--color-blaze, #FF5B14)' : 'var(--color-text-primary, #1D3B34)',
                lineHeight: 1
              }}
            >
              {distMi.toFixed(1)}
            </span>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-secondary, #42675E)' }}>mi</span>
          </div>

          <div className="num-tabular" style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>
            {formatGain(route.elevation_gain_ft)} • {durationText}
          </div>
          {(route.access_miles ?? 0) >= 0.1 && (
            <div className="num-tabular" style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)' }}>
              {route.access_miles!.toFixed(1)} mi road to trail
            </div>
          )}

          <div style={{ fontSize: 11, color: 'var(--color-text-primary, #1D3B34)', marginTop: 2, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <span>{stPct}% Singletrack</span>
            {route.route_type && (
              <span
                style={{
                  fontSize: 10,
                  padding: '1px 5px',
                  borderRadius: 3,
                  backgroundColor: 
                    route.route_type === 'loop' ? 'rgba(46, 111, 64, 0.2)' :
                    route.route_type === 'lollipop' ? 'rgba(63, 108, 143, 0.2)' :
                    'rgba(255, 91, 20, 0.2)',
                  color: 
                    route.route_type === 'loop' ? 'var(--color-lichen, #2E6F40)' :
                    route.route_type === 'lollipop' ? '#1E40AF' :
                    'var(--color-blaze, #C73E00)',
                  fontWeight: 700
                }}
              >
                {route.route_type === 'loop' ? 'True Loop' : route.route_type === 'lollipop' ? 'Lollipop' : 'Out & Back'}
                {route.retraced_miles !== undefined && route.retraced_miles > 0 && route.route_type !== 'loop' ? ` (${route.retraced_miles.toFixed(1)} mi retraced)` : ''}
              </span>
            )}
            {((route.unridden_miles !== undefined && route.unridden_miles > 0) || route.is_find_new_trails) && (
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  padding: '1px 6px',
                  borderRadius: 3,
                  backgroundColor: 'rgba(3, 105, 161, 0.15)',
                  color: 'var(--color-slate, #0369A1)',
                  border: '1px solid rgba(186, 230, 253, 0.4)'
                }}
                title={`${route.unridden_miles?.toFixed(1) || '0.0'} miles of trails you haven't ridden yet`}
              >
                ✨ {route.unridden_miles !== undefined ? route.unridden_miles.toFixed(1) : '0.0'} mi New ({Math.round(route.unridden_percent || 0)}%)
              </span>
            )}
          </div>

          {/* Trust Layer Warning Chips */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 3 }}>
            {route.hard_block_waived && (
              <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, backgroundColor: 'rgba(46, 111, 64, 0.25)', color: 'var(--color-lichen, #2E6F40)' }}>
                ✓ Waived
              </span>
            )}
            {route.dnr_warnings && route.dnr_warnings.length > 0 && (
              <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, backgroundColor: 'rgba(230, 81, 0, 0.25)', color: 'var(--color-blaze, #C73E00)' }}>
                ⚠️ DNR ({route.dnr_warnings.length})
              </span>
            )}
            {route.snowmobile_warnings && route.snowmobile_warnings.length > 0 && (
              <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, backgroundColor: 'rgba(0, 96, 100, 0.25)', color: 'var(--color-slate, #00838F)' }}>
                ❄️ Snowmobile
              </span>
            )}
            {route.community_flag_warnings && route.community_flag_warnings.length > 0 && (
              <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, backgroundColor: 'rgba(245, 127, 23, 0.25)', color: '#F59E0B' }}>
                🚩 Flagged
              </span>
            )}
          </div>
        </div>

        {/* Lightweight SVG Minimap */}
        {route.minimap_svg ? (
          <div
            style={{
              width: 84,
              height: 56,
              backgroundColor: 'var(--color-bg-subtle, #F3F7F7)',
              borderRadius: 6,
              border: '1px solid var(--color-divider, #D1D8D8)',
              overflow: 'hidden',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0
            }}
          >
            <svg
              viewBox="0 0 120 80"
              style={{ width: '100%', height: '100%', display: 'block' }}
              aria-label="Route minimap preview"
            >
              <path
                d={route.minimap_svg}
                fill="none"
                stroke={isSelected ? 'var(--color-blaze, #FF5B14)' : 'var(--color-slate, #3F6C8F)'}
                strokeWidth={isSelected ? '3.0' : '2.2'}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
        ) : (
          <div style={{ width: 84, height: 56, backgroundColor: 'var(--color-bg-subtle, #F3F7F7)', borderRadius: 6 }} />
        )}
      </div>

      {/* Mini Surface Strip (Compact Terrain Proportion Bar) */}
      <div
        style={{
          display: 'flex',
          height: 4,
          borderRadius: 2,
          overflow: 'hidden',
          backgroundColor: 'var(--color-divider, #E0E0E0)',
          marginTop: 2
        }}
      >
        <div style={{ width: `${route.surface_breakdown?.singletrack || 0}%`, backgroundColor: '#2E6F40' }} title="Singletrack" />
        <div style={{ width: `${route.surface_breakdown?.doubletrack || 0}%`, backgroundColor: '#8D6E63' }} title="Doubletrack" />
        <div style={{ width: `${route.surface_breakdown?.gravel || 0}%`, backgroundColor: '#D4A373' }} title="Gravel" />
        <div style={{ width: `${route.surface_breakdown?.paved || 0}%`, backgroundColor: '#78909C' }} title="Paved" />
      </div>
    </article>
  );
};

export default CandidateCard;
