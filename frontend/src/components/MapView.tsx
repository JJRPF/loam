import React, { useEffect, useRef, useState, useCallback } from 'react';
import { 
  Map, 
  Marker, 
  Popup,
  NavigationControl, 
  ScaleControl, 
  GeolocateControl,
  setWorkerUrl,
  type StyleSpecification, 
  type GeoJSONSource 
} from 'maplibre-gl';
import type { RouteResponse, LatLon } from '../types';
import { fetchHeatTrails, fetchOtmTrails } from '../services/api';
import trailheadData from '../data/trailheads.json';

const DEFAULT_TRAILHEAD = trailheadData.trailheads[0];

// Explicitly register worker URL to guarantee local worker loading in dev & prod
setWorkerUrl('/assets/maplibre-gl-worker.mjs');

interface MapViewProps {
  route: RouteResponse | null;
  hoverRoute?: RouteResponse | null;
  start: LatLon;
  end?: LatLon;
  waypoints?: LatLon[];
  scrubCoord?: [number, number] | null;
  onMapClick?: (lat: number, lon: number) => void;
  isDarkMode?: boolean;
}

const CARTO_KEY = 'cb1_4dqd_1_e9976fbebd5d928d8538e995';

const buildMapStyle = (isDark: boolean): StyleSpecification => ({
  version: 8,
  sources: {
    'carto-voyager': {
      type: 'raster',
      tiles: [
        `https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png?key=${CARTO_KEY}`,
        `https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png?key=${CARTO_KEY}`,
        `https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png?key=${CARTO_KEY}`
      ],
      tileSize: 256,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">CARTO</a>'
    },
    'carto-dark': {
      type: 'raster',
      tiles: [
        `https://a.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}@2x.png?key=${CARTO_KEY}`,
        `https://b.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}@2x.png?key=${CARTO_KEY}`,
        `https://c.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}@2x.png?key=${CARTO_KEY}`
      ],
      tileSize: 256,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">CARTO</a>'
    }
  },
  layers: [
    {
      id: 'carto-voyager-layer',
      type: 'raster',
      source: 'carto-voyager',
      minzoom: 0,
      maxzoom: 20,
      layout: {
        visibility: isDark ? 'none' : 'visible'
      }
    },
    {
      id: 'carto-dark-layer',
      type: 'raster',
      source: 'carto-dark',
      minzoom: 0,
      maxzoom: 20,
      layout: {
        visibility: isDark ? 'visible' : 'none'
      }
    }
  ]
});

