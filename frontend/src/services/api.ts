import type { 
  RouteResponse, 
  RouteOptionsResponse, 
  SavedRoute, 
  TerrainPreference, 
  SportProfile, 
  LatLon,
  CommunityFlag,
  TrailCheckin,
  UserDNR,
  UserDataExport,
  TrailSubmission,
  UnriddenTrailItem,
  ConnectorStatus,
  AuthUser,
  GeocodeResult
} from '../types';


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
  overrideDnr?: boolean;
  findNewTrailsMode?: boolean;
  minNewTrailPercent?: number;
  minNewTrailMiles?: number;
  trailRunSteeperGrades?: boolean;
  trailRunAvoidMtbFlow?: boolean;
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
    name: params.name,
    override_dnr: params.overrideDnr ?? false,
    find_new_trails_mode: params.findNewTrailsMode ?? false,
    min_new_trail_percent: params.minNewTrailPercent,
    min_new_trail_miles: params.minNewTrailMiles,
    trail_run_steeper_grades: params.trailRunSteeperGrades ?? false,
    trail_run_avoid_mtb_flow: params.trailRunAvoidMtbFlow ?? true
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

export async function calculateRouteOptions(params: {
  start: LatLon;
  end?: LatLon;
  waypoints?: LatLon[];
  profile: SportProfile;
  terrainPreference?: TerrainPreference;
  isLoop?: boolean;
  routeMode?: string;
  targetDistanceMiles?: number;
  name?: string;
  candidateCount?: number;
  overrideDnr?: boolean;
  findNewTrailsMode?: boolean;
  minNewTrailPercent?: number;
  minNewTrailMiles?: number;
  trailRunSteeperGrades?: boolean;
  trailRunAvoidMtbFlow?: boolean;
}): Promise<RouteOptionsResponse> {
  const payload = {
    start: { lat: params.start.lat, lon: params.start.lon, name: params.start.name },
    end: params.end ? { lat: params.end.lat, lon: params.end.lon, name: params.end.name } : undefined,
    waypoints: params.waypoints?.map(wp => ({ lat: wp.lat, lon: wp.lon, name: wp.name })),
    profile: params.profile,
    terrain_preference: params.terrainPreference,
    is_loop: params.isLoop ?? (params.routeMode === 'loop'),
    route_mode: params.routeMode ?? 'point_to_point',
    target_distance_miles: params.targetDistanceMiles,
    name: params.name,
    candidate_count: params.candidateCount ?? 10,
    override_dnr: params.overrideDnr ?? false,
    find_new_trails_mode: params.findNewTrailsMode ?? false,
    min_new_trail_percent: params.minNewTrailPercent,
    min_new_trail_miles: params.minNewTrailMiles,
    trail_run_steeper_grades: params.trailRunSteeperGrades ?? false,
    trail_run_avoid_mtb_flow: params.trailRunAvoidMtbFlow ?? true
  };

  const res = await fetch(`${API_BASE}/api/route/options`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Route options calculation failed (${res.status}): ${errorText}`);
  }

  return await res.json();
}

export function streamRouteOptions(
  params: {
    start: LatLon;
    end?: LatLon;
    waypoints?: LatLon[];
    profile: SportProfile;
    terrainPreference?: TerrainPreference;
    isLoop?: boolean;
    routeMode?: string;
    targetDistanceMiles?: number;
    name?: string;
    candidateCount?: number;
    overrideDnr?: boolean;
    findNewTrailsMode?: boolean;
    minNewTrailPercent?: number;
    minNewTrailMiles?: number;
    trailRunSteeperGrades?: boolean;
    trailRunAvoidMtbFlow?: boolean;
  },
  callbacks: {
    onCandidate: (candidate: RouteResponse) => void;
    onComplete: (count: number) => void;
    onError: (err: Error) => void;
  }
): () => void {
  const abortController = new AbortController();

  const payload = {
    start: { lat: params.start.lat, lon: params.start.lon, name: params.start.name },
    end: params.end ? { lat: params.end.lat, lon: params.end.lon, name: params.end.name } : undefined,
    waypoints: params.waypoints?.map(wp => ({ lat: wp.lat, lon: wp.lon, name: wp.name })),
    profile: params.profile,
    terrain_preference: params.terrainPreference,
    is_loop: params.isLoop ?? (params.routeMode === 'loop'),
    route_mode: params.routeMode ?? 'point_to_point',
    target_distance_miles: params.targetDistanceMiles,
    name: params.name,
    candidate_count: params.candidateCount ?? 10,
    override_dnr: params.overrideDnr ?? false,
    find_new_trails_mode: params.findNewTrailsMode ?? false,
    min_new_trail_percent: params.minNewTrailPercent,
    min_new_trail_miles: params.minNewTrailMiles,
    trail_run_steeper_grades: params.trailRunSteeperGrades ?? false,
    trail_run_avoid_mtb_flow: params.trailRunAvoidMtbFlow ?? true
  };


  (async () => {
    try {
      const res = await fetch(`${API_BASE}/api/route/options/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: abortController.signal
      });

      if (!res.ok) {
        throw new Error(`Streaming failed (${res.status}): ${await res.text()}`);
      }

      if (!res.body) {
        throw new Error('No response body for streaming');
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let count = 0;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (const part of parts) {
          const trimmed = part.trim();
          if (!trimmed) continue;

          let eventName = 'message';
          let dataStr = '';

          const lines = trimmed.split('\n');
          for (const line of lines) {
            if (line.startsWith('event:')) {
              eventName = line.substring(6).trim();
            } else if (line.startsWith('data:')) {
              dataStr += line.substring(5).trim();
            }
          }

          if (eventName === 'candidate' && dataStr) {
            try {
              const cand: RouteResponse = JSON.parse(dataStr);
              count += 1;
              callbacks.onCandidate(cand);
            } catch (err) {
              console.warn('Failed to parse candidate JSON:', err);
            }
          } else if (eventName === 'complete') {
            callbacks.onComplete(count);
          } else if (eventName === 'error') {
            callbacks.onError(new Error(dataStr || 'Streaming error'));
          }
        }
      }
      callbacks.onComplete(count);
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        callbacks.onError(err);
      }
    }
  })();

  return () => {
    abortController.abort();
  };
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

  if (navigator.share) {
    // Try file share with multiple MIME types compatible with iOS Safari & Android
    const candidateMimes = ['application/gpx+xml', 'application/octet-stream', 'text/xml', 'text/plain'];
    for (const mime of candidateMimes) {
      try {
        const file = new File([gpxContent], filename, { type: mime });
        if (navigator.canShare && navigator.canShare({ files: [file] })) {
          await navigator.share({
            title: route.name || 'Loam Route',
            text: `Open in Garmin Connect (Route Import): ${route.distance_miles.toFixed(1)} mi • +${Math.round(route.elevation_gain_ft)} ft`,
            files: [file]
          });
          return { shared: true, message: 'Phone share modal opened! Select Garmin Connect to import course.' };
        }
      } catch (e: any) {
        if (e.name === 'AbortError') {
          return { shared: false, message: 'Share sheet dismissed.' };
        }
      }
    }

    // If file sharing is not supported by device, trigger native share modal with course text/url
    try {
      await navigator.share({
        title: `${route.name || 'Loam Route'} (Garmin Course)`,
        text: `Open in Garmin Connect to import course: ${route.distance_miles.toFixed(1)} mi • +${Math.round(route.elevation_gain_ft)} ft`,
        url: window.location.href
      });
      return { shared: true, message: 'Phone share modal opened! Select Garmin Connect to import course.' };
    } catch (e: any) {
      if (e.name === 'AbortError') {
        return { shared: false, message: 'Share sheet dismissed.' };
      }
    }
  }

  // Fallback for desktop or environments without Web Share API: download GPX
  await downloadGpx(route);
  return { 
    shared: false, 
    message: 'Native phone share modal is available on mobile. GPX downloaded for Garmin route import.' 
  };
}

