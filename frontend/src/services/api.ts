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
  GeocodeResult
} from '../types';


import { getIdToken } from './auth';
import { formatGain } from '../format';

// '' in dev (proxied by Vite); the production build sets VITE_API_BASE to the API's public origin
export const API_BASE: string = ((import.meta.env.VITE_API_BASE as string | undefined) ?? '').replace(/\/+$/, '');

/** A 429 from the server: its message is friendly and safe to show to people as is. */
export class RateLimitError extends Error {
  retryAfter?: number;
  constructor(message: string, retryAfter?: number) {
    super(message);
    this.name = 'RateLimitError';
    this.retryAfter = retryAfter;
  }
}

/** Builds the RateLimitError for a 429 response (the server's `detail` is the message). */
export async function rateLimitError(res: Response): Promise<RateLimitError> {
  let detail = 'Too many requests. Please wait a moment and try again.';
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') detail = body.detail;
  } catch {
    // not JSON: keep the generic message
  }
  return new RateLimitError(detail, Number(res.headers.get('Retry-After')) || undefined);
}

/**
 * fetch() that sends the signed-in user's Firebase ID token as a bearer token.
 * On a 401 it refreshes the token once and retries. Signed out, it sends no Authorization header.
 */
export async function authedFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const send = async (forceRefresh: boolean) => {
    const token = await getIdToken(forceRefresh);
    const headers = new Headers(init.headers || {});
    if (token) headers.set('Authorization', `Bearer ${token}`);
    return fetch(input, { ...init, headers });
  };
  const res = await send(false);
  if (res.status === 401 && (await getIdToken(false))) {
    return send(true);
  }
  return res;
}

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

  const res = await authedFetch(`${API_BASE}/api/route`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (res.status === 429) throw await rateLimitError(res);
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
  loopsOnly?: boolean;
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
    trail_run_avoid_mtb_flow: params.trailRunAvoidMtbFlow ?? true,
    loops_only: params.loopsOnly ?? false
  };

  const res = await authedFetch(`${API_BASE}/api/route/options`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (res.status === 429) throw await rateLimitError(res);
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
    loopsOnly?: boolean;
  },
  callbacks: {
    onCandidate: (candidate: RouteResponse) => void;
    onComplete: (count: number, info?: { notice?: string | null; nearby_start_suggestion?: string | null }) => void;
    onError: (err: Error) => void;
    /** Called with the exact request body sent, so a later "Report bad route" can include it. */
    onRequest?: (payload: Record<string, unknown>) => void;
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
    trail_run_avoid_mtb_flow: params.trailRunAvoidMtbFlow ?? true,
    loops_only: params.loopsOnly ?? false
  };
  callbacks.onRequest?.(payload);

  (async () => {
    try {
      const res = await authedFetch(`${API_BASE}/api/route/options/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: abortController.signal
      });

      if (res.status === 429) throw await rateLimitError(res);
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
      let completed = false;

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
            let info = {};
            try { info = JSON.parse(dataStr); } catch { /* older servers sent no details */ }
            callbacks.onComplete(count, info);
            completed = true;
          } else if (eventName === 'error') {
            let info: any = null;
            try { info = JSON.parse(dataStr); } catch { /* plain text error */ }
            if (info?.status === 429) {
              callbacks.onError(new RateLimitError(info.error, Number(info.retry_after) || undefined));
            } else {
              callbacks.onError(new Error(info?.error || dataStr || 'Streaming error'));
            }
          }
        }
      }
      if (!completed) callbacks.onComplete(count);
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
    const res = await authedFetch(`${API_BASE}/api/export/gpx`, {
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

  const res = await authedFetch(`${API_BASE}/api/export/fit`, {
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
            text: `Open in Garmin Connect (Route Import): ${route.distance_miles.toFixed(1)} mi • ${formatGain(route.elevation_gain_ft)}`,
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
        text: `Open in Garmin Connect to import course: ${route.distance_miles.toFixed(1)} mi • ${formatGain(route.elevation_gain_ft)}`,
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
    const res = await authedFetch(`${API_BASE}/api/geocode?q=${encodeURIComponent(query.trim())}`);
    if (res.status === 429) throw await rateLimitError(res);
    if (res.ok) {
      const data = await res.json();
      return data.results || [];
    }
  } catch (err) {
    if (err instanceof RateLimitError) throw err;  // shown inline by the search box
    console.warn('Geocoding request failed:', err);
  }
  return [];
}

export async function saveRouteApi(route: RouteResponse): Promise<string> {
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
  const res = await authedFetch(`${API_BASE}/api/saved-routes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (res.status === 401) throw new Error('Sign in to save routes.');
  if (!res.ok) throw new Error(`Saving failed (${res.status}): ${await res.text()}`);
  const data = await res.json();
  return data.id;
}

export async function fetchSavedRoutes(): Promise<SavedRoute[]> {
  const res = await authedFetch(`${API_BASE}/api/saved-routes`);
  if (res.status === 401) return [];
  if (!res.ok) throw new Error(`Could not load saved routes (${res.status})`);
  const data = await res.json();
  return data.routes || [];
}

export async function deleteSavedRoute(id: string): Promise<boolean> {
  const res = await authedFetch(`${API_BASE}/api/saved-routes/${id}`, { method: 'DELETE' });
  return res.ok;
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
    const ele = pt.length > 2 && pt[2] !== null ? `<ele>${pt[2].toFixed(1)}</ele>` : '';
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

export async function uploadActivityFile(
  file: File,
  sport: string = 'mtb',
  consentGiven: boolean = true,
  retainFile: boolean = false
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

  const res = await authedFetch(`${API_BASE}/api/activities/upload`, {
    method: 'POST',
    body: formData
  });

  if (res.status === 429) throw await rateLimitError(res);
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
  details?: string
): Promise<CommunityFlag> {
  const res = await authedFetch(`${API_BASE}/api/flags`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      edge_osm_id: edgeOsmId,
      flag_type: flagType,
      details
    })
  });
  if (res.status === 429) throw await rateLimitError(res);
  if (!res.ok) {
    throw new Error(`Failed to submit flag (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export interface BadRouteReportResult {
  id: string;
  status: 'filed' | 'pending';
  issue_url?: string | null;
  message: string;
}

/** Files a "bad route" report. The server trims the route line before it goes into the GitHub issue. */
export async function submitBadRouteReport(
  comment: string,
  request: Record<string, unknown> | null,
  route: RouteResponse,
  options: RouteResponse[],
  origin: { source?: 'search' | 'saved' | 'shared' | 'other'; savedRouteId?: string } = {}
): Promise<BadRouteReportResult> {
  const res = await authedFetch(`${API_BASE}/api/reports/bad-route`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      comment,
      request: request ?? undefined,
      // A saved route is loaded by the server from the rider's own copy, so no geometry is sent.
      route: origin.savedRouteId ? undefined : route,
      source: origin.source ?? 'search',
      saved_route_id: origin.savedRouteId,
      options: options.slice(0, 25).map((o) => ({
        id: o.id, name: o.name, distance_miles: o.distance_miles, route_type: o.route_type, match_score: o.match_score
      }))
    })
  });
  if (res.status === 429) throw await rateLimitError(res);
  if (res.status === 401) throw new Error('Sign in to report a route.');
  if (res.status === 404) throw new Error('That saved route no longer exists.');
  if (!res.ok) throw new Error(`Could not send the report (${res.status}).`);
  return await res.json();
}

export interface PrivacyZone {
  id: number;
  name: string;
  lat: number;
  lon: number;
  radius_m: number;
}

export async function listPrivacyZones(): Promise<PrivacyZone[]> {
  const res = await authedFetch(`${API_BASE}/api/privacy/zones`);
  if (!res.ok) throw new Error(`Failed to load privacy zones (${res.status})`);
  return await res.json();
}

export async function createPrivacyZone(zone: { name: string; lat: number; lon: number; radius_m: number }): Promise<PrivacyZone> {
  const res = await authedFetch(`${API_BASE}/api/privacy/zones`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(zone)
  });
  if (!res.ok) throw new Error(`Failed to save the privacy zone (${res.status})`);
  return await res.json();
}

export async function deletePrivacyZone(id: number): Promise<void> {
  const res = await authedFetch(`${API_BASE}/api/privacy/zones/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Failed to delete the privacy zone (${res.status})`);
}

export async function getContribution(): Promise<boolean> {
  const res = await authedFetch(`${API_BASE}/api/privacy/consent`);
  if (!res.ok) throw new Error(`Failed to load consent (${res.status})`);
  return Boolean((await res.json()).consent_given);
}

export async function setContribution(consentGiven: boolean): Promise<boolean> {
  const res = await authedFetch(`${API_BASE}/api/privacy/consent?consent_given=${consentGiven}`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed to save consent (${res.status})`);
  return Boolean((await res.json()).consent_given);
}

export async function listFlags(
  edgeOsmId?: number,
  status: string = 'active'
): Promise<CommunityFlag[]> {
  const params = new URLSearchParams();
  if (edgeOsmId !== undefined) params.append('edge_osm_id', String(edgeOsmId));
  if (status) params.append('status', status);

  const res = await authedFetch(`${API_BASE}/api/flags?${params.toString()}`);
  if (!res.ok) return [];
  return await res.json();
}

export async function voteFlag(
  flagId: number,
  voteType: 'confirm' | 'dispute'
): Promise<{ confirmed_count: number; disputed_count: number; status: string }> {
  const res = await authedFetch(`${API_BASE}/api/flags/${flagId}/vote`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ vote_type: voteType })
  });
  if (res.status === 429) throw await rateLimitError(res);
  if (!res.ok) {
    throw new Error(`Vote failed (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function submitTrailCheckin(
  edgeOsmId: number,
  status: string = 'still_open',
  note?: string
): Promise<TrailCheckin> {
  const res = await authedFetch(`${API_BASE}/api/trails/${edgeOsmId}/checkin`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ status, note })
  });
  if (res.status === 429) throw await rateLimitError(res);
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
  const res = await authedFetch(`${API_BASE}/api/trails/${edgeOsmId}/status`);
  if (!res.ok) {
    throw new Error(`Failed to fetch trail status: ${res.status}`);
  }
  return await res.json();
}

export async function listUserDNR(
): Promise<UserDNR[]> {
  const res = await authedFetch(`${API_BASE}/api/user/dnr`);
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
  }
): Promise<UserDNR> {
  const res = await authedFetch(`${API_BASE}/api/user/dnr`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
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
  dnrId: number
): Promise<boolean> {
  const res = await authedFetch(`${API_BASE}/api/user/dnr/${dnrId}`, {
    method: 'DELETE'
  });
  return res.ok;
}

export async function exportMyData(
): Promise<UserDataExport> {
  const res = await authedFetch(`${API_BASE}/api/privacy/export`, {});
  if (!res.ok) {
    throw new Error(`Export failed (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function deleteMyAccount(
): Promise<{ status: string; user_id: string }> {
  const res = await authedFetch(`${API_BASE}/api/privacy/account`, {
    method: 'DELETE'
  });
  if (!res.ok) {
    throw new Error(`Account deletion failed (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

// =========================================================================
// Stage 6: Differentiators API Client Methods
// =========================================================================

export async function getUnriddenTrails(params: {
  lat: number;
  lon: number;
  radiusMiles?: number;
  sport?: string;
}): Promise<UnriddenTrailItem[]> {
  const query = new URLSearchParams({
    lat: params.lat.toString(),
    lon: params.lon.toString(),
    radius_miles: (params.radiusMiles ?? 15).toString(),
    sport: params.sport ?? 'mtb'
  });
  const res = await authedFetch(`${API_BASE}/api/trails/new-to-me?${query.toString()}`);
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
}): Promise<TrailSubmission> {
  const res = await authedFetch(`${API_BASE}/api/submissions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
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
  const res = await authedFetch(`${API_BASE}/api/submissions${query}`);
  if (!res.ok) {
    throw new Error(`Failed to list submissions: ${await res.text()}`);
  }
  return await res.json();
}

export async function submitTrailEvidence(
  submissionId: number,
  evidence: { activity_id?: string; coordinates?: number[][] }
): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/submissions/${submissionId}/evidence`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(evidence)
  });
  if (!res.ok) {
    throw new Error(`Failed to submit evidence: ${await res.text()}`);
  }
  return await res.json();
}

export async function adminApproveSubmission(submissionId: number): Promise<TrailSubmission> {
  const res = await authedFetch(`${API_BASE}/api/submissions/${submissionId}/approve`, {
    method: 'POST'
  });
  if (!res.ok) {
    throw new Error(`Failed to approve submission: ${await res.text()}`);
  }
  return await res.json();
}

export async function adminRejectSubmission(submissionId: number, reason?: string): Promise<TrailSubmission> {
  const res = await authedFetch(`${API_BASE}/api/submissions/${submissionId}/reject`, {
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
  const res = await authedFetch(`${API_BASE}/api/submissions/${submissionId}/reverse`, {
    method: 'POST'
  });
  if (!res.ok) {
    throw new Error(`Failed to reverse submission: ${await res.text()}`);
  }
  return await res.json();
}

export async function adminTakedownSubmission(submissionId: number, reason?: string): Promise<TrailSubmission> {
  const res = await authedFetch(`${API_BASE}/api/submissions/${submissionId}/takedown`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'takedown', reason })
  });
  if (!res.ok) {
    throw new Error(`Failed to take down submission: ${await res.text()}`);
  }
  return await res.json();
}

export async function getConnectors(): Promise<ConnectorStatus[]> {
  const res = await authedFetch(`${API_BASE}/api/connectors`, {});
  if (!res.ok) {
    throw new Error(`Failed to fetch connectors: ${await res.text()}`);
  }
  return await res.json();
}

export async function connectGarmin(
  credentials: { username: string; password: string; import_to_heat?: boolean; mfa_code?: string; mfa_session_id?: string }
): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/connectors/garmin/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
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
  importToHeat: boolean = true
): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/connectors/garmin/verify-mfa`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
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
  importToHeat: boolean = true
): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/connectors/garmin/bulk-import`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ import_to_heat: importToHeat })
  });
  if (!res.ok) {
    throw new Error(`Garmin bulk import failed: ${await res.text()}`);
  }
  return await res.json();
}

export async function connectTrailforks(
  credentials: { username?: string; token?: string }
): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/connectors/trailforks/auth`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(credentials)
  });
  if (!res.ok) {
    throw new Error(`Trailforks connection failed: ${await res.text()}`);
  }
  return await res.json();
}

export async function connectStrava(
  params: { code?: string; personal_token?: string }
): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/connectors/strava/auth`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(params)
  });
  if (!res.ok) {
    throw new Error(`Strava auth failed: ${await res.text()}`);
  }
  return await res.json();
}

export async function getAuthMe(): Promise<{ id: string; email: string | null; display_name: string | null; is_admin: boolean }> {
  const res = await authedFetch(`${API_BASE}/api/auth/me`);
  if (!res.ok) {
    throw new Error(`Not signed in (${res.status})`);
  }
  return await res.json();
}

export async function getDevStatus(): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/dev/status`);
  if (!res.ok) {
    throw new Error(`Dev status check failed (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function clearDevCache(): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/dev/cache/clear`, { method: 'POST' });
  if (!res.ok) {
    throw new Error(`Cache clear failed (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function recalculateDevHeat(): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/dev/heat/recalculate`, { method: 'POST' });
  if (!res.ok) {
    throw new Error(`Heat recalculation failed (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function syncConnector(
  provider: string,
  importToHeat: boolean = true
): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/connectors/${provider}/sync`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ import_to_heat: importToHeat })
  });
  if (!res.ok) {
    throw new Error(`Sync failed: ${await res.text()}`);
  }
  return await res.json();
}

