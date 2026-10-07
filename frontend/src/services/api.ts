import type { RouteResponse, SavedRoute, TerrainPreference, SportProfile, LatLon } from '../types';

const API_BASE = ''; // proxied via vite in dev, relative in production

export async function calculateRoute(params: {
  start: LatLon;
  end?: LatLon;
  waypoints?: LatLon[];
  profile: SportProfile;
  terrainPreference?: TerrainPreference;
  isLoop?: boolean;
  routeMode?: string;
  targetDistanceMiles?: number;
  name?: string;
}): Promise<RouteResponse> {
  const payload = {
    start: { lat: params.start.lat, lon: params.start.lon, name: params.start.name },
    end: params.end ? { lat: params.end.lat, lon: params.end.lon, name: params.end.name } : undefined,
    waypoints: params.waypoints?.map(wp => ({ lat: wp.lat, lon: wp.lon, name: wp.name })),
    profile: params.profile,
    terrain_preference: params.terrainPreference,
    is_loop: params.isLoop ?? (params.routeMode === 'loop'),
    route_mode: params.routeMode ?? 'point_to_point',
    target_distance_miles: params.targetDistanceMiles,
    name: params.name
  };

  const res = await fetch(`${API_BASE}/api/route`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Routing calculation failed (${res.status}): ${errorText}`);
  }

  return await res.json();
}

export async function downloadGpx(route: RouteResponse): Promise<void> {
  const payload = {
    name: route.name || 'Loam Route',
    sport: route.sport || 'mtb',
    distance_miles: route.distance_miles,
    duration_minutes: route.duration_minutes,
    elevation_gain_ft: route.elevation_gain_ft,
    elevation_loss_ft: route.elevation_loss_ft,
    coordinates: route.coordinates
  };

  try {
    const res = await fetch(`${API_BASE}/api/export/gpx`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      const blob = await res.blob();
      triggerDownload(blob, `${(route.name || 'loam_route').toLowerCase().replace(/\s+/g, '_')}.gpx`);
      return;
    }
  } catch (err) {
    console.warn('API GPX export failed, using client-side fallback:', err);
  }

  // Client-side fallback generator
  const gpxContent = generateClientGpx(route);
  const blob = new Blob([gpxContent], { type: 'application/gpx+xml' });
  triggerDownload(blob, `${(route.name || 'loam_route').toLowerCase().replace(/\s+/g, '_')}.gpx`);
}

export async function downloadFit(route: RouteResponse): Promise<void> {
  const payload = {
    name: route.name || 'Loam Route',
    sport: route.sport || 'mtb',
    distance_miles: route.distance_miles,
    duration_minutes: route.duration_minutes,
    elevation_gain_ft: route.elevation_gain_ft,
    elevation_loss_ft: route.elevation_loss_ft,
    coordinates: route.coordinates
  };

  const res = await fetch(`${API_BASE}/api/export/fit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    throw new Error(`Failed to generate Garmin FIT file: ${await res.text()}`);
  }

  const blob = await res.blob();
  triggerDownload(blob, `${(route.name || 'loam_route').toLowerCase().replace(/\s+/g, '_')}.fit`);
}

export async function shareRouteGarmin(route: RouteResponse): Promise<{ shared: boolean; message: string }> {
  const filename = `${(route.name || 'loam_route').toLowerCase().replace(/\s+/g, '_')}.gpx`;
  const gpxContent = generateClientGpx(route);
  const file = new File([gpxContent], filename, { type: 'application/gpx+xml' });

  if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({
        title: `${route.name || 'Loam Route'} (Garmin Course)`,
        text: `Open in Garmin Connect: ${route.distance_miles.toFixed(1)} mi with ${Math.round(route.elevation_gain_ft)} ft elevation gain.`,
        files: [file]
      });
      return { shared: true, message: 'Shared to Garmin Connect sheet!' };
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        console.error('Share failed', e);
      }
    }
  }

  // Fallback: download GPX and inform user
  await downloadGpx(route);
  return { 
    shared: false, 
    message: 'GPX downloaded! Open the downloaded file in Garmin Connect on your phone or sync to your fenix 7 Pro.' 
  };
}

