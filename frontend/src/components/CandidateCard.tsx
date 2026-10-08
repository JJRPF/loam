import React from 'react';
import type { RouteResponse } from '../types';

interface CandidateCardProps {
  route: RouteResponse;
  isSelected: boolean;
  onSelect: () => void;
  onHover?: (route: RouteResponse | null) => void;
}

export const CandidateCard: React.FC<CandidateCardProps> = ({
  route,
  isSelected,
  onSelect,
  onHover
}) => {
  const hours = Math.floor(route.duration_minutes / 60);
  const mins = Math.round(route.duration_minutes % 60);
  const durationText = hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;

  const stPct = Math.round(route.surface_breakdown?.singletrack || 0);
  const repPct = route.repetition_ratio !== undefined ? Math.round(route.repetition_ratio * 100) : null;

  return (
    <article
      onClick={onSelect}
      onMouseEnter={() => onHover?.(route)}
      onMouseLeave={() => onHover?.(null)}
      style={{
        backgroundColor: '#FFFFFF',
        borderRadius: 8,
        padding: '12px 14px',
        border: isSelected ? '2px solid #FF5B14' : '1px solid #D1D8D8',
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
                backgroundColor: isSelected ? '#1D3B34' : '#E2ECF3',
                color: isSelected ? '#FFFFFF' : '#1D3B34',
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
              color: '#1D3B34',
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
            backgroundColor: isSelected ? '#FF5B14' : '#F3F7F7',
            color: isSelected ? '#FFFFFF' : '#1D3B34',
            flexShrink: 0
          }}
        >
          <span style={{ fontSize: 10, fontWeight: 600, opacity: 0.85, textTransform: 'uppercase' }}>Match</span>
          <span className="num-tabular" style={{ fontSize: 15, fontWeight: 700 }}>
            {route.match_score ?? 90}
          </span>
        </div>
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
                color: isSelected ? '#FF5B14' : '#1D3B34',
                lineHeight: 1
              }}
            >
              {route.distance_miles.toFixed(1)}
            </span>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#42675E' }}>mi</span>
          </div>

          <div className="num-tabular" style={{ fontSize: 12, color: '#42675E' }}>
            +{Math.round(route.elevation_gain_ft)} ft • {durationText}
          </div>

          <div style={{ fontSize: 11, color: '#1D3B34', marginTop: 2, display: 'flex', gap: 6, alignItems: 'center' }}>
            <span>{stPct}% Singletrack</span>
            {repPct !== null && (
              <span
                style={{
                  fontSize: 10,
                  padding: '1px 5px',
                  borderRadius: 3,
                  backgroundColor: repPct < 25 ? '#E8F5E9' : '#FFF3E0',
                  color: repPct < 25 ? '#2E6F40' : '#C73E00',
                  fontWeight: 600
                }}
              >
                {repPct < 25 ? 'Loop' : `${repPct}% Rep`}
              </span>
            )}
          </div>

          {/* Trust Layer Warning Chips */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 3 }}>
            {route.hard_block_waived && (
              <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, backgroundColor: '#E8F5E9', color: '#2E6F40' }}>
                ✓ Waived
              </span>
            )}
            {route.dnr_warnings && route.dnr_warnings.length > 0 && (
              <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, backgroundColor: '#FFF3E0', color: '#C73E00' }}>
                ⚠️ DNR ({route.dnr_warnings.length})
              </span>
            )}
            {route.snowmobile_warnings && route.snowmobile_warnings.length > 0 && (
              <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, backgroundColor: '#E0F7FA', color: '#006064' }}>
                ❄️ Snowmobile
              </span>
            )}
            {route.community_flag_warnings && route.community_flag_warnings.length > 0 && (
              <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, backgroundColor: '#FFFDE7', color: '#F57F17' }}>
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
              backgroundColor: '#F3F7F7',
              borderRadius: 6,
              border: '1px solid #D1D8D8',
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
                stroke={isSelected ? '#FF5B14' : '#3F6C8F'}
                strokeWidth={isSelected ? '3.0' : '2.2'}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
        ) : (
          <div style={{ width: 84, height: 56, backgroundColor: '#F3F7F7', borderRadius: 6 }} />
        )}
      </div>

      {/* Mini Surface Strip (Compact Terrain Proportion Bar) */}
      <div
        style={{
          display: 'flex',
          height: 4,
          borderRadius: 2,
          overflow: 'hidden',
          backgroundColor: '#E0E0E0',
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