export async function disconnectConnector(
  provider: string
): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/connectors/${provider}`, {
    method: 'DELETE'
  });
  if (!res.ok) {
    throw new Error(`Disconnect failed: ${await res.text()}`);
  }
  return await res.json();
}

export interface HeatMeta { min_unique_riders: number; seed_heat_public: boolean }

export function heatInfoText(meta: HeatMeta): string {
  const base = `Heat shows trails ridden by ${meta.min_unique_riders} or more people in the past year.`;
  return meta.seed_heat_public ? `${base} To get started, it also includes Loam's creator's own rides on trails.` : base;
}

export async function fetchHeatMeta(): Promise<HeatMeta> {
  const res = await authedFetch(`${API_BASE}/api/heat/meta`);
  if (!res.ok) throw new Error(`Heat settings unavailable (${res.status})`);
  return await res.json();
}

export async function fetchHeatTrails(sport?: string): Promise<{ type: string; features: any[] }> {
  const url = sport ? `${API_BASE}/api/heat/trails?sport=${encodeURIComponent(sport)}` : `${API_BASE}/api/heat/trails`;
  const res = await authedFetch(url);
  if (!res.ok) {
    throw new Error(`Failed to load heat trails (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function fetchOtmTrails(params: {
  minLat: number;
  minLon: number;
  maxLat: number;
  maxLon: number;
  sport?: string;
}): Promise<{ type: string; features: any[] }> {
  const sport = params.sport ?? 'mtb';
  const url = `${API_BASE}/api/otm/trails?min_lat=${params.minLat}&min_lon=${params.minLon}&max_lat=${params.maxLat}&max_lon=${params.maxLon}&sport=${encodeURIComponent(sport)}`;
  const res = await authedFetch(url);
  if (!res.ok) {
    throw new Error(`Failed to load trails (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function fetchOtmTrailDetails(osmWayId: number): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/otm/trail/${osmWayId}`);
  if (!res.ok) {
    throw new Error(`Failed to load trail details (${res.status}): ${await res.text()}`);
  }
  return await res.json();
}

export async function importCubeTrekActivity(
  urlOrId: string,
  sport: string = 'mtb',
  name?: string,
  importToHeat: boolean = true
): Promise<any> {
  const res = await authedFetch(`${API_BASE}/api/connectors/cubetrek/import`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      url_or_id: urlOrId,
      sport,
      name,
      import_to_heat: importToHeat
    })
  });
  if (!res.ok) {
    throw new Error(`CubeTrek import failed: ${await res.text()}`);
  }
  return await res.json();
}





export interface WeatherPeriod {
  start: string;
  temp_f: number | null;
  precip_pct: number | null;
  wind: string | null;
  summary: string | null;
}

/** Hourly forecast from the National Weather Service via the API; null when it is unavailable. */
export async function fetchWeather(lat: number, lon: number): Promise<WeatherPeriod[] | null> {
  try {
    const res = await fetch(`${API_BASE}/api/weather?lat=${lat}&lon=${lon}&hours=12`);
    if (!res.ok) return null;
    return (await res.json()).periods as WeatherPeriod[];
  } catch {
    return null;
  }
}


export interface NetworkStat {
  radius_mi: number;
  trail_miles: number;
  ridden_miles: number;
  ridden_percent: number | null;
}

/** How much of the trail network around a point the signed-in rider has ridden (their own data). */
export async function fetchMyNetwork(lat: number, lon: number): Promise<NetworkStat | null> {
  try {
    const res = await authedFetch(`${API_BASE}/api/me/network?lat=${lat}&lon=${lon}&radius_mi=10`);
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}
