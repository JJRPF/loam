import React, { useState } from 'react';
import type { 
  SportProfile, 
  TerrainPreference, 
  LatLon, 
  GeocodeResult
} from '../types';
import { 
  TERRAIN_PRESETS
} from '../types';
import { geocodeLocations } from '../services/api';
import { TerrainMixBar } from './TerrainMixBar';

interface PlanPanelProps {
  sport: SportProfile;
  onSportChange: (sport: SportProfile) => void;
  start: LatLon;
  onStartChange: (start: LatLon) => void;
  end?: LatLon;
  onEndChange: (end?: LatLon) => void;
  routeMode: 'loop' | 'point_to_point' | 'out_and_back';
  onRouteChange: (mode: 'loop' | 'point_to_point' | 'out_and_back') => void;
  targetMiles: number;
  onTargetMilesChange: (miles: number) => void;
  terrainPref: TerrainPreference;
  onTerrainPrefChange: (pref: TerrainPreference) => void;
  onBuildRoutes: () => void;
  isLoading: boolean;
  onPickOnMap: (target: 'start' | 'end' | 'mid') => void;
  pickingTarget: 'start' | 'end' | 'mid' | null;
  waypoints?: LatLon[];
  onWaypointsChange?: (w: LatLon[]) => void;
  overrideDnr?: boolean;
  onOverrideDnrChange?: (override: boolean) => void;
  // Stage 6: Differentiators
  findNewTrailsMode?: boolean;
  onFindNewTrailsModeChange?: (val: boolean) => void;
  minNewTrailPercent?: number;
  onMinNewTrailPercentChange?: (pct: number) => void;
  trailRunSteeperGrades?: boolean;
  onTrailRunSteeperGradesChange?: (val: boolean) => void;
  trailRunAvoidMtbFlow?: boolean;
  onTrailRunAvoidMtbFlowChange?: (val: boolean) => void;
  loopsOnly?: boolean;
  onLoopsOnlyChange?: (val: boolean) => void;
}

