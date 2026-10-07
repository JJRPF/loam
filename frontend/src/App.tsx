import React, { useState, useEffect } from 'react';
import type { 
  SportProfile, 
  TerrainPreference, 
  LatLon, 
  RouteResponse 
} from './types';
import {
  TERRAIN_PRESETS,
  NH_TRAILHEAD_PRESETS 
} from './types';
import { calculateRoute } from './services/api';
import { MapView } from './components/MapView';
import { PlanPanel } from './components/PlanPanel';
import { ResultsPanel } from './components/ResultsPanel';
import { SavedRoutesPanel } from './components/SavedRoutesPanel';
import { ExplorePanel } from './components/ExplorePanel';
import { YouPanel } from './components/YouPanel';

export const App: React.FC = () => {
  // Navigation tabs
  const [activeTab, setActiveTab] = useState<'plan' | 'results' | 'explore' | 'saved' | 'you'>('plan');
  
  // Mobile bottom sheet snap state ('peek' | 'half' | 'full')
  const [sheetSnap, setSheetSnap] = useState<'peek' | 'half' | 'full'>('half');
  const [isMobile, setIsMobile] = useState(window.innerWidth < 800);

  // Router Input State
  const [sport, setSport] = useState<SportProfile>('mtb_hardtail');
  const [start, setStart] = useState<LatLon>({
    lat: NH_TRAILHEAD_PRESETS[0].lat,
    lon: NH_TRAILHEAD_PRESETS[0].lon,
    name: NH_TRAILHEAD_PRESETS[0].name
  });
  const [end, setEnd] = useState<LatLon | undefined>(undefined);
  const [waypoints] = useState<LatLon[]>([]);
  const [routeMode, setRouteMode] = useState<'loop' | 'point_to_point' | 'out_and_back'>('loop');
  const [targetMiles, setTargetMiles] = useState<number>(10.0);
  const [terrainPref, setTerrainPref] = useState<TerrainPreference>(TERRAIN_PRESETS[0].weights);

  // Route calculation and results
  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [scrubCoord, setScrubCoord] = useState<[number, number] | null>(null);
  const [pickingTarget, setPickingTarget] = useState<'start' | 'end' | null>(null);

  // Responsive listener
  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth < 800);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Handle map click for selecting points
  const handleMapClick = (lat: number, lon: number) => {
    if (pickingTarget === 'start') {
      setStart({ lat, lon, name: `Custom Start (${lat.toFixed(4)}, ${lon.toFixed(4)})` });
      setPickingTarget(null);
    } else if (pickingTarget === 'end') {
      setEnd({ lat, lon, name: `Custom End (${lat.toFixed(4)}, ${lon.toFixed(4)})` });
      setPickingTarget(null);
    }
  };

  const handleBuildRoutes = async () => {
    setIsLoading(true);
    try {
      const result = await calculateRoute({
        start,
        end: routeMode === 'point_to_point' ? end : undefined,
        waypoints,
        profile: sport,
        terrainPreference: terrainPref,
        isLoop: routeMode === 'loop',
        routeMode,
        targetDistanceMiles: targetMiles,
        name: `${start.name || 'Loam'} ${sport.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())} ${routeMode === 'loop' ? 'Loop' : 'Route'}`
      });
      setRoute(result);
      setActiveTab('results');
      if (isMobile) {
        setSheetSnap('half');
      }
    } catch (e: any) {
      alert(`Route calculation failed: ${e.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleLoadSavedRoute = (savedRoute: RouteResponse) => {
    setRoute(savedRoute);
    if (savedRoute.coordinates && savedRoute.coordinates.length > 0) {
      setStart({
        lat: savedRoute.coordinates[0][1],
        lon: savedRoute.coordinates[0][0],
        name: savedRoute.name
      });
    }
    setActiveTab('results');
    if (isMobile) {
      setSheetSnap('half');
    }
  };

  // Bottom Sheet height mapping
  const getSheetHeight = () => {
    switch (sheetSnap) {
      case 'peek': return '110px';
      case 'half': return '52vh';
      case 'full': return '88vh';
    }
  };

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh', overflow: 'hidden', position: 'relative' }}>
      
      {/* =========================================================================
          DESKTOP SIDEBAR PANEL (400px fixed width on >= 800px)
         ========================================================================= */}
      {!isMobile && (
        <aside
          style={{
            width: 400,
            minWidth: 400,
            height: '100%',
            backgroundColor: '#E7ECEC',
            borderRight: '1px solid #D1D8D8',
            display: 'flex',
            flexDirection: 'column',
            zIndex: 10,
            boxShadow: '2px 0 8px rgba(0,0,0,0.06)'
          }}
        >
          {/* Header */}
          <header
            style={{
              padding: '16px 20px',
              backgroundColor: '#1D3B34',
              color: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between'
            }}
          >
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.5px' }}>Loam</span>
                <span style={{ fontSize: 11, backgroundColor: '#A9BF7A', color: '#1D3B34', fontWeight: 700, padding: '2px 6px', borderRadius: 4 }}>
                  NH MVP
                </span>
              </div>
              <div style={{ fontSize: 12, color: '#A9BF7A', marginTop: 2 }}>
                Trail Route Builder • Atkinson Hyperlegible
              </div>
            </div>
            {route && (
              <span className="num-tabular" style={{ fontSize: 13, color: '#FFFFFF', backgroundColor: 'rgba(255,255,255,0.15)', padding: '4px 8px', borderRadius: 6 }}>
                {route.distance_miles.toFixed(1)} mi
              </span>
            )}
          </header>

          {/* Desktop Navigation Tabs */}
          <nav
            style={{
              display: 'flex',
              borderBottom: '1px solid #D1D8D8',
              backgroundColor: '#FFFFFF'
            }}
          >
            {[
              { id: 'plan', label: 'Plan' },
              { id: 'results', label: route ? 'Results' : 'Route' },
              { id: 'explore', label: 'Explore' },
              { id: 'saved', label: 'Saved' },
              { id: 'you', label: 'You' }
            ].map(tab => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id as any)}
                style={{
                  flex: 1,
                  padding: '12px 0',
                  minHeight: 44,
                  fontSize: 14,
                  fontWeight: activeTab === tab.id ? 700 : 500,
                  backgroundColor: 'transparent',
                  color: activeTab === tab.id ? '#FF5B14' : '#1D3B34',
                  border: 'none',
                  borderBottom: activeTab === tab.id ? '3px solid #FF5B14' : '3px solid transparent',
                  borderRadius: 0
                }}
              >
                {tab.label}
              </button>
            ))}
          </nav>

          {/* Tab Content Body */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
            {activeTab === 'plan' && (
              <PlanPanel
                sport={sport}
                onSportChange={setSport}
                start={start}
                onStartChange={setStart}
                end={end}
                onEndChange={setEnd}
                routeMode={routeMode}
                onRouteChange={setRouteMode}
                targetMiles={targetMiles}
                onTargetMilesChange={setTargetMiles}
                terrainPref={terrainPref}
                onTerrainPrefChange={setTerrainPref}
                onBuildRoutes={handleBuildRoutes}
                isLoading={isLoading}
                onPickOnMap={(target) => setPickingTarget(target)}
                pickingTarget={pickingTarget}
              />
            )}

            {activeTab === 'results' && route && (
              <ResultsPanel
                route={route}
                onBackToPlan={() => setActiveTab('plan')}
                onScrubCoord={setScrubCoord}
                onRouteSaved={() => {}}
              />
            )}

            {activeTab === 'results' && !route && (
              <div style={{ padding: 24, textAlign: 'center', backgroundColor: '#FFFFFF', borderRadius: 8 }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: '#1D3B34', marginBottom: 4 }}>
                  No active route
                </div>
                <div style={{ fontSize: 13, color: '#42675E', marginBottom: 16 }}>
                  Configure your starting point and terrain preferences in the Plan tab, then tap "Build Routes".
                </div>
                <button
                  type="button"
                  onClick={() => setActiveTab('plan')}
                  className="btn-primary"
                  style={{ width: '100%' }}
                >
                  Go to Plan
                </button>
              </div>
            )}

            {activeTab === 'explore' && <ExplorePanel />}
            {activeTab === 'saved' && <SavedRoutesPanel onLoadRoute={handleLoadSavedRoute} />}
            {activeTab === 'you' && <YouPanel />}
          </div>
        </aside>
      )}

      {/* =========================================================================
          FULL BLEED MAPLIBRE MAP CANVAS (100% viewport)
         ========================================================================= */}
      <main style={{ flex: 1, height: '100%', position: 'relative' }}>
        <MapView
          route={route}
          start={start}
          end={end}
          waypoints={waypoints}
          scrubCoord={scrubCoord}
          onMapClick={handleMapClick}
        />

        {/* Picking Location Banner */}
        {pickingTarget && (
          <div
            style={{
              position: 'absolute',
              top: 16,
              left: '50%',
              transform: 'translateX(-50%)',
              backgroundColor: '#FF5B14',
              color: '#FFFFFF',
              padding: '8px 16px',
              borderRadius: 20,
              fontSize: 14,
              fontWeight: 700,
              boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
              zIndex: 20
            }}
          >
            Tap map to set {pickingTarget === 'start' ? 'Starting Location' : 'Destination'}
          </div>
        )}
      </main>

      {/* =========================================================================
          MOBILE ADAPTIVE BOTTOM SHEET (< 800px)
         ========================================================================= */}
      {isMobile && (
        <section
          style={{
            position: 'absolute',
            bottom: 0,
            left: 0,
            right: 0,
            height: getSheetHeight(),
            backgroundColor: '#E7ECEC',
            borderTopLeftRadius: 16,
            borderTopRightRadius: 16,
            boxShadow: '0 -4px 16px rgba(0,0,0,0.18)',
            display: 'flex',
            flexDirection: 'column',
            zIndex: 30,
            transition: 'height 0.25s cubic-bezier(0.2, 0.8, 0.2, 1)'
          }}
        >
          {/* Bottom Sheet Drag Handle & Snap Controls */}
          <div
            style={{
              padding: '8px 16px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              cursor: 'pointer',
              userSelect: 'none'
            }}
            onClick={() => {
              if (sheetSnap === 'peek') setSheetSnap('half');
              else if (sheetSnap === 'half') setSheetSnap('full');
              else setSheetSnap('peek');
            }}
          >
            <div
              style={{
                width: 36,
                height: 4,
                backgroundColor: '#9BA8A8',
                borderRadius: 2,
                marginBottom: 6
              }}
            />
            {/* Peek Bar Summary */}
            {sheetSnap === 'peek' && (
              <div style={{ display: 'flex', width: '100%', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: '#1D3B34' }}>
                  {route ? `${route.distance_miles.toFixed(1)} mi • ${route.name}` : `${start.name || 'Bear Brook'} (${targetMiles} mi)`}
                </div>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (!route) handleBuildRoutes();
                    else setSheetSnap('half');
                  }}
                  className="btn-primary"
                  style={{ minHeight: 36, padding: '4px 12px', fontSize: 13 }}
                >
                  {route ? 'Inspect' : 'Build'}
                </button>
              </div>
            )}
          </div>

          {/* Sheet Scrollable Content (visible on half & full snap) */}
          {sheetSnap !== 'peek' && (
            <div style={{ flex: 1, overflowY: 'auto', padding: '0 16px 12px 16px' }}>
              {activeTab === 'plan' && (
                <PlanPanel
                  sport={sport}
                  onSportChange={setSport}
                  start={start}
                  onStartChange={setStart}
                  end={end}
                  onEndChange={setEnd}
                  routeMode={routeMode}
                  onRouteChange={setRouteMode}
                  targetMiles={targetMiles}
                  onTargetMilesChange={setTargetMiles}
                  terrainPref={terrainPref}
                  onTerrainPrefChange={setTerrainPref}
                  onBuildRoutes={handleBuildRoutes}
                  isLoading={isLoading}
                  onPickOnMap={(target) => {
                    setPickingTarget(target);
                    setSheetSnap('peek');
                  }}
                  pickingTarget={pickingTarget}
                />
              )}

              {activeTab === 'results' && route && (
                <ResultsPanel
                  route={route}
                  onBackToPlan={() => setActiveTab('plan')}
                  onScrubCoord={setScrubCoord}
                  onRouteSaved={() => {}}
                />
              )}

              {activeTab === 'results' && !route && (
                <div style={{ padding: 24, textAlign: 'center', backgroundColor: '#FFFFFF', borderRadius: 8 }}>
                  <div style={{ fontSize: 16, fontWeight: 700, color: '#1D3B34', marginBottom: 4 }}>
                    No active route
                  </div>
                  <button
                    type="button"
                    onClick={() => setActiveTab('plan')}
                    className="btn-primary"
                    style={{ width: '100%', marginTop: 8 }}
                  >
                    Go to Plan
                  </button>
                </div>
              )}

              {activeTab === 'explore' && <ExplorePanel />}
              {activeTab === 'saved' && <SavedRoutesPanel onLoadRoute={handleLoadSavedRoute} />}
              {activeTab === 'you' && <YouPanel />}
            </div>
          )}

          {/* Bottom Tabs Bar (Plan, Explore, Saved, You) */}
          <nav
            style={{
              display: 'flex',
              borderTop: '1px solid #D1D8D8',
              backgroundColor: '#FFFFFF',
              minHeight: 52
            }}
          >
            {[
              { id: 'plan', label: 'Plan' },
              { id: 'results', label: route ? 'Results' : 'Route' },
              { id: 'explore', label: 'Explore' },
              { id: 'saved', label: 'Saved' },
              { id: 'you', label: 'You' }
            ].map(tab => (
              <button
                key={tab.id}
                type="button"
                onClick={() => {
                  setActiveTab(tab.id as any);
                  if (sheetSnap === 'peek') setSheetSnap('half');
                }}
                style={{
                  flex: 1,
                  fontSize: 13,
                  fontWeight: activeTab === tab.id ? 700 : 500,
                  backgroundColor: 'transparent',
                  color: activeTab === tab.id ? '#FF5B14' : '#1D3B34',
                  border: 'none',
                  borderTop: activeTab === tab.id ? '3px solid #FF5B14' : '3px solid transparent',
                  borderRadius: 0,
                  padding: '8px 0'
                }}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </section>
      )}

    </div>
  );
};

export default App;