export async function geocodeLocations(query: string): Promise<GeocodeResult[]> {
  if (!query || !query.trim()) return [];
  try {
    const res = await fetch(`${API_BASE}/api/geocode?q=${encodeURIComponent(query.trim())}`);
    if (res.ok) {
      const data = await res.json();
      return data.results || [];
    }
  } catch (err) {
    console.warn('Geocoding request failed:', err);
  }
  return [];
}

export async function verifyAuthToken(params: {
  token?: string;
  idToken?: string;
  uid?: string;
  email?: string;
  displayName?: string;
}): Promise<AuthUser> {
  const payload = {
    token: params.token || params.idToken,
    id_token: params.idToken || params.token,
    uid: params.uid,
    email: params.email,
    display_name: params.displayName
  };

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (params.token || params.idToken) {
    headers['Authorization'] = `Bearer ${params.token || params.idToken}`;
  }

  const res = await fetch(`${API_BASE}/api/auth/verify`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Auth verification failed (${res.status}): ${errText}`);
  }

  const data = await res.json();
  const user = data.user;
  return {
    id: user.id,
    email: user.email,
    displayName: user.display_name,
    photoURL: user.photo_url,
    idToken: params.token || params.idToken
  };
}

export async function saveRouteApi(route: RouteResponse, userId = 'justin_user', token?: string): Promise<string> {
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
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-User-Id': userId
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(`${API_BASE}/api/saved-routes`, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      const data = await res.json();
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

export async function fetchSavedRoutes(userId = 'justin_user', token?: string): Promise<SavedRoute[]> {
  try {
    const headers: Record<string, string> = { 'X-User-Id': userId };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(`${API_BASE}/api/saved-routes`, { headers });
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

export async function deleteSavedRoute(id: string, userId = 'justin_user', token?: string): Promise<boolean> {
  try {
    const headers: Record<string, string> = { 'X-User-Id': userId };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(`${API_BASE}/api/saved-routes/${id}`, {
      method: 'DELETE',
      headers
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

export async function uploadActivityFile(
  file: File,
  sport: string = 'mtb',
  consentGiven: boolean = true,
  retainFile: boolean = false,
  userId: string = 'justin_default_user'
): Promise<{
  activity_id: string;
  distance_miles: number;
  duration_minutes: number;
  matched_edges_count: number;
  trimmed_points_count: number;
  message?: string;
}> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('sport', sport);
  formData.append('consent_given', String(consentGiven));
  formData.append('retain_file', String(retainFile));

  const res = await fetch(`${API_BASE}/api/activities/upload`, {
    method: 'POST',
    headers: {
      'X-User-Id': userId
    },
    body: formData
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Upload failed (${res.status}): ${errorText}`);
  }

  return await res.json();
}

