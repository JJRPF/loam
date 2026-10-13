import type { LatLon, SportProfile, TerrainPreference } from './types';

/** Everything a search needs, kept in the query string so every search is a shareable link. */
export interface SearchState {
  sport: SportProfile;
  start: LatLon;
  end?: LatLon;
  waypoints: LatLon[];
  routeMode: 'loop' | 'point_to_point' | 'out_and_back';
  targetMiles: number;
  terrainPref: TerrainPreference;
  overrideDnr: boolean;
  findNewTrailsMode: boolean;
  minNewTrailPercent: number;
  loopsOnly: boolean;
}

const SPORTS = ['mtb', 'mtb_hardtail', 'mtb_fullsus', 'mtb_gravel', 'mtb_fat', 'mtb_emtb', 'trail_run', 'bike', 'foot'];
const MODES = ['loop', 'point_to_point', 'out_and_back'];

const pt = (p: LatLon) => `${p.lat.toFixed(5)},${p.lon.toFixed(5)}`;

function parsePoint(v: string | null, name?: string): LatLon | undefined {
  if (!v) return undefined;
  const [lat, lon] = v.split(',').map(Number);
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return undefined;
  return { lat, lon, name };
}

export function encodeSearch(s: SearchState): string {
  const q = new URLSearchParams();
  q.set('sport', s.sport);
  q.set('start', pt(s.start));
  if (s.start.name) q.set('sn', s.start.name);
  if (s.end && s.routeMode === 'point_to_point') q.set('end', pt(s.end));
  if (s.routeMode !== 'out_and_back') s.waypoints.forEach((w) => q.append('via', pt(w)));
  q.set('mode', s.routeMode);
  q.set('mi', String(s.targetMiles));
  const t = s.terrainPref;
  q.set('terrain', [t.singletrack, t.doubletrack, t.gravel, t.paved].map((x) => Math.round(x * 100)).join(','));
  if (s.overrideDnr) q.set('dnr', '1');
  if (s.findNewTrailsMode) q.set('new', String(s.minNewTrailPercent));
  if (s.loopsOnly) q.set('loops', '1');
  return q.toString();
}

/** The search encoded in a query string, or null when it has no (valid) start point. */
export function decodeSearch(search: string): Partial<SearchState> & { start: LatLon } | null {
  const q = new URLSearchParams(search);
  const start = parsePoint(q.get('start'), q.get('sn') || undefined);
  if (!start) return null;
  const out: Partial<SearchState> & { start: LatLon } = { start };
  const sport = q.get('sport');
  if (sport && SPORTS.includes(sport)) out.sport = sport as SportProfile;
  const mode = q.get('mode');
  if (mode && MODES.includes(mode)) out.routeMode = mode as SearchState['routeMode'];
  const mi = Number(q.get('mi'));
  if (Number.isFinite(mi) && mi >= 1 && mi <= 50) out.targetMiles = mi;
  const end = parsePoint(q.get('end'));
  if (end) out.end = end;
  out.waypoints = q.getAll('via').map((v) => parsePoint(v)).filter((p): p is LatLon => !!p).slice(0, 5);
  const terrain = (q.get('terrain') || '').split(',').map(Number);
  if (terrain.length === 4 && terrain.every((x) => Number.isFinite(x) && x >= 0)) {
    const sum = terrain.reduce((a, b) => a + b, 0);
    if (sum > 0) {
      const [singletrack, doubletrack, gravel, paved] = terrain.map((x) => x / sum);
      out.terrainPref = { singletrack, doubletrack, gravel, paved };
    }
  }
  out.overrideDnr = q.get('dnr') === '1';
  const nw = Number(q.get('new'));
  out.findNewTrailsMode = q.has('new') && Number.isFinite(nw);
  if (out.findNewTrailsMode) out.minNewTrailPercent = Math.min(80, Math.max(10, nw));
  out.loopsOnly = q.get('loops') === '1';
  return out;
}

export function writeSearchUrl(s: SearchState) {
  try {
    window.history.replaceState(null, '', `${window.location.pathname}?${encodeSearch(s)}`);
  } catch {
    // history unavailable (sandboxed frame); the link just won't update
  }
}