export const PlanPanel: React.FC<PlanPanelProps> = ({
  sport,
  onSportChange,
  start,
  onStartChange,
  end,
  onEndChange,
  routeMode,
  onRouteChange,
  targetMiles,
  onTargetMilesChange,
  terrainPref,
  onTerrainPrefChange,
  onBuildRoutes,
  isLoading,
  onPickOnMap,
  pickingTarget,
  waypoints = [],
  onWaypointsChange,
  overrideDnr = false,
  onOverrideDnrChange,
  findNewTrailsMode = false,
  onFindNewTrailsModeChange,
  minNewTrailPercent = 30,
  onMinNewTrailPercentChange,
  trailRunSteeperGrades = true,
  onTrailRunSteeperGradesChange,
  trailRunAvoidMtbFlow = true,
  onTrailRunAvoidMtbFlowChange,
  loopsOnly = false,
  onLoopsOnlyChange
}) => {
  const [selectedPresetName, setSelectedPresetName] = useState<string>("Mostly Trail");

  // Geocoding states
  const [startQuery, setStartQuery] = useState('');
  const [startResults, setStartResults] = useState<GeocodeResult[]>([]);
  const [isSearchingStart, setIsSearchingStart] = useState(false);
  const [showStartResults, setShowStartResults] = useState(false);

  const [endQuery, setEndQuery] = useState('');
  const [endResults, setEndResults] = useState<GeocodeResult[]>([]);
  const [isSearchingEnd, setIsSearchingEnd] = useState(false);
  const [showEndResults, setShowEndResults] = useState(false);

  const handleApplyTerrainPreset = (presetName: string) => {
    const found = TERRAIN_PRESETS.find(p => p.name === presetName);
    if (found) {
      setSelectedPresetName(presetName);
      onTerrainPrefChange(found.weights);
    }
  };

  const handleLocateMe = () => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          onStartChange({
            lat: pos.coords.latitude,
            lon: pos.coords.longitude,
            name: "Current GPS Location"
          });
        },
        (err) => {
          alert(`Location access failed: ${err.message}. Defaulting to Bear Brook State Park.`);
        }
      );
    } else {
      alert("Geolocation is not supported by your browser.");
    }
  };

  const handleStartSearch = async (val: string) => {
    setStartQuery(val);
    if (val.trim().length >= 2) {
      setIsSearchingStart(true);
      setShowStartResults(true);
      try {
        const results = await geocodeLocations(val.trim());
        setStartResults(results);
      } finally {
        setIsSearchingStart(false);
      }
    } else {
      setStartResults([]);
      setShowStartResults(false);
    }
  };

  const handleSelectStartLocation = (loc: GeocodeResult) => {
    onStartChange({
      lat: loc.lat,
      lon: loc.lon,
      name: loc.name
    });
    setStartQuery('');
    setShowStartResults(false);
    setStartResults([]);
  };

  const handleEndSearch = async (val: string) => {
    setEndQuery(val);
    if (val.trim().length >= 2) {
      setIsSearchingEnd(true);
      setShowEndResults(true);
      try {
        const results = await geocodeLocations(val.trim());
        setEndResults(results);
      } finally {
        setIsSearchingEnd(false);
      }
    } else {
      setEndResults([]);
      setShowEndResults(false);
    }
  };

  const handleSelectEndLocation = (loc: GeocodeResult) => {
    onEndChange({
      lat: loc.lat,
      lon: loc.lon,
      name: loc.name
    });
    setEndQuery('');
    setShowEndResults(false);
    setEndResults([]);
  };

  // Functionally active sports: Mountain Bike and Trail Run
  const activeSport = sport === 'trail_run' ? 'trail_run' : 'mtb';

  const handleSportSelect = (targetSport: 'mtb' | 'trail_run') => {
    if (targetSport === 'mtb') {
      onSportChange('mtb');
      handleApplyTerrainPreset("Mostly Trail");
    } else {
      onSportChange('trail_run');
      handleApplyTerrainPreset("Mostly Trail");
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '4px 0 24px 0' }}>
      
      {/* 1. Sport Mode Selector: Mountain Bike & Trail Run */}
      <section>
        <label style={{ display: 'block', fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', marginBottom: 6 }}>
          Sport & Route Profile
        </label>
        <div style={{ display: 'flex', gap: 8 }}>
          {[
            { id: 'mtb', label: '🚵 Mountain Bike' },
            { id: 'trail_run', label: '🏃 Trail Run' }
          ].map(s => {
            const isSelected = activeSport === s.id;
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => handleSportSelect(s.id as any)}
                className={isSelected ? 'btn-primary' : 'btn-secondary'}
                style={{
                  flex: 1,
                  fontSize: 13,
                  padding: '8px 6px',
                  minHeight: 42,
                  backgroundColor: isSelected ? 'var(--color-blaze-dark, #C73E00)' : 'var(--color-card-bg, #FFFFFF)',
                  color: isSelected ? '#FFFFFF' : 'var(--color-text-primary, #1D3B34)',
                  borderColor: isSelected ? 'var(--color-blaze, #FF5B14)' : 'var(--color-divider, #D1D8D8)',
                  borderRadius: 6
                }}
              >
                {s.label}
              </button>
            );
          })}
        </div>

        {/* Trail Running Profile Polish */}
        {activeSport === 'trail_run' && (
          <div style={{ backgroundColor: 'var(--color-bg-subtle, #F3F7F7)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
              🏃 Trail Running Routing Polish
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 12, color: 'var(--color-text-primary, #1D3B34)' }}>
              <input
                type="checkbox"
                checked={trailRunSteeperGrades}
                onChange={(e) => onTrailRunSteeperGradesChange?.(e.target.checked)}
                style={{ accentColor: '#2E6F40' }}
              />
              <span>Allow steeper grades & foot-only stairs (Hiking tolerance)</span>
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 12, color: 'var(--color-text-primary, #1D3B34)' }}>
              <input
                type="checkbox"
                checked={trailRunAvoidMtbFlow}
                onChange={(e) => onTrailRunAvoidMtbFlowChange?.(e.target.checked)}
                style={{ accentColor: '#2E6F40' }}
              />
              <span>Avoid high-speed downhill mountain bike flow trails</span>
            </label>
          </div>
        )}
      </section>

      {/* 2. Route Mode: Loop / Round Trip vs Point to Point */}
      <section>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <label style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
            Route Type
          </label>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {[
            { id: 'loop', label: 'Loop / Round Trip' },
            { id: 'point_to_point', label: 'Point to Point' },
            { id: 'out_and_back', label: 'Out & Back' }
          ].map(m => (
            <button
              key={m.id}
              type="button"
              onClick={() => onRouteChange(m.id as any)}
              style={{
                flex: 1,
                padding: '8px 10px',
                minHeight: 40,
                fontSize: 13,
                fontWeight: routeMode === m.id ? 700 : 500,
                backgroundColor: routeMode === m.id ? 'var(--color-header-bg, #1D3B34)' : 'var(--color-card-bg, #FFFFFF)',
                color: routeMode === m.id ? '#FFFFFF' : 'var(--color-text-primary, #1D3B34)',
                borderColor: routeMode === m.id ? 'var(--color-header-bg, #1D3B34)' : 'var(--color-divider, #D1D8D8)',
                borderRadius: 6
              }}
            >
              {m.label}
            </button>
          ))}
        </div>
        {routeMode === 'loop' && (
          <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 10px', backgroundColor: 'var(--color-bg-subtle, #F5F7F7)', borderRadius: 6, border: '1px solid var(--color-divider, #D1D8D8)' }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-primary, #1D3B34)' }}>
              Loops only (retrace ≤ 10%)
            </span>
            <input
              type="checkbox"
              id="loops-only-checkbox"
              checked={loopsOnly}
              onChange={(e) => onLoopsOnlyChange?.(e.target.checked)}
              style={{ width: 16, height: 16, cursor: 'pointer', accentColor: 'var(--color-lichen, #2E6F40)' }}
            />
          </div>
        )}
      </section>

      {/* 3. Starting Location UX: Search, Direct Map Tap, Geolocation (No dropdown presets) */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <label style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
              Starting Location
            </label>
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                type="button"
                onClick={handleLocateMe}
                style={{ fontSize: 12, padding: '2px 8px', minHeight: 28, backgroundColor: 'var(--color-slate-light, #E2ECF3)', color: 'var(--color-text-primary, #1D3B34)' }}
                title="Use browser GPS location"
              >
                📍 GPS
              </button>
              <button
                type="button"
                onClick={() => onPickOnMap('start')}
                style={{
                  fontSize: 12,
                  padding: '2px 8px',
                  minHeight: 28,
                  backgroundColor: pickingTarget === 'start' ? 'var(--color-blaze, #FF5B14)' : 'var(--color-slate-light, #E2ECF3)',
                  color: pickingTarget === 'start' ? '#FFFFFF' : 'var(--color-text-primary, #1D3B34)'
                }}
                title="Tap anywhere on map"
              >
                {pickingTarget === 'start' ? 'Tap Map...' : 'Tap Map'}
              </button>
            </div>
          </div>

          {/* Search Input for Location (Geocoding) */}
          <div style={{ position: 'relative' }}>
            <input
              type="text"
              placeholder="Search trailhead or town (e.g. Bear Brook)..."
              value={startQuery}
              onChange={(e) => handleStartSearch(e.target.value)}
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: 8,
                border: '1px solid var(--color-divider, #D1D8D8)',
                backgroundColor: 'var(--color-input-bg, #FFFFFF)',
                color: 'var(--color-text-primary, #1D3B34)',
                fontSize: 13
              }}
            />
            {isSearchingStart && (
              <span style={{ position: 'absolute', right: 10, top: 8, fontSize: 11, color: 'var(--color-text-secondary, #42675E)' }}>
                Searching...
              </span>
            )}

            {/* Geocode Results Dropdown */}
            {showStartResults && startResults.length > 0 && (
              <div
                style={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  right: 0,
                  marginTop: 4,
                  backgroundColor: 'var(--color-card-bg, #FFFFFF)',
                  border: '1px solid var(--color-divider, #D1D8D8)',
                  borderRadius: 8,
                  zIndex: 50,
                  maxHeight: 180,
                  overflowY: 'auto',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.15)'
                }}
              >
                {startResults.map((item, idx) => (
                  <div
                    key={idx}
                    className="start-geocode-item"
                    data-testid="start-geocode-item"
                    onClick={() => handleSelectStartLocation(item)}
                    style={{
                      padding: '8px 12px',
                      cursor: 'pointer',
                      borderBottom: '1px solid var(--color-divider, #E7ECEC)',
                      fontSize: 13,
                      color: 'var(--color-text-primary, #1D3B34)'
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--color-bg-subtle, #F3F7F7)'}
                    onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                  >
                    <div style={{ fontWeight: 600 }}>{item.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)' }}>{item.display_name}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Current Selected Location Indicator */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              backgroundColor: 'var(--color-bg-subtle, #F3F7F7)',
              padding: '6px 10px',
              borderRadius: 6,
              border: '1px solid var(--color-divider, #D1D8D8)',
              marginTop: 6,
              fontSize: 12
            }}
          >
            <span style={{ fontWeight: 600, color: 'var(--color-text-primary, #1D3B34)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              📍 {start.name || 'Custom Start Point'}
            </span>
            <span className="num-tabular" style={{ color: 'var(--color-text-secondary, #42675E)', fontSize: 11, flexShrink: 0, marginLeft: 8 }}>
              {start.lat.toFixed(4)}, {start.lon.toFixed(4)}
            </span>
          </div>
        </div>

        {/* End Location for Point-to-Point */}
        {routeMode === 'point_to_point' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <label style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
                Destination Location
              </label>
              <button
                type="button"
                onClick={() => onPickOnMap('end')}
                style={{
                  fontSize: 12,
                  padding: '2px 8px',
                  minHeight: 28,
                  backgroundColor: pickingTarget === 'end' ? 'var(--color-blaze, #FF5B14)' : 'var(--color-slate-light, #E2ECF3)',
                  color: pickingTarget === 'end' ? '#FFFFFF' : 'var(--color-text-primary, #1D3B34)'
                }}
              >
                {pickingTarget === 'end' ? 'Tap Map...' : 'Tap Map'}
              </button>
            </div>

            <div style={{ position: 'relative' }}>
              <input
                type="text"
                placeholder="Search destination trailhead..."
                value={endQuery}
                onChange={(e) => handleEndSearch(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  borderRadius: 8,
                  border: '1px solid var(--color-divider, #D1D8D8)',
                  backgroundColor: 'var(--color-input-bg, #FFFFFF)',
                  color: 'var(--color-text-primary, #1D3B34)',
                  fontSize: 13
                }}
              />
              {isSearchingEnd && (
                <span style={{ position: 'absolute', right: 10, top: 8, fontSize: 11, color: 'var(--color-text-secondary, #42675E)' }}>
                  Searching...
                </span>
              )}

              {showEndResults && endResults.length > 0 && (
                <div
                  style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    right: 0,
                    marginTop: 4,
                    backgroundColor: 'var(--color-card-bg, #FFFFFF)',
                    border: '1px solid var(--color-divider, #D1D8D8)',
                    borderRadius: 8,
                    zIndex: 50,
                    maxHeight: 180,
                    overflowY: 'auto',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.15)'
                  }}
                >
                  {endResults.map((item, idx) => (
                    <div
                      key={idx}
                      className="end-geocode-item"
                      data-testid="end-geocode-item"
                      onClick={() => handleSelectEndLocation(item)}
                      style={{
                        padding: '8px 12px',
                        cursor: 'pointer',
                        borderBottom: '1px solid var(--color-divider, #E7ECEC)',
                        fontSize: 13,
                        color: 'var(--color-text-primary, #1D3B34)'
                      }}
                      onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--color-bg-subtle, #F3F7F7)'}
                      onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                    >
                      <div style={{ fontWeight: 600 }}>{item.name}</div>
                      <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)' }}>{item.display_name}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {end && (
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  backgroundColor: 'var(--color-bg-subtle, #F3F7F7)',
                  padding: '6px 10px',
                  borderRadius: 6,
                  border: '1px solid var(--color-divider, #D1D8D8)',
                  marginTop: 6,
                  fontSize: 12
                }}
              >
                <span style={{ fontWeight: 600, color: 'var(--color-text-primary, #1D3B34)' }}>
                  🏁 {end.name || 'Custom End Point'}
                </span>
                <span className="num-tabular" style={{ color: 'var(--color-text-secondary, #42675E)', fontSize: 11 }}>
                  {end.lat.toFixed(4)}, {end.lon.toFixed(4)}
                </span>
              </div>
            )}
          </div>
        )}

        {/* Midpoints (point to point): the route passes through each, in order */}
        {routeMode === 'point_to_point' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <label style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
                Midpoints ({waypoints.length}/5)
              </label>
              <button
                type="button"
                disabled={waypoints.length >= 5}
                onClick={() => onPickOnMap('mid')}
                style={{
                  fontSize: 12, padding: '2px 8px', minHeight: 28,
                  backgroundColor: pickingTarget === 'mid' ? 'var(--color-blaze, #FF5B14)' : 'var(--color-slate-light, #E2ECF3)',
                  color: pickingTarget === 'mid' ? '#FFFFFF' : 'var(--color-text-primary, #1D3B34)'
                }}
              >
                {pickingTarget === 'mid' ? 'Tap Map...' : 'Add midpoint'}
              </button>
            </div>
            {waypoints.map((w, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'var(--color-bg-subtle, #F3F7F7)', padding: '4px 10px', borderRadius: 6, border: '1px solid var(--color-divider, #D1D8D8)', marginBottom: 4, fontSize: 12 }}>
                <span>{i + 1}. {w.name || 'Midpoint'}</span>
                <button
                  type="button"
                  aria-label={`Remove midpoint ${i + 1}`}
                  onClick={() => onWaypointsChange?.(waypoints.filter((_, k) => k !== i))}
                  style={{ minHeight: 28, minWidth: 28, padding: 0 }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 4. Target Distance in Miles (Strictly Miles!) */}
      <section>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
          <label style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
            Target Distance
          </label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <button
              type="button"
              onClick={() => onTargetMilesChange(Math.max(1, targetMiles - 1))}
              style={{ width: 28, height: 28, minHeight: 28, padding: 0, borderRadius: 4, backgroundColor: 'var(--color-card-bg, #FFFFFF)', border: '1px solid var(--color-divider, #D1D8D8)' }}
            >
              -
            </button>
            <span className="num-tabular" style={{ fontSize: 20, fontWeight: 700, color: 'var(--color-blaze, #FF5B14)', minWidth: 64, textAlign: 'center' }}>
              {targetMiles.toFixed(1)} mi
            </span>
            <button
              type="button"
              onClick={() => onTargetMilesChange(Math.min(50, targetMiles + 1))}
              style={{ width: 28, height: 28, minHeight: 28, padding: 0, borderRadius: 4, backgroundColor: 'var(--color-card-bg, #FFFFFF)', border: '1px solid var(--color-divider, #D1D8D8)' }}
            >
              +
            </button>
          </div>
        </div>
        <input
          type="range"
          min="1"
          max="35"
          step="0.5"
          value={targetMiles}
          onChange={(e) => onTargetMilesChange(parseFloat(e.target.value))}
          style={{ width: '100%', accentColor: 'var(--color-blaze, #FF5B14)' }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--color-text-secondary, #42675E)' }}>
          <span>1.0 mi (Quick spin)</span>
          <span>12.0 mi</span>
          <span>35.0 mi (Epic)</span>
        </div>
      </section>

      {/* 5. Terrain Mix Sliders & Presets */}
      <section>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
          <label style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
            Terrain Mix
          </label>
        </div>

        {/* Preset Chips */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
          {TERRAIN_PRESETS.map(preset => (
            <button
              key={preset.name}
              type="button"
              onClick={() => handleApplyTerrainPreset(preset.name)}
              style={{
                fontSize: 12,
                padding: '4px 10px',
                minHeight: 32,
                borderRadius: 6,
                backgroundColor: selectedPresetName === preset.name ? 'var(--color-header-bg, #1D3B34)' : 'var(--color-card-bg, #FFFFFF)',
                color: selectedPresetName === preset.name ? '#FFFFFF' : 'var(--color-text-primary, #1D3B34)',
                borderColor: selectedPresetName === preset.name ? 'var(--color-header-bg, #1D3B34)' : 'var(--color-divider, #D1D8D8)'
              }}
            >
              {preset.name}
            </button>
          ))}
        </div>

        {/* One stacked bar; drag a divider (or use the arrow keys on it) to shift terrain between neighbours */}
        <TerrainMixBar
          value={terrainPref}
          onChange={(next) => { setSelectedPresetName(''); onTerrainPrefChange(next); }}
        />
      </section>

      {/* 5b. Trust & DNR Settings */}
      <section style={{ backgroundColor: 'var(--color-bg-subtle, #F3F7F7)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary, #1D3B34)' }}>
          <input
            type="checkbox"
            checked={overrideDnr}
            onChange={(e) => onOverrideDnrChange?.(e.target.checked)}
            style={{ width: 16, height: 16, accentColor: 'var(--color-blaze, #FF5B14)' }}
          />
          <span>Allow Soft DNR Override (Warn & Log)</span>
        </label>
        <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)', marginTop: 4, paddingLeft: 24 }}>
          If enabled, routing may pass through soft user DNR segments when necessary, adding a warning and penalty. Hard closures remain strictly blocked.
        </div>
      </section>

      {/* 5c. Find New Trails Mode (Stage 6 Differentiator) */}
      <section style={{
        backgroundColor: findNewTrailsMode ? 'rgba(46, 111, 64, 0.15)' : 'var(--color-bg-subtle, #F3F7F7)',
        padding: '12px 14px',
        borderRadius: 8,
        border: `1px solid ${findNewTrailsMode ? 'var(--color-lichen, #81C784)' : 'var(--color-divider, #D1D8D8)'}`,
        transition: 'all 0.2s ease'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: findNewTrailsMode ? 10 : 0 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, fontWeight: 700, color: findNewTrailsMode ? 'var(--color-lichen, #2E6F40)' : 'var(--color-text-primary, #1D3B34)' }}>
            <input
              type="checkbox"
              checked={findNewTrailsMode}
              onChange={(e) => onFindNewTrailsModeChange?.(e.target.checked)}
              style={{ width: 16, height: 16, accentColor: '#2E6F40' }}
            />
            <span>✨ Find New Trails Mode</span>
          </label>
          {findNewTrailsMode && (
            <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-lichen, #2E6F40)' }}>
              {minNewTrailPercent}% unridden
            </span>
          )}
        </div>
        
        {findNewTrailsMode && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>
              <span>Minimum Unridden Trails Target:</span>
              <span className="num-tabular" style={{ fontWeight: 600 }}>{minNewTrailPercent}%</span>
            </div>
            <input
              type="range"
              min={10}
              max={80}
              step={5}
              value={minNewTrailPercent}
              onChange={(e) => onMinNewTrailPercentChange?.(Number(e.target.value))}
              style={{ width: '100%', accentColor: '#2E6F40' }}
            />
            <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)', marginTop: 2 }}>
              Highlights trails with strong recent heat that you have not yet ridden or run based on your activity history.
            </div>
          </div>
        )}
      </section>

      {/* 6. Primary Action: Build Routes */}
      <button
        type="button"
        onClick={onBuildRoutes}
        disabled={isLoading}
        className="btn-primary"
        style={{ width: '100%', marginTop: 8 }}
      >
        {isLoading ? 'Building Routes...' : 'Build Routes'}
      </button>

    </div>
  );
};

export default PlanPanel;
