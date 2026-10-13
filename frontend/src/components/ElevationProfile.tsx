import React, { useRef, useState, useMemo } from 'react';
import type { SurfaceSegment } from '../types';
import { SurfaceStrip } from './SurfaceStrip';

interface ElevationProfileProps {
  coordinates: number[][]; // [[lon, lat], ...] or [[lon, lat, ele], ...]
  surfaceStrip: SurfaceSegment[];
  surfaceBreakdown: Record<string, number>;
  distanceMiles: number;
  elevationGainFt: number | null;
  elevationLossFt: number | null;
  onScrub?: (coord: [number, number] | null, index: number | null) => void;
}

export const ElevationProfile: React.FC<ElevationProfileProps> = ({
  coordinates,
  surfaceStrip,
  surfaceBreakdown,
  distanceMiles,
  elevationGainFt,
  elevationLossFt,
  onScrub
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoverData, setHoverData] = useState<{
    x: number;
    y: number;
    tooltipLeft: number;
    distMi: number;
    eleFt: number;
    gradePct: number;
    surfaceType: string;
  } | null>(null);

  // Derive points data with elevation in feet and cumulative distance
  const profilePoints = useMemo(() => {
    if (!coordinates || coordinates.length === 0) return [];

    let cumDistM = 0;
    const pts: { distMi: number; eleFt: number; coord: [number, number] }[] = [];

    // Only a real DEM sample on every vertex draws a profile; otherwise there is no curve.
    const hasEle = coordinates.every(c => c.length > 2 && c[2] !== null && Number.isFinite(c[2]));
    if (!hasEle) return [];

    for (let i = 0; i < coordinates.length; i++) {
      const c = coordinates[i];
      if (i > 0) {
        const prev = coordinates[i - 1];
        // Approximate distance
        const dx = (c[0] - prev[0]) * Math.cos((c[1] * Math.PI) / 180) * 111132;
        const dy = (c[1] - prev[1]) * 111132;
        cumDistM += Math.sqrt(dx * dx + dy * dy);
      }

      const eleFt = c[2] * 3.28084;

      pts.push({
        distMi: (cumDistM * 0.000621371),
        eleFt: Math.round(eleFt),
        coord: [c[0], c[1]]
      });
    }

    // Scale final distance to match distanceMiles
    if (pts.length > 0 && cumDistM > 0 && distanceMiles > 0) {
      const lastDist = pts[pts.length - 1].distMi;
      if (lastDist > 0) {
        const factor = distanceMiles / lastDist;
        pts.forEach(p => { p.distMi = p.distMi * factor; });
      }
    }

    return pts;
  }, [coordinates, distanceMiles]);

  const { minEle, maxEle, pathD, areaD, width, height } = useMemo(() => {
    const w = 400;
    const h = 100;
    if (profilePoints.length < 2) {
      return { minEle: 0, maxEle: 0, pathD: '', areaD: '', width: w, height: h };
    }

    const eles = profilePoints.map(p => p.eleFt);
    const minE = Math.min(...eles);
    const maxE = Math.max(...eles);
    const eleRange = Math.max(maxE - minE, 60);

    const padTop = 15;
    const padBottom = 15;
    const plotH = h - padTop - padBottom;

    const maxDist = profilePoints[profilePoints.length - 1].distMi || 1;

    const pointsD = profilePoints.map((p, idx) => {
      const x = (p.distMi / maxDist) * w;
      const y = padTop + plotH - ((p.eleFt - minE) / eleRange) * plotH;
      return `${idx === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    }).join(' ');

    const area = `${pointsD} L ${w} ${h} L 0 ${h} Z`;

    return { minEle: minE, maxEle: maxE, pathD: pointsD, areaD: area, width: w, height: h };
  }, [profilePoints]);

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!containerRef.current || profilePoints.length < 2) return;
    const rect = containerRef.current.getBoundingClientRect();
    const xPct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const targetIdx = Math.round(xPct * (profilePoints.length - 1));
    const currentPt = profilePoints[targetIdx];

    // Compute grade
    let grade = 0;
    if (targetIdx > 0 && targetIdx < profilePoints.length) {
      const prev = profilePoints[targetIdx - 1];
      const dMi = currentPt.distMi - prev.distMi;
      if (dMi > 0.01) {
        const dFt = currentPt.eleFt - prev.eleFt;
        grade = Math.round((dFt / (dMi * 5280)) * 100);
      }
    }

    // Find surface type for this index
    let surfaceType = 'singletrack';
    if (surfaceStrip && surfaceStrip.length > 0) {
      const seg = surfaceStrip.find(s => targetIdx >= s.start_index && targetIdx <= s.end_index);
      if (seg) surfaceType = seg.surface_type;
    }

    const xPos = xPct * rect.width;
    const tooltipLeft = Math.min(Math.max(xPos - 70, 8), Math.max(rect.width - 150, 10));

    setHoverData({
      x: xPos,
      y: (e.clientY - rect.top),
      tooltipLeft,
      distMi: Number(currentPt.distMi.toFixed(2)),
      eleFt: currentPt.eleFt,
      gradePct: grade,
      surfaceType
    });

    onScrub?.(currentPt.coord, targetIdx);
  };

  const handlePointerLeave = () => {
    setHoverData(null);
    onScrub?.(null, null);
  };

  const hasProfile = profilePoints.length >= 2 && elevationGainFt !== null && elevationLossFt !== null;

  if (!hasProfile) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
        <div style={{ fontSize: 13, color: 'var(--color-text-primary, #1D3B34)' }}>
          <span style={{ fontWeight: 700, fontSize: 15 }}>Elevation unavailable</span>
          <span style={{ marginLeft: 8, color: 'var(--color-text-secondary, #42675E)' }}>
            No elevation data covers this route.
          </span>
        </div>
        <SurfaceStrip strip={surfaceStrip} breakdown={surfaceBreakdown} totalMiles={distanceMiles} compact={false} />
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
      {/* Elevation Stats Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', fontSize: 13, color: 'var(--color-text-primary, #1D3B34)' }}>
        <div>
          <span style={{ fontWeight: 700, fontSize: 15, color: 'var(--color-text-primary, #1D3B34)' }}>Elevation Profile</span>
          <span style={{ marginLeft: 8, color: 'var(--color-text-secondary, #42675E)' }}>
            +{Math.round(elevationGainFt ?? 0)} ft / -{Math.round(elevationLossFt ?? 0)} ft
          </span>
        </div>
        <div className="num-tabular" style={{ color: 'var(--color-text-secondary, #42675E)', fontSize: 12 }}>
          {minEle} ft – {maxEle} ft
        </div>
      </div>

      {/* SVG Canvas with Interactive Scrubber */}
      <div
        ref={containerRef}
        style={{
          position: 'relative',
          width: '100%',
          height: 100,
          backgroundColor: 'var(--color-card-bg, #FFFFFF)',
          borderRadius: 8,
          border: '1px solid var(--color-divider, #D1D8D8)',
          overflow: 'hidden',
          cursor: 'crosshair',
          touchAction: 'none'
        }}
        onPointerMove={handlePointerMove}
        onPointerLeave={handlePointerLeave}
      >
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          style={{ width: '100%', height: '100%', display: 'block' }}
        >
          <defs>
            <linearGradient id="eleFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#3F6C8F" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#3F6C8F" stopOpacity="0.05" />
            </linearGradient>
          </defs>

          {/* Area fill */}
          {areaD && <path d={areaD} fill="url(#eleFill)" />}

          {/* Profile curve */}
          {pathD && (
            <path
              d={pathD}
              fill="none"
              stroke="var(--color-text-primary, #1D3B34)"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* Grid line at base */}
          <line x1="0" y1={height - 2} x2={width} y2={height - 2} stroke="var(--color-divider, #D1D8D8)" strokeWidth="1" />
        </svg>

        {/* Hover Crosshair & Tooltip */}
        {hoverData && (
          <>
            <div
              style={{
                position: 'absolute',
                top: 0,
                bottom: 0,
                left: hoverData.x,
                width: 2,
                backgroundColor: 'var(--color-blaze, #FF5B14)',
                pointerEvents: 'none'
              }}
            />
            <div
              style={{
                position: 'absolute',
                top: 8,
                left: hoverData.tooltipLeft,
                backgroundColor: 'var(--color-header-bg, #1D3B34)',
                color: 'var(--color-header-text, #FFFFFF)',
                borderRadius: 6,
                border: '1px solid var(--color-divider, rgba(255,255,255,0.2))',
                padding: '4px 8px',
                fontSize: 12,
                pointerEvents: 'none',
                boxShadow: '0 2px 6px rgba(0,0,0,0.25)',
                whiteSpace: 'nowrap',
                zIndex: 20
              }}
            >
              <div style={{ fontWeight: 700 }}>
                {hoverData.distMi} mi • {hoverData.eleFt} ft
              </div>
              <div style={{ color: 'var(--color-lichen, #A9BF7A)', fontSize: 11, textTransform: 'capitalize' }}>
                {hoverData.surfaceType} {hoverData.gradePct !== 0 ? `(${hoverData.gradePct > 0 ? '+' : ''}${hoverData.gradePct}%)` : ''}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Signature Element: Surface Strip Directly Beneath Profile */}
      <SurfaceStrip
        strip={surfaceStrip}
        breakdown={surfaceBreakdown}
        totalMiles={distanceMiles}
        compact={false}
      />
    </div>
  );
};
