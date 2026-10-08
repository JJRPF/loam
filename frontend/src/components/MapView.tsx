import React, { useEffect, useRef } from 'react';
import { 
  Map, 
  Marker, 
  NavigationControl, 
  ScaleControl, 
  GeolocateControl,
  type StyleSpecification, 
  type GeoJSONSource 
} from 'maplibre-gl';
import type { RouteResponse, LatLon } from '../types';

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
  isDarkMode = false
}) => {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const startMarkerRef = useRef<Marker | null>(null);
  const endMarkerRef = useRef<Marker | null>(null);
  const scrubMarkerRef = useRef<Marker | null>(null);
  const onMapClickRef = useRef(onMapClick);
  const prevStartRef = useRef<{ lat: number; lon: number } | null>(null);

  useEffect(() => {
    onMapClickRef.current = onMapClick;
  }, [onMapClick]);

  // Initialize MapLibre
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;

    const initialCenter: [number, number] = [start?.lon ?? -71.3524, start?.lat ?? 43.1305];

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
      // Add empty route source & layers
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
          'line-color': isDarkMode ? '#0E1D19' : '#1D3B34',
          'line-width': 7,
          'line-opacity': 0.8
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
          'line-width': 4.0,
          'line-dasharray': [2, 2],
          'line-opacity': 0.85
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
          'line-width': 4.5,
          'line-opacity': 1.0
        }
      });

      // Auto center on GPS if no route and default/no start selected
      if (!route && (!start || (start.lat === 43.1305 && start.lon === -71.3524))) {
        if ('geolocation' in navigator) {
          navigator.geolocation.getCurrentPosition(
            (pos) => {
              if (mapRef.current && !route) {
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
          map.setPaintProperty('route-casing', 'line-color', isDarkMode ? '#0E1D19' : '#1D3B34');
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

  // Auto center on route when route changes; fit bounds to route geometry
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const source = map.getSource('route-line-source') as GeoJSONSource;
    if (!source) return;

    if (route && route.coordinates && route.coordinates.length > 0) {
      source.setData({
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'LineString',
          coordinates: route.coordinates.map(pt => [pt[0], pt[1]])
        }
      });

      // Auto center on the route
      if (route.bbox && route.bbox.length === 4) {
        map.fitBounds(
          [
            [route.bbox[0], route.bbox[1]],
            [route.bbox[2], route.bbox[3]]
          ],
          { padding: { top: 60, bottom: 240, left: 60, right: 60 }, maxZoom: 15.5, duration: 800 }
        );
      } else {
        const first = route.coordinates[0];
        map.flyTo({ center: [first[0], first[1]], zoom: 13, duration: 600 });
      }
    } else {
      source.setData({
        type: 'FeatureCollection',
        features: []
      });

      // When route is cleared, auto center back to route start or GPS
      if (start && start.lon && start.lat) {
        map.flyTo({ center: [start.lon, start.lat], zoom: 13, duration: 600 });
      }
    }
  }, [route]);

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
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const hoverSource = map.getSource('hover-route-source') as GeoJSONSource;
    if (!hoverSource) return;

    if (hoverRoute && hoverRoute.coordinates && hoverRoute.coordinates.length > 0 && hoverRoute.name !== route?.name) {
      hoverSource.setData({
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'LineString',
          coordinates: hoverRoute.coordinates.map(pt => [pt[0], pt[1]])
        }
      });
    } else {
      hoverSource.setData({
        type: 'FeatureCollection',
        features: []
      });
    }
  }, [hoverRoute, route]);

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
      
      {/* Map Attribution Badge per Item 5: CARTO and OpenStreetMap */}
      <div
        className="map-attribution-badge"
        style={{
          position: 'absolute',
          bottom: 12,
          right: 12,
          fontSize: 11,
          lineHeight: '14px',
          color: 'var(--color-text-primary, #1D3B34)',
          backgroundColor: isDarkMode ? 'rgba(14, 29, 25, 0.90)' : 'rgba(231, 236, 236, 0.90)',
          border: '1px solid var(--color-divider, #D1D8D8)',
          padding: '4px 8px',
          borderRadius: 4,
          zIndex: 10,
          pointerEvents: 'auto',
          boxShadow: '0 1px 4px rgba(0,0,0,0.18)',
          backdropFilter: 'blur(4px)'
        }}
      >
        &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'underline' }}>OpenStreetMap</a> contributors, &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'underline' }}>CARTO</a>
      </div>
    </div>
  );
};

export default MapView;
