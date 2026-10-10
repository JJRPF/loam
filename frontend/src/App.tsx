import React, { useState, useEffect } from 'react';
import type { 
  SportProfile, 
  TerrainPreference, 
  LatLon, 
  RouteResponse 
} from './types';
import {
  TERRAIN_PRESETS
} from './types';
import { calculateRoute, streamRouteOptions } from './services/api';
import { MapView } from './components/MapView';
import { PlanPanel } from './components/PlanPanel';
import { ResultsPanel } from './components/ResultsPanel';
import { SavedRoutesPanel } from './components/SavedRoutesPanel';
import { ExplorePanel } from './components/ExplorePanel';
import { YouPanel } from './components/YouPanel';
import { DevToolsPage } from './components/DevToolsPage';
import { ErrorBoundary } from './components/ErrorBoundary';

export const App: React.FC = () => {
  // Dark mode state
  const [isDarkMode, setIsDarkMode] = useState<boolean>(() => {
    return localStorage.getItem('loam_theme') === 'dark';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', isDarkMode ? 'dark' : 'light');
    localStorage.setItem('loam_theme', isDarkMode ? 'dark' : 'light');
  }, [isDarkMode]);

  // Separate Dev Tools page route state
  const [isDevRoute, setIsDevRoute] = useState<boolean>(() => {
    return window.location.hash === '#/dev' || window.location.pathname === '/dev';
  });

  useEffect(() => {
    const handleLocationChange = () => {
      setIsDevRoute(window.location.hash === '#/dev' || window.location.pathname === '/dev');
    };
    window.addEventListener('hashchange', handleLocationChange);
    window.addEventListener('popstate', handleLocationChange);
    return () => {
      window.removeEventListener('hashchange', handleLocationChange);
      window.removeEventListener('popstate', handleLocationChange);
    };
  }, []);

  // Navigation tabs
  const [activeTab, setActiveTab] = useState<'plan' | 'results' | 'explore' | 'saved' | 'you'>('plan');
  
  // Mobile bottom sheet snap state ('peek' | 'half' | 'full')
  const [sheetSnap, setSheetSnap] = useState<'peek' | 'half' | 'full'>('half');
  const [isMobile, setIsMobile] = useState(window.innerWidth < 800);

  // Router Input State
  const [sport, setSport] = useState<SportProfile>('mtb');
  const [start, setStart] = useState<LatLon>({
    lat: 43.1305,
    lon: -71.3524,
    name: "Bear Brook State Park"
  });
  const [end, setEnd] = useState<LatLon | undefined>(undefined);
  const [waypoints] = useState<LatLon[]>([]);
  const [routeMode, setRouteMode] = useState<'loop' | 'point_to_point' | 'out_and_back'>('loop');
  const [targetMiles, setTargetMiles] = useState<number>(10.0);
  const [terrainPref, setTerrainPref] = useState<TerrainPreference>(TERRAIN_PRESETS[0].weights);
  const [overrideDnr, setOverrideDnr] = useState<boolean>(false);

  // Stage 6: Differentiators state
  const [findNewTrailsMode, setFindNewTrailsMode] = useState<boolean>(false);
  const [minNewTrailPercent, setMinNewTrailPercent] = useState<number>(30);
  const [trailRunSteeperGrades, setTrailRunSteeperGrades] = useState<boolean>(true);
  const [trailRunAvoidMtbFlow, setTrailRunAvoidMtbFlow] = useState<boolean>(true);

  // Route calculation and results
  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [options, setOptions] = useState<RouteResponse[]>([]);
  const [hoverRoute, setHoverRoute] = useState<RouteResponse | null>(null);
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

  const handleBuildRoutes = () => {
    setIsLoading(true);
    setOptions([]);
    setRoute(null);
    setActiveTab('results');
    if (isMobile) {
      setSheetSnap('half');
    }

    streamRouteOptions(
      {
        start,
        end: routeMode === 'point_to_point' ? end : undefined,
        waypoints,
        profile: sport,
        terrainPreference: terrainPref,
        isLoop: routeMode === 'loop',
        routeMode,
        targetDistanceMiles: targetMiles,
        name: `${start.name || 'Loam'} ${sport.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())} ${routeMode === 'loop' ? 'Loop' : 'Route'}`,
        candidateCount: 10,
        overrideDnr,
        findNewTrailsMode,
        minNewTrailPercent,
        trailRunSteeperGrades,
        trailRunAvoidMtbFlow
      },
      {
        onCandidate: (cand) => {
          setOptions(prev => {
            const next = [...prev, cand];
            if (prev.length === 0) {
              setRoute(cand); // First resolved option becomes active
            }
            return next;
          });
        },
        onComplete: () => {
          setIsLoading(false);
        },
        onError: (err) => {
          console.error('Route options stream error:', err);
          setIsLoading(false);
          // Fallback to single calculation if stream fails
          calculateRoute({
            start,
            end: routeMode === 'point_to_point' ? end : undefined,
            waypoints,
            profile: sport,
            terrainPreference: terrainPref,
            isLoop: routeMode === 'loop',
            routeMode,
            targetDistanceMiles: targetMiles,
            name: `${start.name || 'Loam'} ${sport.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())} ${routeMode === 'loop' ? 'Loop' : 'Route'}`,
            overrideDnr,
            findNewTrailsMode,
            minNewTrailPercent,
            trailRunSteeperGrades,
            trailRunAvoidMtbFlow
          }).then(res => {
            setRoute(res);
            setOptions([res]);
          }).catch(e => alert(`Route calculation failed: ${e.message}`));
        }
      }
    );
  };

  const handleLoadSavedRoute = (savedRoute: RouteResponse) => {
    setRoute(savedRoute);
    setOptions([savedRoute]);
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

  if (isDevRoute) {
    return (
      <DevToolsPage
        onBack={() => {
          window.location.hash = '';
          setIsDevRoute(false);
        }}
        isDarkMode={isDarkMode}
      />
    );
  }

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
            backgroundColor: 'var(--color-panel-bg, #E7ECEC)',
            borderRight: '1px solid var(--color-divider, #D1D8D8)',
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
              backgroundColor: 'var(--color-header-bg, #1D3B34)',
              color: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <img
                src="/brand/loam-logo-horizontal-reversed.svg"
                alt="loam"
                style={{ height: 28, width: 'auto', display: 'block' }}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {route && (
                <span className="num-tabular" style={{ fontSize: 13, color: '#FFFFFF', backgroundColor: 'rgba(255,255,255,0.15)', padding: '4px 8px', borderRadius: 6 }}>
                  {route.distance_miles.toFixed(1)} mi
                </span>
              )}
              {/* Dark mode button */}
              <button
                type="button"
                onClick={() => setIsDarkMode(!isDarkMode)}
                style={{
                  backgroundColor: 'rgba(255,255,255,0.15)',
                  border: 'none',
                  borderRadius: 6,
                  color: '#FFFFFF',
                  padding: '4px 8px',
                  minHeight: 30,
                  fontSize: 14
                }}
                title={isDarkMode ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
              >
                {isDarkMode ? '🌙' : '☀️'}
              </button>
            </div>
          </header>

          {/* Desktop Navigation Tabs */}
          <nav
            style={{
              display: 'flex',
              borderBottom: '1px solid var(--color-divider, #D1D8D8)',
              backgroundColor: 'var(--color-nav-bg, #FFFFFF)'
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
                  color: activeTab === tab.id ? 'var(--color-blaze, #FF5B14)' : 'var(--color-text-primary, #1D3B34)',
                  border: 'none',
                  borderBottom: activeTab === tab.id ? '3px solid var(--color-blaze, #FF5B14)' : '3px solid transparent',
                  borderRadius: 0
                }}
              >
                {tab.label}
              </button>
            ))}
          </nav>

          {/* Tab Content Body */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
            <ErrorBoundary fallbackTitle="Panel Error" onReset={() => setActiveTab('plan')}>
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
                  overrideDnr={overrideDnr}
                  onOverrideDnrChange={setOverrideDnr}
                  findNewTrailsMode={findNewTrailsMode}
                  onFindNewTrailsModeChange={setFindNewTrailsMode}
                  minNewTrailPercent={minNewTrailPercent}
                  onMinNewTrailPercentChange={setMinNewTrailPercent}
                  trailRunSteeperGrades={trailRunSteeperGrades}
                  onTrailRunSteeperGradesChange={setTrailRunSteeperGrades}
                  trailRunAvoidMtbFlow={trailRunAvoidMtbFlow}
                  onTrailRunAvoidMtbFlowChange={setTrailRunAvoidMtbFlow}
                />
              )}

              {activeTab === 'results' && (
                <ResultsPanel
                  route={route}
                  options={options}
                  onSelectRoute={setRoute}
                  onHoverRoute={setHoverRoute}
                  onBackToPlan={() => setActiveTab('plan')}
                  onScrubCoord={setScrubCoord}
                  onRouteSaved={() => {}}
                  isLoading={isLoading}
                />
              )}

              {activeTab === 'explore' && <ExplorePanel />}
              {activeTab === 'saved' && <SavedRoutesPanel onLoadRoute={handleLoadSavedRoute} />}
              {activeTab === 'you' && (
                <YouPanel
                  isDarkMode={isDarkMode}
                  onToggleDarkMode={() => setIsDarkMode(!isDarkMode)}
                />
              )}
            </ErrorBoundary>
          </div>
        </aside>
      )}

      {/* =========================================================================
          FULL BLEED MAPLIBRE MAP CANVAS (100% viewport)
         ========================================================================= */}
      <main style={{ flex: 1, height: '100%', position: 'relative' }}>
        <MapView
          route={route || (options.length > 0 ? options[0] : null)}
          hoverRoute={hoverRoute}
          start={start}
          end={end}
          waypoints={waypoints}
          scrubCoord={scrubCoord}
          onMapClick={handleMapClick}
          isDarkMode={isDarkMode}
        />

        {/* Picking Location Banner */}
        {pickingTarget && (
          <div
            style={{
              position: 'absolute',
              top: 16,
              left: '50%',
              transform: 'translateX(-50%)',
              backgroundColor: 'var(--color-blaze, #FF5B14)',
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
            backgroundColor: 'var(--color-panel-bg, #E7ECEC)',
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
                backgroundColor: 'var(--color-divider, #9BA8A8)',
                borderRadius: 2,
                marginBottom: 6
              }}
            />
            {/* Peek Bar Summary */}
            {sheetSnap === 'peek' && (
              <div style={{ display: 'flex', width: '100%', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, overflow: 'hidden' }}>
                  <img src="/brand/loam-icon.svg" alt="Loam" style={{ width: 20, height: 20, flexShrink: 0 }} />
                  <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {route ? `${route.distance_miles.toFixed(1)} mi • ${route.name}` : `${start.name || 'Bear Brook'} (${targetMiles} mi)`}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setIsDarkMode(!isDarkMode);
                    }}
                    style={{ minHeight: 32, padding: '2px 8px', fontSize: 12, backgroundColor: 'transparent', border: '1px solid var(--color-divider)' }}
                  >
                    {isDarkMode ? '🌙' : '☀️'}
                  </button>
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
              </div>
            )}
          </div>

          {/* Sheet Scrollable Content (visible on half & full snap) */}
          {sheetSnap !== 'peek' && (
            <div style={{ flex: 1, overflowY: 'auto', padding: '0 16px 12px 16px' }}>
              <ErrorBoundary fallbackTitle="Panel Error" onReset={() => setActiveTab('plan')}>
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
                    overrideDnr={overrideDnr}
                    onOverrideDnrChange={setOverrideDnr}
                    findNewTrailsMode={findNewTrailsMode}
                    onFindNewTrailsModeChange={setFindNewTrailsMode}
                    minNewTrailPercent={minNewTrailPercent}
                    onMinNewTrailPercentChange={setMinNewTrailPercent}
                    trailRunSteeperGrades={trailRunSteeperGrades}
                    onTrailRunSteeperGradesChange={setTrailRunSteeperGrades}
                    trailRunAvoidMtbFlow={trailRunAvoidMtbFlow}
                    onTrailRunAvoidMtbFlowChange={setTrailRunAvoidMtbFlow}
                  />
                )}

                {activeTab === 'results' && (
                  <ResultsPanel
                    route={route}
                    options={options}
                    onSelectRoute={setRoute}
                    onHoverRoute={setHoverRoute}
                    onBackToPlan={() => setActiveTab('plan')}
                    onScrubCoord={setScrubCoord}
                    onRouteSaved={() => {}}
                    isLoading={isLoading}
                  />
                )}

                {activeTab === 'explore' && <ExplorePanel />}
                {activeTab === 'saved' && <SavedRoutesPanel onLoadRoute={handleLoadSavedRoute} />}
                {activeTab === 'you' && (
                  <YouPanel
                    isDarkMode={isDarkMode}
                    onToggleDarkMode={() => setIsDarkMode(!isDarkMode)}
                  />
                )}
              </ErrorBoundary>
            </div>
          )}

          {/* Bottom Tabs Bar (Plan, Results/Route, Explore, Saved, You) */}
          <nav
            style={{
              display: 'flex',
              borderTop: '1px solid var(--color-divider, #D1D8D8)',
              backgroundColor: 'var(--color-nav-bg, #FFFFFF)',
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
                  color: activeTab === tab.id ? 'var(--color-blaze, #FF5B14)' : 'var(--color-text-primary, #1D3B34)',
                  border: 'none',
                  borderTop: activeTab === tab.id ? '3px solid var(--color-blaze, #FF5B14)' : '3px solid transparent',
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