export const MapView: React.FC<MapViewProps> = ({
  route,
  hoverRoute,
  start,
  end,
  scrubCoord,
  onMapClick,
  isDarkMode = true
}) => {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const startMarkerRef = useRef<Marker | null>(null);
  const endMarkerRef = useRef<Marker | null>(null);
  const scrubMarkerRef = useRef<Marker | null>(null);
  const onMapClickRef = useRef(onMapClick);
  const prevStartRef = useRef<{ lat: number; lon: number } | null>(null);

  // Active route reference for map event callbacks
  const routeRef = useRef<RouteResponse | null>(route);
  routeRef.current = route;

  const hoverRouteRef = useRef<RouteResponse | null>(hoverRoute || null);
  hoverRouteRef.current = hoverRoute || null;

  // Heat trail state & cached GeoJSON
  const [showHeatmap, setShowHeatmap] = useState<boolean>(true);
  const [heatTrailCount, setHeatTrailCount] = useState<number>(0);
  const heatDataRef = useRef<any>(null);

  // OpenTrailMap (OTM) trails state & cached GeoJSON
  const [showOtmTrails, setShowOtmTrails] = useState<boolean>(false);
  const [otmTrailCount, setOtmTrailCount] = useState<number>(0);
  const otmDataRef = useRef<any>(null);

  useEffect(() => {
    onMapClickRef.current = onMapClick;
  }, [onMapClick]);

  // Apply route line data directly whenever source exists
  const applyRoute = useCallback((r: RouteResponse | null) => {
    const map = mapRef.current;
    if (!map) return;
    const source = map.getSource('route-line-source') as GeoJSONSource;
    if (!source) return;

    if (r && r.coordinates && r.coordinates.length > 0) {
      source.setData({
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'LineString',
          coordinates: r.coordinates.map(pt => [Number(pt[0]), Number(pt[1])])
        }
      });

      // Retraced sections (highlighted in red)
      const retracedSource = map.getSource('retraced-route-source') as GeoJSONSource;
      if (retracedSource) {
        if (r.retraced_coordinates && r.retraced_coordinates.length > 0) {
          retracedSource.setData({
            type: 'FeatureCollection',
            features: r.retraced_coordinates.map(line => ({
              type: 'Feature',
              properties: {},
              geometry: {
                type: 'LineString',
                coordinates: line.map(pt => [Number(pt[0]), Number(pt[1])])
              }
            }))
          });
        } else {
          retracedSource.setData({
            type: 'FeatureCollection',
            features: []
          });
        }
      }

      // Fit bounds to route geometry
      if (r.bbox && r.bbox.length === 4) {
        map.fitBounds(
          [
            [Number(r.bbox[0]), Number(r.bbox[1])],
            [Number(r.bbox[2]), Number(r.bbox[3])]
          ],
          { padding: { top: 60, bottom: 240, left: 60, right: 60 }, maxZoom: 15.5, duration: 800 }
        );
      } else {
        const first = r.coordinates[0];
        map.flyTo({ center: [Number(first[0]), Number(first[1])], zoom: 13, duration: 600 });
      }
    } else {
      source.setData({
        type: 'FeatureCollection',
        features: []
      });

      const retracedSource = map.getSource('retraced-route-source') as GeoJSONSource;
      if (retracedSource) {
        retracedSource.setData({
          type: 'FeatureCollection',
          features: []
        });
      }

      // When route is cleared, auto center back to route start or GPS
      if (start && start.lon && start.lat) {
        map.flyTo({ center: [Number(start.lon), Number(start.lat)], zoom: 13, duration: 600 });
      }
    }
  }, [start]);

  // Apply hover preview route data directly
  const applyHoverRoute = useCallback((hr: RouteResponse | null) => {
    const map = mapRef.current;
    if (!map) return;
    const hoverSource = map.getSource('hover-route-source') as GeoJSONSource;
    if (!hoverSource) return;

    if (hr && hr.coordinates && hr.coordinates.length > 0 && hr.name !== routeRef.current?.name) {
      hoverSource.setData({
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'LineString',
          coordinates: hr.coordinates.map(pt => [Number(pt[0]), Number(pt[1])])
        }
      });
    } else {
      hoverSource.setData({
        type: 'FeatureCollection',
        features: []
      });
    }
  }, []);

  // Fetch heat trail GeoJSON on mount
  useEffect(() => {
    fetchHeatTrails()
      .then((geojson) => {
        if (!geojson || !geojson.features) return;
        setHeatTrailCount(geojson.features.length);
        heatDataRef.current = geojson;
        const map = mapRef.current;
        if (map) {
          const src = map.getSource('heat-trails-source') as GeoJSONSource;
          if (src) {
            src.setData(geojson);
          }
        }
      })
      .catch((err) => {
        console.warn('Failed to load heat trails:', err);
      });
  }, []);

  // OSM trails for the visible area, refreshed when the map stops moving (zoom 12+).
  const loadTrailsForView = (map: Map) => {
    if (map.getZoom() < 12) return;
    const b = map.getBounds();
    fetchOtmTrails({ minLat: b.getSouth(), minLon: b.getWest(), maxLat: b.getNorth(), maxLon: b.getEast() })
      .then((geojson) => {
        if (!geojson || !geojson.features) return;
        setOtmTrailCount(geojson.features.length);
        otmDataRef.current = geojson;
        const src = map.getSource('otm-trails-source') as GeoJSONSource;
        if (src) {
          src.setData(geojson);
        }
      })
      .catch((err) => {
        console.warn('Failed to load OSM trails:', err);
      });
  };

  // Initialize MapLibre
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;

    const initialCenter: [number, number] = [start?.lon ?? DEFAULT_TRAILHEAD.lon, start?.lat ?? DEFAULT_TRAILHEAD.lat];

    const map = new Map({
      container: mapContainer.current,
      style: buildMapStyle(isDarkMode),
      center: initialCenter,
      zoom: 12.5,
      pitch: 0,
      attributionControl: false // Handled via dedicated responsive attribution badge below
    });

    map.addControl(new NavigationControl({ showCompass: true }), 'top-right');
    map.addControl(
      new GeolocateControl({
        positionOptions: { enableHighAccuracy: true },
        trackUserLocation: false
      }),
      'top-right'
    );
    map.addControl(new ScaleControl({ unit: 'imperial' }), 'bottom-left');

    map.on('load', () => {
      loadTrailsForView(map);
      // 1. Heat trail GeoJSON source & layers (rendered below active route)
      map.addSource('heat-trails-source', {
        type: 'geojson',
        data: heatDataRef.current || {
          type: 'FeatureCollection',
          features: []
        }
      });

      map.addLayer({
        id: 'heat-trails-glow',
        type: 'line',
        source: 'heat-trails-source',
        layout: {
          'line-cap': 'round',
          'line-join': 'round',
          visibility: showHeatmap ? 'visible' : 'none'
        },
        paint: {
          'line-color': [
            'interpolate',
            ['linear'],
            ['get', 'heat_score'],
            0, '#FFA726',
            40, '#FF7043',
            75, '#E63946',
            100, '#D90429'
          ],
          'line-width': ['interpolate', ['linear'], ['zoom'], 10, 3, 14, 8, 17, 14],
          'line-blur': 3,
          'line-opacity': 0.65
        }
      });

      map.addLayer({
        id: 'heat-trails-line',
        type: 'line',
        source: 'heat-trails-source',
        layout: {
          'line-cap': 'round',
          'line-join': 'round',
          visibility: showHeatmap ? 'visible' : 'none'
        },
        paint: {
          'line-color': [
            'interpolate',
            ['linear'],
            ['get', 'heat_score'],
            0, '#FFB74D',
            40, '#FF7043',
            75, '#E63946',
            100, '#B71C1C'
          ],
          'line-width': ['interpolate', ['linear'], ['zoom'], 10, 1.5, 13, 3, 16, 5],
          'line-opacity': 0.85
        }
      });

      // Trail click popup for heat trail inspection
      map.on('click', 'heat-trails-line', (e) => {
        if (!e.features || !e.features[0]) return;
        const feat = e.features[0];
        const name = feat.properties?.name || 'Local Trail';
        const heat = feat.properties?.heat_score || 0;
        const rides = feat.properties?.ride_count || 0;
        new Popup({ offset: 10 })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-family: -apple-system, sans-serif; font-size: 13px; color: #E7ECEC; padding: 2px;">
            <div style="font-weight: 700; font-size: 14px; margin-bottom: 2px;">${name}</div>
            <div style="color: #FF5B14; font-weight: 600;">🔥 Heat Index: ${heat}/100</div>
            <div style="font-size: 11px; color: #A0B5AE;">${rides} logged activity passes</div>
          </div>`)
          .addTo(map);
      });

      map.on('mouseenter', 'heat-trails-line', () => {
        map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', 'heat-trails-line', () => {
        map.getCanvas().style.cursor = '';
      });

      // 1.5 OpenTrailMap (OTM) trails source & layer
      map.addSource('otm-trails-source', {
        type: 'geojson',
        data: otmDataRef.current || {
          type: 'FeatureCollection',
          features: []
        }
      });

      map.addLayer({
        id: 'otm-trails-line',
        type: 'line',
        source: 'otm-trails-source',
        layout: {
          'line-cap': 'round',
          'line-join': 'round',
          visibility: showOtmTrails ? 'visible' : 'none'
        },
        paint: {
          'line-color': [
            'match',
            ['get', 'difficulty'],
            'expert', '#CE93D8',
            'advanced', '#64B5F6',
            'beginner', '#81C784',
            '#4FC3F7'
          ],
          'line-width': ['interpolate', ['linear'], ['zoom'], 10, 1.5, 13, 3, 16, 5],
          'line-opacity': 0.85,
          'line-dasharray': [3, 1]
        }
      });

      map.on('click', 'otm-trails-line', (e) => {
        if (!e.features || !e.features[0]) return;
        const feat = e.features[0];
        const name = feat.properties?.name || 'OpenTrailMap Trail';
        const diff = feat.properties?.difficulty || 'Standard';
        const surf = feat.properties?.surface || 'natural';
        new Popup({ offset: 10 })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-family: -apple-system, sans-serif; font-size: 13px; color: #E7ECEC; padding: 2px;">
            <div style="font-weight: 700; font-size: 14px; margin-bottom: 2px;">🌲 ${name}</div>
            <div style="color: #0288D1; font-weight: 600; text-transform: capitalize;">Difficulty: ${diff}</div>
            <div style="font-size: 11px; color: #A0B5AE;">Surface: ${surf} | OpenTrailMap</div>
          </div>`)
          .addTo(map);
      });

      map.on('mouseenter', 'otm-trails-line', () => {
        map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', 'otm-trails-line', () => {
        map.getCanvas().style.cursor = '';
      });

      // 2. Active route source & layers
      map.addSource('route-line-source', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: []
        }
      });

      // Route shadow casing
      map.addLayer({
        id: 'route-casing',
        type: 'line',
        source: 'route-line-source',
        layout: {
          'line-cap': 'round',
          'line-join': 'round'
        },
        paint: {
          'line-color': isDarkMode ? '#050D0A' : '#0B1D18',
          'line-width': 8,
          'line-opacity': 0.85
        }
      });

      // Hover Route Preview Source & Layer (Slate #3F6C8F)
      map.addSource('hover-route-source', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: []
        }
      });

      map.addLayer({
        id: 'hover-route-line',
        type: 'line',
        source: 'hover-route-source',
        layout: {
          'line-cap': 'round',
          'line-join': 'round'
        },
        paint: {
          'line-color': '#3F6C8F',
          'line-width': 4.5,
          'line-dasharray': [2, 2],
          'line-opacity': 0.9
        }
      });

      // Primary Blaze Route Line (#FF5B14)
      map.addLayer({
        id: 'route-line',
        type: 'line',
        source: 'route-line-source',
        layout: {
          'line-cap': 'round',
          'line-join': 'round'
        },
        paint: {
          'line-color': '#FF5B14',
          'line-width': 5.0,
          'line-opacity': 1.0
        }
      });

      // Retraced Sections Layer (Red #EF4444)
      map.addSource('retraced-route-source', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: []
        }
      });

      map.addLayer({
        id: 'retraced-route-line',
        type: 'line',
        source: 'retraced-route-source',
        layout: {
          'line-cap': 'round',
          'line-join': 'round'
        },
        paint: {
          'line-color': '#EF4444',
          'line-width': 5.5,
          'line-opacity': 0.95
        }
      });

      // Apply initial route and hover route immediately upon map load
      applyRoute(routeRef.current);
      applyHoverRoute(hoverRouteRef.current);

      // Auto center on GPS if no route and default/no start selected
      if (!routeRef.current && (!start || (start.lat === DEFAULT_TRAILHEAD.lat && start.lon === DEFAULT_TRAILHEAD.lon))) {
        if ('geolocation' in navigator) {
          navigator.geolocation.getCurrentPosition(
            (pos) => {
              if (mapRef.current && !routeRef.current) {
                mapRef.current.flyTo({
                  center: [pos.coords.longitude, pos.coords.latitude],
                  zoom: 13,
                  duration: 800
                });
              }
            },
            () => {
              // Geolocation denied or unavailable; stay at default start
            },
            { timeout: 6000, enableHighAccuracy: true }
          );
        }
      }
    });

    map.on('click', (e) => {
      onMapClickRef.current?.(e.lngLat.lat, e.lngLat.lng);
    });

    (window as any).__loamMap = map;
    map.on('moveend', () => loadTrailsForView(map));
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Sync Dark Mode theme with MapLibre layers
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applyTheme = () => {
      try {
        if (map.getLayer('carto-voyager-layer')) {
          map.setLayoutProperty('carto-voyager-layer', 'visibility', isDarkMode ? 'none' : 'visible');
        }
        if (map.getLayer('carto-dark-layer')) {
          map.setLayoutProperty('carto-dark-layer', 'visibility', isDarkMode ? 'visible' : 'none');
        }
        if (map.getLayer('route-casing')) {
          map.setPaintProperty('route-casing', 'line-color', isDarkMode ? '#050D0A' : '#0B1D18');
        }
      } catch (err) {
        console.warn('Error applying map theme:', err);
      }
    };

    if (map.getLayer('carto-voyager-layer')) {
      applyTheme();
    } else {
      map.once('styledata', applyTheme);
    }
  }, [isDarkMode]);

  // Sync Heatmap layer visibility
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    try {
      const vis = showHeatmap ? 'visible' : 'none';
      if (map.getLayer('heat-trails-glow')) {
        map.setLayoutProperty('heat-trails-glow', 'visibility', vis);
      }
      if (map.getLayer('heat-trails-line')) {
        map.setLayoutProperty('heat-trails-line', 'visibility', vis);
      }
    } catch (err) {
      console.warn('Error toggling heatmap layer visibility:', err);
    }
  }, [showHeatmap]);

  // Sync OpenTrailMap layer visibility
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    try {
      const vis = showOtmTrails ? 'visible' : 'none';
      if (map.getLayer('otm-trails-line')) {
        map.setLayoutProperty('otm-trails-line', 'visibility', vis);
      }
    } catch (err) {
      console.warn('Error toggling OTM trail layer visibility:', err);
    }
  }, [showOtmTrails]);

  // Update Route GeoJSON when route changes
  useEffect(() => {
    applyRoute(route);
  }, [route, applyRoute]);

  // Auto center on route start when start position changes and no route is active
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const prev = prevStartRef.current;
    const startChanged = !prev || prev.lat !== start.lat || prev.lon !== start.lon;
    prevStartRef.current = { lat: start.lat, lon: start.lon };

    if (startChanged && !route && start && start.lon && start.lat) {
      map.flyTo({
        center: [start.lon, start.lat],
        zoom: 13,
        duration: 600
      });
    }
  }, [start, route]);

  // Update Hover Preview Route GeoJSON
  useEffect(() => {
    applyHoverRoute(hoverRoute || null);
  }, [hoverRoute, applyHoverRoute]);

  // Update Start & End Markers
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    // Start Marker (Forest Green #2E6F40)
    if (!startMarkerRef.current) {
      const el = document.createElement('div');
      el.style.width = '18px';
      el.style.height = '18px';
      el.style.backgroundColor = '#2E6F40';
      el.style.border = '2.5px solid #FFFFFF';
      el.style.borderRadius = '50%';
      el.style.boxShadow = '0 2px 6px rgba(0,0,0,0.3)';
      el.title = 'Start';
      startMarkerRef.current = new Marker({ element: el }).setLngLat([start.lon, start.lat]).addTo(map);
    } else {
      startMarkerRef.current.setLngLat([start.lon, start.lat]);
    }

    // End Marker (Spruce / Blaze #C73E00)
    if (end) {
      if (!endMarkerRef.current) {
        const el = document.createElement('div');
        el.style.width = '18px';
        el.style.height = '18px';
        el.style.backgroundColor = '#C73E00';
        el.style.border = '2.5px solid #FFFFFF';
        el.style.borderRadius = '50%';
        el.style.boxShadow = '0 2px 6px rgba(0,0,0,0.3)';
        el.title = 'End';
        endMarkerRef.current = new Marker({ element: el }).setLngLat([end.lon, end.lat]).addTo(map);
      } else {
        endMarkerRef.current.setLngLat([end.lon, end.lat]);
      }
    } else if (endMarkerRef.current) {
      endMarkerRef.current.remove();
      endMarkerRef.current = null;
    }
  }, [start, end]);

  // Update Scrub Marker
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (scrubCoord) {
      if (!scrubMarkerRef.current) {
        const el = document.createElement('div');
        el.style.width = '16px';
        el.style.height = '16px';
        el.style.backgroundColor = '#FF5B14';
        el.style.border = '3px solid #FFFFFF';
        el.style.borderRadius = '50%';
        el.style.boxShadow = '0 0 10px rgba(255, 91, 20, 0.8)';
        el.style.pointerEvents = 'none';
        scrubMarkerRef.current = new Marker({ element: el }).setLngLat(scrubCoord).addTo(map);
      } else {
        scrubMarkerRef.current.setLngLat(scrubCoord);
      }
    } else if (scrubMarkerRef.current) {
      scrubMarkerRef.current.remove();
      scrubMarkerRef.current = null;
    }
  }, [scrubCoord]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div ref={mapContainer} className="maplibre-container" />
      
      {/* Heatmap Layer Toggle Badge */}
      <div
        style={{
          position: 'absolute',
          top: 16,
          left: 16,
          zIndex: 15,
          display: 'flex',
          alignItems: 'center',
          gap: 6
        }}
      >
        <button
          type="button"
          onClick={() => setShowHeatmap(!showHeatmap)}
          style={{
            backgroundColor: showHeatmap ? 'var(--color-header-bg)' : 'var(--color-card-bg)',
            color: showHeatmap ? '#FFFFFF' : 'var(--color-text-secondary)',
            border: showHeatmap ? '1px solid var(--color-blaze, #FF5B14)' : '1px solid var(--color-divider)',
            borderRadius: 20,
            padding: '6px 14px',
            fontSize: 12,
            fontWeight: 700,
            boxShadow: '0 2px 8px rgba(0,0,0,0.18)',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            cursor: 'pointer',
            transition: 'all 0.2s ease'
          }}
          title={showHeatmap ? 'Hide trail heatmap' : 'Show trail heatmap'}
        >
          <span>🔥</span>
          <span>{showHeatmap ? 'Heatmap ON' : 'Heatmap OFF'}</span>
          {heatTrailCount > 0 && (
            <span
              style={{
                backgroundColor: showHeatmap ? 'var(--color-blaze, #FF5B14)' : 'var(--color-divider)',
                color: showHeatmap ? '#FFFFFF' : 'var(--color-text-secondary)',
                padding: '1px 6px',
                borderRadius: 10,
                fontSize: 10,
                fontWeight: 700
              }}
            >
              {heatTrailCount}
            </span>
          )}
        </button>

        {/* OpenTrailMap Layer Toggle Badge */}
        <button
          type="button"
          onClick={() => setShowOtmTrails(!showOtmTrails)}
          style={{
            backgroundColor: showOtmTrails ? 'var(--color-header-bg)' : 'var(--color-card-bg)',
            color: showOtmTrails ? '#FFFFFF' : 'var(--color-text-secondary)',
            border: showOtmTrails ? '1px solid #0288D1' : '1px solid var(--color-divider)',
            borderRadius: 20,
            padding: '6px 14px',
            fontSize: 12,
            fontWeight: 700,
            boxShadow: '0 2px 8px rgba(0,0,0,0.18)',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            cursor: 'pointer',
            transition: 'all 0.2s ease'
          }}
          title={showOtmTrails ? 'Hide OpenTrailMap trails' : 'Show OpenTrailMap trails'}
        >
          <span>🌲</span>
          <span>{showOtmTrails ? 'OTM Trails ON' : 'OTM Trails OFF'}</span>
          {otmTrailCount > 0 && (
            <span
              style={{
                backgroundColor: showOtmTrails ? '#0288D1' : 'var(--color-divider)',
                color: showOtmTrails ? '#FFFFFF' : 'var(--color-text-secondary)',
                padding: '1px 6px',
                borderRadius: 10,
                fontSize: 10,
                fontWeight: 700
              }}
            >
              {otmTrailCount}
            </span>
          )}
        </button>
      </div>

      {/* Map Attribution Badge: CARTO and OpenStreetMap (Responsive: top on mobile, bottom on desktop) */}
      <div className="map-attribution-badge">
        &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'underline' }}>OpenStreetMap</a> contributors, &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'underline' }}>CARTO</a>
      </div>
    </div>
  );
};

export default MapView;
