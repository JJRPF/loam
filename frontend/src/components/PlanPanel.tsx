import React, { useState } from 'react';
import type { 
  SportProfile, 
  TerrainPreference, 
  LatLon, 
  TrailheadPreset
} from '../types';
import { 
  NH_TRAILHEAD_PRESETS, 
  TERRAIN_PRESETS
} from '../types';

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
  onPickOnMap: (target: 'start' | 'end') => void;
  pickingTarget: 'start' | 'end' | null;
  overrideDnr?: boolean;
  onOverrideDnrChange?: (override: boolean) => void;
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
  overrideDnr = false,
  onOverrideDnrChange
}) => {
  const [selectedPresetName, setSelectedPresetName] = useState<string>("Mostly Trail");

  const handleApplyTerrainPreset = (presetName: string) => {
    const found = TERRAIN_PRESETS.find(p => p.name === presetName);
    if (found) {
      setSelectedPresetName(presetName);
      onTerrainPrefChange(found.weights);
    }
  };

  const handleSelectTrailhead = (preset: TrailheadPreset) => {
    onStartChange({
      lat: preset.lat,
      lon: preset.lon,
      name: preset.name
    });
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
          alert(`Location access failed: ${err.message}. Defaulting to Bear Brook Trailhead.`);
        }
      );
    }
  };

  const isBike = sport.startsWith('mtb') || sport === 'bike';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '4px 0 24px 0' }}>
      
      {/* 1. Sport Mode Selector */}
      <section>
        <label style={{ display: 'block', fontSize: 13, fontWeight: 700, color: '#1D3B34', marginBottom: 6 }}>
          Sport Mode
        </label>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <button
            type="button"
            onClick={() => onSportChange('mtb_hardtail')}
            className={isBike ? 'btn-primary' : 'btn-secondary'}
            style={{
              flex: 1,
              backgroundColor: isBike ? '#1D3B34' : '#FFFFFF',
              color: isBike ? '#FFFFFF' : '#1D3B34',
              borderColor: '#D1D8D8'
            }}
          >
            Mountain Bike
          </button>
          <button
            type="button"
            onClick={() => onSportChange('trail_run')}
            className={!isBike ? 'btn-primary' : 'btn-secondary'}
            style={{
              flex: 1,
              backgroundColor: !isBike ? '#1D3B34' : '#FFFFFF',
              color: !isBike ? '#FFFFFF' : '#1D3B34',
              borderColor: '#D1D8D8'
            }}
          >
            Trail Run
          </button>
        </div>

        {/* MTB Subtypes */}
        {isBike && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {[
              { id: 'mtb_hardtail', label: 'Hardtail' },
              { id: 'mtb_fullsus', label: 'Full-Sus' },
              { id: 'mtb_gravel', label: 'Gravel' },
              { id: 'mtb_fat', label: 'Fat Bike' },
              { id: 'mtb_emtb', label: 'eMTB' }
            ].map(sub => (
              <button
                key={sub.id}
                type="button"
                onClick={() => onSportChange(sub.id as SportProfile)}
                style={{
                  padding: '6px 12px',
                  minHeight: 36,
                  fontSize: 13,
                  fontWeight: sport === sub.id ? 700 : 500,
                  backgroundColor: sport === sub.id ? '#3F6C8F' : '#F3F7F7',
                  color: sport === sub.id ? '#FFFFFF' : '#1D3B34',
                  border: '1px solid',
                  borderColor: sport === sub.id ? '#3F6C8F' : '#D1D8D8',
                  borderRadius: 6
                }}
              >
                {sub.label}
              </button>
            ))}
          </div>
        )}
      </section>

      {/* 2. Route Mode: Loop / Round Trip vs Point to Point */}
      <section>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <label style={{ fontSize: 13, fontWeight: 700, color: '#1D3B34' }}>
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
                backgroundColor: routeMode === m.id ? '#2A4F46' : '#FFFFFF',
                color: routeMode === m.id ? '#FFFFFF' : '#1D3B34',
                borderColor: routeMode === m.id ? '#2A4F46' : '#D1D8D8',
                borderRadius: 6
              }}
            >
              {m.label}
            </button>
          ))}
        </div>
      </section>

      {/* 3. Trailhead & Locations */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <label style={{ fontSize: 13, fontWeight: 700, color: '#1D3B34' }}>
              Starting Location
            </label>
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                type="button"
                onClick={handleLocateMe}
                style={{ fontSize: 12, padding: '2px 8px', minHeight: 28, backgroundColor: '#E2ECF3', color: '#1D3B34' }}
              >
                GPS
              </button>
              <button
                type="button"
                onClick={() => onPickOnMap('start')}
                style={{
                  fontSize: 12,
                  padding: '2px 8px',
                  minHeight: 28,
                  backgroundColor: pickingTarget === 'start' ? '#FF5B14' : '#E2ECF3',
                  color: pickingTarget === 'start' ? '#FFFFFF' : '#1D3B34'
                }}
              >
                {pickingTarget === 'start' ? 'Tap Map...' : 'Tap Map'}
              </button>
            </div>
          </div>

          {/* Quick Trailheads */}
          <select
            value={start.name || ''}
            onChange={(e) => {
              const th = NH_TRAILHEAD_PRESETS.find(p => p.name === e.target.value);
              if (th) handleSelectTrailhead(th);
            }}
            style={{
              width: '100%',
              padding: '10px 12px',
              borderRadius: 8,
              border: '1px solid #D1D8D8',
              backgroundColor: '#FFFFFF',
              color: '#1D3B34',
              fontSize: 14,
              fontWeight: 600
            }}
          >
            {NH_TRAILHEAD_PRESETS.map(th => (
              <option key={th.name} value={th.name}>
                {th.name} ({th.region})
              </option>
            ))}
          </select>
          <div style={{ fontSize: 11, color: '#42675E', marginTop: 4 }}>
            {start.lat.toFixed(4)}, {start.lon.toFixed(4)}
          </div>
        </div>

        {/* End Location for Point-to-Point */}
        {routeMode === 'point_to_point' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <label style={{ fontSize: 13, fontWeight: 700, color: '#1D3B34' }}>
                End Location
              </label>
              <button
                type="button"
                onClick={() => onPickOnMap('end')}
                style={{
                  fontSize: 12,
                  padding: '2px 8px',
                  minHeight: 28,
                  backgroundColor: pickingTarget === 'end' ? '#FF5B14' : '#E2ECF3',
                  color: pickingTarget === 'end' ? '#FFFFFF' : '#1D3B34'
                }}
              >
                {pickingTarget === 'end' ? 'Tap Map...' : 'Tap Map'}
              </button>
            </div>
            <select
              value={end?.name || ''}
              onChange={(e) => {
                const th = NH_TRAILHEAD_PRESETS.find(p => p.name === e.target.value);
                if (th) onEndChange({ lat: th.lat, lon: th.lon, name: th.name });
              }}
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: 8,
                border: '1px solid #D1D8D8',
                backgroundColor: '#FFFFFF',
                color: '#1D3B34',
                fontSize: 14,
                fontWeight: 600
              }}
            >
              <option value="">Select Destination Trailhead...</option>
              {NH_TRAILHEAD_PRESETS.map(th => (
                <option key={th.name} value={th.name}>
                  {th.name} ({th.region})
                </option>
              ))}
            </select>
          </div>
        )}
      </section>

      {/* 4. Target Distance in Miles (Strictly Miles!) */}
      <section>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
          <label style={{ fontSize: 13, fontWeight: 700, color: '#1D3B34' }}>
            Target Distance
          </label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <button
              type="button"
              onClick={() => onTargetMilesChange(Math.max(1, targetMiles - 1))}
              style={{ width: 28, height: 28, minHeight: 28, padding: 0, borderRadius: 4, backgroundColor: '#FFFFFF', border: '1px solid #D1D8D8' }}
            >
              -
            </button>
            <span className="num-tabular" style={{ fontSize: 20, fontWeight: 700, color: '#FF5B14', minWidth: 64, textAlign: 'center' }}>
              {targetMiles.toFixed(1)} mi
            </span>
            <button
              type="button"
              onClick={() => onTargetMilesChange(Math.min(50, targetMiles + 1))}
              style={{ width: 28, height: 28, minHeight: 28, padding: 0, borderRadius: 4, backgroundColor: '#FFFFFF', border: '1px solid #D1D8D8' }}
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
          style={{ width: '100%', accentColor: '#FF5B14' }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#42675E' }}>
          <span>1.0 mi (Quick spin)</span>
          <span>12.0 mi</span>
          <span>35.0 mi (Epic)</span>
        </div>
      </section>

      {/* 5. Terrain Mix Sliders & Presets */}
      <section>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
          <label style={{ fontSize: 13, fontWeight: 700, color: '#1D3B34' }}>
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
                backgroundColor: selectedPresetName === preset.name ? '#1D3B34' : '#FFFFFF',
                color: selectedPresetName === preset.name ? '#FFFFFF' : '#1D3B34',
                borderColor: selectedPresetName === preset.name ? '#1D3B34' : '#D1D8D8'
              }}
            >
              {preset.name}
            </button>
          ))}
        </div>

        {/* Segmented Terrain Visual Preview Bar */}
        <div style={{ display: 'flex', height: 10, borderRadius: 5, overflow: 'hidden', marginBottom: 12, backgroundColor: '#E0E0E0' }}>
          <div style={{ width: `${terrainPref.singletrack * 100}%`, backgroundColor: '#2E6F40' }} title="Singletrack" />
          <div style={{ width: `${terrainPref.doubletrack * 100}%`, backgroundColor: '#8D6E63' }} title="Doubletrack" />
          <div style={{ width: `${terrainPref.gravel * 100}%`, backgroundColor: '#D4A373' }} title="Gravel" />
          <div style={{ width: `${terrainPref.paved * 100}%`, backgroundColor: '#78909C' }} title="Paved" />
        </div>

        {/* Individual Adjusters */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[
            { key: 'singletrack', label: 'Singletrack', color: '#2E6F40' },
            { key: 'doubletrack', label: 'Doubletrack', color: '#8D6E63' },
            { key: 'gravel', label: 'Gravel', color: '#D4A373' },
            { key: 'paved', label: 'Paved / Road', color: '#78909C' }
          ].map(t => {
            const val = (terrainPref as any)[t.key] as number;
            return (
              <div key={t.key} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 13 }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, backgroundColor: t.color }} />
                  {t.label}
                </span>
                <span className="num-tabular" style={{ fontWeight: 600, color: '#1D3B34' }}>
                  {Math.round(val * 100)}%
                </span>
              </div>
            );
          })}
        </div>
      </section>

      {/* 5b. Trust & DNR Settings */}
      <section style={{ backgroundColor: '#F3F7F7', padding: '10px 12px', borderRadius: 8, border: '1px solid #D1D8D8' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#1D3B34' }}>
          <input
            type="checkbox"
            checked={overrideDnr}
            onChange={(e) => onOverrideDnrChange?.(e.target.checked)}
            style={{ width: 16, height: 16, accentColor: '#FF5B14' }}
          />
          <span>Allow Soft DNR Override (Warn & Log)</span>
        </label>
        <div style={{ fontSize: 11, color: '#42675E', marginTop: 4, paddingLeft: 24 }}>
          If enabled, routing may pass through soft user DNR segments when necessary, adding a warning and penalty. Hard closures remain strictly blocked.
        </div>
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