export async function saveRouteApi(route: RouteResponse, userId = 'justin_user'): Promise<string> {
  const payload = {
    name: route.name || 'Loam Route',
    sport: route.sport || 'mtb',
    distance_miles: route.distance_miles,
    elevation_gain_ft: route.elevation_gain_ft,
    elevation_loss_ft: route.elevation_loss_ft,
    coordinates: route.coordinates,
    surface_breakdown: route.surface_breakdown,
    surface_strip: route.surface_strip,
    verbal_summary: route.verbal_summary
  };

  try {
    const res = await fetch(`${API_BASE}/api/saved-routes`, {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'X-User-Id': userId
      },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      const data = await res.json();
      // Also cache in localStorage
      saveRouteLocally({ ...payload, id: data.id, created_at: new Date().toISOString(), user_id: userId });
      return data.id;
    }
  } catch (err) {
    console.warn('API save route failed, saving locally:', err);
  }

  // Fallback: save to localStorage
  const localId = `local_${Date.now()}`;
  saveRouteLocally({ ...payload, id: localId, created_at: new Date().toISOString(), user_id: userId });
  return localId;
}

export async function fetchSavedRoutes(userId = 'justin_user'): Promise<SavedRoute[]> {
  try {
    const res = await fetch(`${API_BASE}/api/saved-routes`, {
      headers: { 'X-User-Id': userId }
    });
    if (res.ok) {
      const data = await res.json();
      if (data.routes && data.routes.length > 0) {
        return data.routes;
      }
    }
  } catch (err) {
    console.warn('Could not fetch routes from API, reading localStorage:', err);
  }

  return getLocalSavedRoutes();
}

export async function deleteSavedRoute(id: string, userId = 'justin_user'): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/saved-routes/${id}`, {
      method: 'DELETE',
      headers: { 'X-User-Id': userId }
    });
    if (res.ok) {
      removeLocalSavedRoute(id);
      return true;
    }
  } catch (err) {
    console.warn('API delete route failed:', err);
  }
  removeLocalSavedRoute(id);
  return true;
}

// Helpers
function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function generateClientGpx(route: RouteResponse): string {
  const timeStr = new Date().toISOString();
  const trkpts = route.coordinates.map((pt) => {
    const lon = pt[0];
    const lat = pt[1];
    const ele = pt.length > 2 ? `<ele>${pt[2].toFixed(1)}</ele>` : '';
    return `      <trkpt lat="${lat.toFixed(6)}" lon="${lon.toFixed(6)}">${ele}</trkpt>`;
  }).join('\n');

  return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Loam Trail Route Builder" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata>
    <name>${route.name || 'Loam Route'}</name>
    <desc>Loam Route: ${route.distance_miles.toFixed(1)} mi (${route.sport})</desc>
    <time>${timeStr}</time>
  </metadata>
  <trk>
    <name>${route.name || 'Loam Route'}</name>
    <type>${route.sport || 'mtb'}</type>
    <trkseg>
${trkpts}
    </trkseg>
  </trk>
</gpx>`;
}

const LOCAL_STORAGE_KEY = 'loam_saved_routes_v1';

function saveRouteLocally(route: SavedRoute) {
  try {
    const existing = getLocalSavedRoutes();
    const updated = [route, ...existing.filter(r => r.id !== route.id)];
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(updated));
  } catch (e) {
    console.error('LocalStorage write failed', e);
  }
}

function getLocalSavedRoutes(): SavedRoute[] {
  try {
    const data = localStorage.getItem(LOCAL_STORAGE_KEY);
    return data ? JSON.parse(data) : [];
  } catch {
    return [];
  }
}

function removeLocalSavedRoute(id: string) {
  try {
    const existing = getLocalSavedRoutes();
    const updated = existing.filter(r => r.id !== id);
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(updated));
  } catch {}
}