// =========================================================================
// Stage 5: Trust Layer API Operations (Flags, Check-ins, DNR, Export, Delete)
// =========================================================================

export async function createFlag(
  edgeOsmId: number,
  flagType: 'gone' | 'blocked' | 'closed' | 'seasonal',
  details?: string,
  userId: string = 'justin_default_user'
): Promise<CommunityFlag> {
  const res = await fetch(`${API_BASE}/api/flags`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId
    },
    body: JSON.stringify({
      edge_osm_id: edgeOsmId,
      flag_type: flagType,
      details
    })
  });
  if (!res.ok) {
    throw new Error(`Failed to submit flag (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function listFlags(
  edgeOsmId?: number,
  status: string = 'active'
): Promise<CommunityFlag[]> {
  const params = new URLSearchParams();
  if (edgeOsmId !== undefined) params.append('edge_osm_id', String(edgeOsmId));
  if (status) params.append('status', status);

  const res = await fetch(`${API_BASE}/api/flags?${params.toString()}`);
  if (!res.ok) return [];
  return await res.json();
}

export async function voteFlag(
  flagId: number,
  voteType: 'confirm' | 'dispute',
  userId: string = 'justin_default_user'
): Promise<{ confirmed_count: number; disputed_count: number; status: string }> {
  const res = await fetch(`${API_BASE}/api/flags/${flagId}/vote`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId
    },
    body: JSON.stringify({ vote_type: voteType })
  });
  if (!res.ok) {
    throw new Error(`Vote failed (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function submitTrailCheckin(
  edgeOsmId: number,
  status: string = 'still_open',
  note?: string,
  userId: string = 'justin_default_user'
): Promise<TrailCheckin> {
  const res = await fetch(`${API_BASE}/api/trails/${edgeOsmId}/checkin`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId
    },
    body: JSON.stringify({ status, note })
  });
  if (!res.ok) {
    throw new Error(`Check-in failed (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function getTrailStatus(
  edgeOsmId: number
): Promise<{
  edge_osm_id: number;
  status: string;
  confidence_score: number;
  check_date?: string;
  snowmobile: boolean;
  recent_checkins_count: number;
  active_flags: CommunityFlag[];
}> {
  const res = await fetch(`${API_BASE}/api/trails/${edgeOsmId}/status`);
  if (!res.ok) {
    throw new Error(`Failed to fetch trail status: ${res.status}`);
  }
  return await res.json();
}

export async function listUserDNR(
  userId: string = 'justin_default_user'
): Promise<UserDNR[]> {
  const res = await fetch(`${API_BASE}/api/user/dnr`, {
    headers: { 'X-User-Id': userId }
  });
  if (!res.ok) return [];
  return await res.json();
}

export async function createUserDNR(
  data: {
    name: string;
    dnr_type: 'trail' | 'area';
    edge_osm_id?: number;
    geom?: any;
    is_soft?: boolean;
    reason?: string;
  },
  userId: string = 'justin_default_user'
): Promise<UserDNR> {
  const res = await fetch(`${API_BASE}/api/user/dnr`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId
    },
    body: JSON.stringify({
      name: data.name,
      dnr_type: data.dnr_type,
      edge_osm_id: data.edge_osm_id,
      geom: data.geom,
      is_soft: data.is_soft ?? true,
      reason: data.reason
    })
  });
  if (!res.ok) {
    throw new Error(`Failed to create DNR (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function deleteUserDNR(
  dnrId: number,
  userId: string = 'justin_default_user'
): Promise<boolean> {
  const res = await fetch(`${API_BASE}/api/user/dnr/${dnrId}`, {
    method: 'DELETE',
    headers: { 'X-User-Id': userId }
  });
  return res.ok;
}

export async function exportMyData(
  userId: string = 'justin_default_user'
): Promise<UserDataExport> {
  const res = await fetch(`${API_BASE}/api/privacy/export`, {
    headers: { 'X-User-Id': userId }
  });
  if (!res.ok) {
    throw new Error(`Export failed (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function deleteMyAccount(
  userId: string = 'justin_default_user'
): Promise<{ status: string; user_id: string }> {
  const res = await fetch(`${API_BASE}/api/privacy/account`, {
    method: 'DELETE',
    headers: { 'X-User-Id': userId }
  });
  if (!res.ok) {
    throw new Error(`Account deletion failed (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

// =========================================================================
// Stage 6: Differentiators API Client Methods
// =========================================================================

export async function getUnriddenTrails(params?: {
  lat?: number;
  lon?: number;
  radiusMiles?: number;
  sport?: string;
  userId?: string;
}): Promise<UnriddenTrailItem[]> {
  const lat = params?.lat ?? 44.0536;
  const lon = params?.lon ?? -71.1285;
  const query = new URLSearchParams({
    lat: lat.toString(),
    lon: lon.toString(),
    radius_miles: (params?.radiusMiles ?? 15).toString(),
    sport: params?.sport ?? 'mtb'
  });
  const res = await fetch(`${API_BASE}/api/trails/new-to-me?${query.toString()}`, {
    headers: { 'X-User-Id': params?.userId ?? 'justin_default_user' }
  });
  if (!res.ok) {
    throw new Error(`Failed to load unridden trails: ${await res.text()}`);
  }
  return await res.json();
}

export async function submitTrail(params: {
  name: string;
  sport: string;
  difficulty: string;
  coordinates: number[][];
  description?: string;
  userId?: string;
}): Promise<TrailSubmission> {
  const res = await fetch(`${API_BASE}/api/submissions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': params.userId ?? 'justin_default_user'
    },
    body: JSON.stringify(params)
  });
  if (!res.ok) {
    throw new Error(`Failed to submit trail: ${await res.text()}`);
  }
  return await res.json();
}

export async function listSubmissions(status?: string): Promise<TrailSubmission[]> {
  const query = status ? `?status=${status}` : '';
  const res = await fetch(`${API_BASE}/api/submissions${query}`);
  if (!res.ok) {
    throw new Error(`Failed to list submissions: ${await res.text()}`);
  }
  return await res.json();
}

export async function submitTrailEvidence(
  submissionId: number,
  evidence: { activity_id?: string; coordinates?: number[][] },
  userId: string = 'justin_default_user'
): Promise<any> {
  const res = await fetch(`${API_BASE}/api/submissions/${submissionId}/evidence`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId
    },
    body: JSON.stringify(evidence)
  });
  if (!res.ok) {
    throw new Error(`Failed to submit evidence: ${await res.text()}`);
  }
  return await res.json();
}

export async function adminApproveSubmission(submissionId: number): Promise<TrailSubmission> {
  const res = await fetch(`${API_BASE}/api/submissions/${submissionId}/approve`, {
    method: 'POST'
  });
  if (!res.ok) {
    throw new Error(`Failed to approve submission: ${await res.text()}`);
  }
  return await res.json();
}

export async function adminRejectSubmission(submissionId: number, reason?: string): Promise<TrailSubmission> {
  const res = await fetch(`${API_BASE}/api/submissions/${submissionId}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'reject', reason })
  });
  if (!res.ok) {
    throw new Error(`Failed to reject submission: ${await res.text()}`);
  }
  return await res.json();
}

export async function adminReverseSubmission(submissionId: number): Promise<TrailSubmission> {
  const res = await fetch(`${API_BASE}/api/submissions/${submissionId}/reverse`, {
    method: 'POST'
  });
  if (!res.ok) {
    throw new Error(`Failed to reverse submission: ${await res.text()}`);
  }
  return await res.json();
}

export async function adminTakedownSubmission(submissionId: number, reason?: string): Promise<TrailSubmission> {
  const res = await fetch(`${API_BASE}/api/submissions/${submissionId}/takedown`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'takedown', reason })
  });
  if (!res.ok) {
    throw new Error(`Failed to take down submission: ${await res.text()}`);
  }
  return await res.json();
}

export async function getConnectors(userId: string = 'justin_default_user'): Promise<ConnectorStatus[]> {
  const res = await fetch(`${API_BASE}/api/connectors`, {
    headers: { 'X-User-Id': userId }
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch connectors: ${await res.text()}`);
  }
  return await res.json();
}

export async function connectGarmin(
  credentials: { username: string; password: string; import_to_heat?: boolean; mfa_code?: string; mfa_session_id?: string },
  userId: string = 'justin_default_user'
): Promise<any> {
  const res = await fetch(`${API_BASE}/api/connectors/garmin/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId
    },
    body: JSON.stringify({
      username: credentials.username,
      password: credentials.password,
      import_to_heat: credentials.import_to_heat ?? true,
      mfa_code: credentials.mfa_code,
      mfa_session_id: credentials.mfa_session_id
    })
  });
  if (!res.ok) {
    throw new Error(`Garmin login failed: ${await res.text()}`);
  }
  return await res.json();
}

export async function verifyGarminMfa(
  mfaSessionId: string,
  mfaCode: string,
  importToHeat: boolean = true,
  userId: string = 'justin_default_user'
): Promise<any> {
  const res = await fetch(`${API_BASE}/api/connectors/garmin/verify-mfa`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId
    },
    body: JSON.stringify({
      mfa_session_id: mfaSessionId,
      mfa_code: mfaCode,
      import_to_heat: importToHeat
    })
  });
  if (!res.ok) {
    throw new Error(`Garmin 2FA verification failed: ${await res.text()}`);
  }
  return await res.json();
}

