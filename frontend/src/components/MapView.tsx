import React, { useEffect, useRef } from 'react';
import { 
  Map, 
  Marker, 
  NavigationControl, 
  ScaleControl, 
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
}

// Clean, outdoor topographic basemap style using Carto Voyager with terrain labels
const MAP_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    'carto-voyager': {
      type: 'raster',
      tiles: [
        'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png',
        'https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png',
        'https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png'
      ],
      tileSize: 256,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
    }
  },
  layers: [
    {
      id: 'carto-voyager-layer',
      type: 'raster',
      source: 'carto-voyager',
      minzoom: 0,
      maxzoom: 20
    }
  ]
};

export const MapView: React.FC<MapViewProps> = ({
  route,
  hoverRoute,
  start,
  end,
  scrubCoord,
  onMapClick
}) => {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const startMarkerRef = useRef<Marker | null>(null);
  const endMarkerRef = useRef<Marker | null>(null);
  const scrubMarkerRef = useRef<Marker | null>(null);
  const onMapClickRef = useRef(onMapClick);
  useEffect(() => {
    onMapClickRef.current = onMapClick;
  }, [onMapClick]);

  // Initialize MapLibre
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;

    const map = new Map({
      container: mapContainer.current,
      style: MAP_STYLE,
      center: [-71.3524, 43.1305], // Bear Brook State Park, NH
      zoom: 12.5,
      pitch: 0
    });

    map.addControl(new NavigationControl({ showCompass: true }), 'top-right');
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
          'line-color': '#1D3B34',
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
    });

    map.on('click', (e) => {
      onMapClickRef.current?.(e.lngLat.lat, e.lngLat.lng);
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Update Route GeoJSON
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

      // Fit map bounds to route
      if (route.bbox && route.bbox.length === 4) {
        map.fitBounds(
          [
            [route.bbox[0], route.bbox[1]],
            [route.bbox[2], route.bbox[3]]
          ],
          { padding: { top: 60, bottom: 240, left: 60, right: 60 }, maxZoom: 15.5, duration: 800 }
        );
      }
    } else {
      source.setData({
        type: 'FeatureCollection',
        features: []
      });
    }
  }, [route]);

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

    // Start Marker (Forest Green)
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

    // End Marker (Spruce / Blaze)
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
      {/* Attribution Overlay */}
      <div
        style={{
          position: 'absolute',
          bottom: 4,
          right: 4,
          fontSize: 10,
          color: '#1D3B34',
          backgroundColor: 'rgba(231, 236, 236, 0.85)',
          padding: '2px 6px',
          borderRadius: 4,
          pointerEvents: 'none'
        }}
      >
        &copy; OpenStreetMap contributors • Loam NH
      </div>
    </div>
  );
};
