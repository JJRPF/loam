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
import { EmailLinkFinish } from './components/EmailLinkFinish';
import trailheadData from './data/trailheads.json';
import { ErrorBoundary } from './components/ErrorBoundary';
import { decodeSearch, writeSearchUrl } from './urlState';
import { rememberRoute } from './services/offlineRoutes';
import { OfflineBanner } from './components/OfflineBanner';

// A shared link carries the whole search in its query string; opening it re-runs the search.
const initialShared = typeof window !== 'undefined' ? decodeSearch(window.location.search) : null;

export const App: React.FC = () => {
  // Dark mode only: enforce dark theme exclusively across application
  const isDarkMode = true;

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', 'dark');
    localStorage.setItem('loam_theme', 'dark');
  }, []);

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
  const [sport, setSport] = useState<SportProfile>(initialShared?.sport ?? 'mtb');
  // Until the browser reports a position, start at the first OSM-derived trailhead.
  const [start, setStart] = useState<LatLon>(() => {
    if (initialShared) return initialShared.start;
    const th = trailheadData.trailheads[0];
    return { lat: th.lat, lon: th.lon, name: th.name };
  });

  // Default Starting Location to GPS (browser geolocation)
  useEffect(() => {
    if (!initialShared && typeof window !== 'undefined' && 'geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setStart({
            lat: pos.coords.latitude,
            lon: pos.coords.longitude,
            name: "Current GPS Location"
          });
        },
        (err) => {
          // Permission denied or unavailable: keep the OSM trailhead start
          console.debug("Browser geolocation unavailable, keeping the trailhead start:", err.message);
        },
        { enableHighAccuracy: true, timeout: 5000, maximumAge: 60000 }
      );
    }
  }, []);
  const [end, setEnd] = useState<LatLon | undefined>(initialShared?.end);
  const [waypoints, setWaypoints] = useState<LatLon[]>(initialShared?.waypoints ?? []);
  const [routeMode, setRouteMode] = useState<'loop' | 'point_to_point' | 'out_and_back'>(initialShared?.routeMode ?? 'loop');
  const [targetMiles, setTargetMiles] = useState<number>(initialShared?.targetMiles ?? 10.0);
  const [terrainPref, setTerrainPref] = useState<TerrainPreference>(initialShared?.terrainPref ?? TERRAIN_PRESETS[0].weights);
  const [overrideDnr, setOverrideDnr] = useState<boolean>(initialShared?.overrideDnr ?? false);

  // Stage 6: Differentiators state
  const [findNewTrailsMode, setFindNewTrailsMode] = useState<boolean>(initialShared?.findNewTrailsMode ?? false);
  const [minNewTrailPercent, setMinNewTrailPercent] = useState<number>(initialShared?.minNewTrailPercent ?? 30);
  const [trailRunSteeperGrades, setTrailRunSteeperGrades] = useState<boolean>(true);
  const [trailRunAvoidMtbFlow, setTrailRunAvoidMtbFlow] = useState<boolean>(true);
  const [loopsOnly, setLoopsOnly] = useState<boolean>(initialShared?.loopsOnly ?? false);
  const [noTrueLoopNearHere, setNoTrueLoopNearHere] = useState<boolean>(false);
  const [nearbyStartSuggestion, setNearbyStartSuggestion] = useState<string | null>(null);
  const [optionsNotice, setOptionsNotice] = useState<string | null>(null);
  const [searchRequest, setSearchRequest] = useState<Record<string, unknown> | null>(null);

  // Route calculation and results
  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [options, setOptions] = useState<RouteResponse[]>([]);
  const [hoverRoute, setHoverRoute] = useState<RouteResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [scrubCoord, setScrubCoord] = useState<[number, number] | null>(null);
  const [pickingTarget, setPickingTarget] = useState<'start' | 'end' | 'mid' | null>(null);

  // Opening a shared link re-runs its search once.
  useEffect(() => {
    if (initialShared) handleBuildRoutes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The last 10 routes viewed stay on the device for offline viewing.
  useEffect(() => {
    if (route) void rememberRoute(route);
  }, [route]);

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
    } else if (pickingTarget === 'mid') {
      setWaypoints((w) => [...w, { lat, lon, name: `Midpoint (${lat.toFixed(4)}, ${lon.toFixed(4)})` }].slice(0, 5));
      setPickingTarget(null);
    }
  };

  const handleBuildRoutes = () => {
    setIsLoading(true);
    setOptions([]);
    setRoute(null);
    setNoTrueLoopNearHere(false);
    setNearbyStartSuggestion(null);
    setOptionsNotice(null);
    setSearchRequest(null);
    writeSearchUrl({
      sport, start, end: routeMode === 'point_to_point' ? end : undefined, waypoints, routeMode,
      targetMiles, terrainPref, overrideDnr, findNewTrailsMode, minNewTrailPercent, loopsOnly
    });
    setActiveTab('results');
    if (isMobile) {
      setSheetSnap('half');
    }

    streamRouteOptions(
      {
        start,
        end: routeMode === 'point_to_point' ? end : undefined,
        waypoints: routeMode === 'out_and_back' ? [] : waypoints,
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
        trailRunAvoidMtbFlow,
        loopsOnly
      },
      {
        onRequest: setSearchRequest,
        onCandidate: (cand) => {
          setOptions(prev => {
            const next = [...prev, cand];
            if (prev.length === 0) {
              setRoute(cand); // First resolved option becomes active
            }
            return next;
          });
        },
        onComplete: (_count, info) => {
          setIsLoading(false);
          setOptionsNotice(info?.notice || null);
          setOptions(currentOpts => {
            const hasLoops = currentOpts.some(o => o.route_type === 'loop' || o.route_type === 'lollipop');
            if (routeMode === 'loop' && (!hasLoops || currentOpts.length === 0)) {
              setNoTrueLoopNearHere(true);
            }
            if (currentOpts.length > 0 && currentOpts[0].nearby_start_suggestion) {
              setNearbyStartSuggestion(currentOpts[0].nearby_start_suggestion);
            }
            return currentOpts;
          });
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
      <EmailLinkFinish />
      <OfflineBanner />
      
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
                  waypoints={waypoints}
                  onWaypointsChange={setWaypoints}
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
                  loopsOnly={loopsOnly}
                  onLoopsOnlyChange={setLoopsOnly}
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
                  noTrueLoopNearHere={noTrueLoopNearHere}
                  nearbyStartSuggestion={nearbyStartSuggestion || undefined}
                  optionsNotice={optionsNotice || undefined}
                  searchRequest={searchRequest}
                />
              )}

              {activeTab === 'explore' && <ExplorePanel onPlanFrom={(s) => { setStart(s); setActiveTab('plan'); }} />}
              {activeTab === 'saved' && <SavedRoutesPanel onLoadRoute={handleLoadSavedRoute} />}
              {activeTab === 'you' && (
                <YouPanel isDarkMode={isDarkMode} />
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
            Tap map to set {pickingTarget === 'start' ? 'Starting Location' : pickingTarget === 'mid' ? 'a Midpoint' : 'Destination'}
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
                    waypoints={waypoints}
                    onWaypointsChange={setWaypoints}
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
                    loopsOnly={loopsOnly}
                    onLoopsOnlyChange={setLoopsOnly}
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
                    noTrueLoopNearHere={noTrueLoopNearHere}
                    nearbyStartSuggestion={nearbyStartSuggestion || undefined}
                  optionsNotice={optionsNotice || undefined}
                    searchRequest={searchRequest}
                  />
                )}

                {activeTab === 'explore' && <ExplorePanel onPlanFrom={(s) => { setStart(s); setActiveTab('plan'); }} />}
                {activeTab === 'saved' && <SavedRoutesPanel onLoadRoute={handleLoadSavedRoute} />}
                {activeTab === 'you' && (
                  <YouPanel isDarkMode={isDarkMode} />
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