export async function bulkImportGarmin(
  importToHeat: boolean = true,
  userId: string = 'justin_default_user'
): Promise<any> {
  const res = await fetch(`${API_BASE}/api/connectors/garmin/bulk-import`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId
    },
    body: JSON.stringify({ import_to_heat: importToHeat })
  });
  if (!res.ok) {
    throw new Error(`Garmin bulk import failed: ${await res.text()}`);
  }
  return await res.json();
}

export async function connectTrailforks(
  credentials: { username?: string; token?: string },
  userId: string = 'justin_default_user'
): Promise<any> {
  const res = await fetch(`${API_BASE}/api/connectors/trailforks/auth`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId
    },
    body: JSON.stringify(credentials)
  });
  if (!res.ok) {
    throw new Error(`Trailforks connection failed: ${await res.text()}`);
  }
  return await res.json();
}

export async function connectStrava(
  params: { code?: string; personal_token?: string },
  userId: string = 'justin_default_user'
): Promise<any> {
  const res = await fetch(`${API_BASE}/api/connectors/strava/auth`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId
    },
    body: JSON.stringify(params)
  });
  if (!res.ok) {
    throw new Error(`Strava auth failed: ${await res.text()}`);
  }
  return await res.json();
}

export async function getDevStatus(devKey?: string, idToken?: string, userEmail?: string): Promise<any> {
  const headers: Record<string, string> = {};
  if (devKey) headers['X-Dev-Key'] = devKey;
  if (idToken) headers['Authorization'] = `Bearer ${idToken}`;
  if (userEmail) headers['X-User-Id'] = userEmail;

  const res = await fetch(`${API_BASE}/api/dev/status`, { headers });
  if (!res.ok) {
    throw new Error(`Dev status check failed (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function clearDevCache(devKey?: string, idToken?: string, userEmail?: string): Promise<any> {
  const headers: Record<string, string> = {};
  if (devKey) headers['X-Dev-Key'] = devKey;
  if (idToken) headers['Authorization'] = `Bearer ${idToken}`;
  if (userEmail) headers['X-User-Id'] = userEmail;

  const res = await fetch(`${API_BASE}/api/dev/cache/clear`, { method: 'POST', headers });
  if (!res.ok) {
    throw new Error(`Cache clear failed (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function recalculateDevHeat(devKey?: string, idToken?: string, userEmail?: string): Promise<any> {
  const headers: Record<string, string> = {};
  if (devKey) headers['X-Dev-Key'] = devKey;
  if (idToken) headers['Authorization'] = `Bearer ${idToken}`;
  if (userEmail) headers['X-User-Id'] = userEmail;

  const res = await fetch(`${API_BASE}/api/dev/heat/recalculate`, { method: 'POST', headers });
  if (!res.ok) {
    throw new Error(`Heat recalculation failed (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function syncConnector(
  provider: string,
  userId: string = 'justin_default_user',
  importToHeat: boolean = true
): Promise<any> {
  const res = await fetch(`${API_BASE}/api/connectors/${provider}/sync`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId
    },
    body: JSON.stringify({ import_to_heat: importToHeat })
  });
  if (!res.ok) {
    throw new Error(`Sync failed: ${await res.text()}`);
  }
  return await res.json();
}

export async function disconnectConnector(
  provider: string,
  userId: string = 'justin_default_user'
): Promise<any> {
  const res = await fetch(`${API_BASE}/api/connectors/${provider}`, {
    method: 'DELETE',
    headers: { 'X-User-Id': userId }
  });
  if (!res.ok) {
    throw new Error(`Disconnect failed: ${await res.text()}`);
  }
  return await res.json();
}

export async function fetchHeatTrails(sport?: string): Promise<{ type: string; features: any[] }> {
  const url = sport ? `${API_BASE}/api/heat/trails?sport=${encodeURIComponent(sport)}` : `${API_BASE}/api/heat/trails`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to load heat trails (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}



