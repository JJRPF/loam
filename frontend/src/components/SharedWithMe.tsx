import React, { useCallback, useEffect, useState } from 'react';
import type { RouteResponse } from '../types';
import {
  copyFriendRoute, downloadFriendRoute, fetchFriendRoute, listFriendRoutes, type FriendRouteSummary, type SharedRoute
} from '../services/api';
import { formatGain } from '../format';

export function sharedToRoute(s: SharedRoute): RouteResponse {
  const lons = s.coordinates.map((c) => c[0]);
  const lats = s.coordinates.map((c) => c[1]);
  const miles = s.distance_miles ?? 0;
  return {
    name: s.name, sport: s.sport, distance_miles: miles, duration_minutes: miles * 6,
    elevation_gain_ft: s.elevation_gain_ft, elevation_loss_ft: s.elevation_loss_ft,
    surface_breakdown: s.surface_breakdown, surface_strip: s.surface_strip, coordinates: s.coordinates,
    bbox: s.coordinates.length ? [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)] : [],
    warnings: []
  };
}

const small: React.CSSProperties = { fontSize: 12, minHeight: 44, padding: '2px 10px' };

/** "Shared with me": routes friends shared with their friends. Opening one shows it like any route. */
export const SharedWithMe: React.FC<{ onLoadRoute: (route: RouteResponse) => void; onCopied: () => void }> = ({ onLoadRoute, onCopied }) => {
  const [routes, setRoutes] = useState<FriendRouteSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRoutes(await listFriendRoutes());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load routes shared with you.');
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const run = async (fn: () => Promise<unknown>, done?: string) => {
    setError(null);
    setNotice(null);
    try {
      await fn();
      if (done) setNotice(done);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.');
      void load(); // it may have just been unshared
    }
  };

  if (routes.length === 0 && !error) return null;

  return (
    <section aria-labelledby="shared-with-me" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <h3 id="shared-with-me" style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text-primary)' }}>Shared with me</h3>
      {routes.map((r) => (
        <div key={r.id} style={{ backgroundColor: 'var(--color-card-bg)', borderRadius: 8, border: '1px solid var(--color-divider)', padding: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 15, fontWeight: 700, overflowWrap: 'anywhere' }}>{r.name}</div>
              <div style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>From {r.shared_by}</div>
            </div>
            <div style={{ textAlign: 'right', flexShrink: 0 }}>
              <div className="num-tabular" style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-blaze-text)' }}>{(r.distance_miles ?? 0).toFixed(1)} mi</div>
              <div className="num-tabular" style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>{formatGain(r.elevation_gain_ft)}</div>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            <button type="button" className="btn-outline" style={small} onClick={() => void run(async () => onLoadRoute(sharedToRoute(await fetchFriendRoute(r.id))))}>Inspect</button>
            <button type="button" className="btn-outline" style={small} onClick={() => void run(async () => { await copyFriendRoute(r.id); onCopied(); }, 'Copied to your saved routes.')}>Copy to my routes</button>
            <button type="button" className="btn-outline" style={small} onClick={() => void run(() => downloadFriendRoute(r.id, 'gpx', r.name))}>GPX</button>
          </div>
        </div>
      ))}
      {notice && <div role="status" style={{ fontSize: 13, color: 'var(--color-lichen)' }}>{notice}</div>}
      {error && <div role="alert" style={{ fontSize: 13, color: 'var(--color-blaze-text)' }}>{error}</div>}
    </section>
  );
};

export default SharedWithMe;
