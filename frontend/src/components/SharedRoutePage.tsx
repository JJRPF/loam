import React, { useEffect, useMemo, useState } from 'react';
import {
  copyFriendRoute, copySharedRoute, downloadFriendRoute, downloadSharedRoute, fetchFriendRoute, fetchSharedRoute,
  LinkGoneError, shareRouteGarmin, type SharedRoute
} from '../services/api';
import { useAuth } from '../services/auth';
import { MapView } from './MapView';
import { ElevationProfile } from './ElevationProfile';
import { SignInCard } from './SignInCard';
import { LegalLinks } from './LegalLinks';
import { sharedToRoute as toRoute } from './SharedWithMe';
import { formatGain } from '../format';

/** What a shared route is opened from: a public link (token) or a friend's share (id, signed in). */
export type SharedSource = { kind: 'link'; token: string } | { kind: 'friend'; id: number };

export function tokenFromPath(path: string, prefix: string): string {
  return decodeURIComponent(path.slice(prefix.length).split('/')[0] ?? '');
}

const page: React.CSSProperties = { width: '100%', height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--color-panel-bg)', color: 'var(--color-text-primary)' };
const muted: React.CSSProperties = { fontSize: 13, lineHeight: '18px', color: 'var(--color-text-secondary)' };

const Header: React.FC = () => (
  <header style={{ padding: '10px 16px', backgroundColor: 'var(--color-header-bg)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
    <a href="/" aria-label="Loam home" style={{ display: 'inline-flex', alignItems: 'center', minHeight: 44 }}>
      <img src="/brand/loam-logo-horizontal-reversed.svg" alt="loam" style={{ height: 26, width: 'auto', display: 'block' }} />
    </a>
  </header>
);

/** A route that is gone, never existed or was revoked: one friendly page for all three (the server answers the same). */
export const LinkGone: React.FC = () => (
  <div style={page}>
    <Header />
    <main style={{ flex: 1, overflowY: 'auto', padding: '32px 16px', display: 'flex', justifyContent: 'center' }}>
      <div style={{ maxWidth: 440, width: '100%', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h1 style={{ fontSize: 22, lineHeight: '28px', fontWeight: 700 }}>This link no longer works</h1>
        <p style={{ fontSize: 15, lineHeight: '22px' }}>
          The person who shared this route may have stopped sharing it, or the link may be mistyped. Ask them for a new link.
        </p>
        <a href="/" className="btn-primary" style={{ textDecoration: 'none', width: 'fit-content' }}>Plan a route on Loam</a>
      </div>
    </main>
  </div>
);

export const SharedRoutePage: React.FC<{ source: SharedSource }> = ({ source }) => {
  const { user } = useAuth();
  const [shared, setShared] = useState<SharedRoute | null>(null);
  const [gone, setGone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [needSignIn, setNeedSignIn] = useState(false);
  const [isMobile, setIsMobile] = useState(window.innerWidth < 800);
  const sourceKey = source.kind === 'link' ? source.token : `f${source.id}`;

  useEffect(() => {
    document.title = 'A route shared on Loam';
    const meta = document.createElement('meta');
    meta.name = 'robots';
    meta.content = 'noindex, nofollow';
    document.head.appendChild(meta);
    const ref = document.createElement('meta');
    ref.name = 'referrer';
    ref.content = 'no-referrer';
    document.head.appendChild(ref);
    return () => { meta.remove(); ref.remove(); };
  }, []);

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 800);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    let ignore = false;
    setShared(null);
    setGone(false);
    setError(null);
    const load = source.kind === 'link' ? fetchSharedRoute(source.token) : fetchFriendRoute(source.id);
    load
      .then((r) => { if (!ignore) setShared(r); })
      .catch((e) => {
        if (ignore) return;
        if (e instanceof LinkGoneError || source.kind === 'friend') setGone(true);
        else setError(e instanceof Error ? e.message : 'Could not open this route.');
      });
    return () => { ignore = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceKey]);

  const route = useMemo(() => (shared ? toRoute(shared) : null), [shared]);

  if (gone) return <LinkGone />;

  const run = async (what: string, fn: () => Promise<string | void>) => {
    setBusy(what);
    setError(null);
    setNotice(null);
    try {
      const msg = await fn();
      if (msg) setNotice(msg);
    } catch (e) {
      if (e instanceof LinkGoneError) setGone(true);
      else setError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      setBusy(null);
    }
  };

  const copyToMine = () => {
    if (!user) { setNeedSignIn(true); return; }
    void run('copy', async () => {
      if (source.kind === 'link') await copySharedRoute(source.token);
      else await copyFriendRoute(source.id);
      return 'Copied to your saved routes. Open the Saved tab in Loam to find it.';
    });
  };

  const download = (fmt: 'gpx' | 'fit') => run(fmt, async () => {
    if (!shared) return;
    if (source.kind === 'link') await downloadSharedRoute(source.token, fmt, shared.name);
    else await downloadFriendRoute(source.id, fmt, shared.name);
  });

  const planFromHere = () => {
    if (!route || route.coordinates.length === 0) return;
    const [lon, lat] = route.coordinates[0];
    const sport = ['mtb', 'trail_run', 'bike', 'foot'].includes(route.sport) ? route.sport : 'mtb';
    const mi = Math.min(50, Math.max(1, Math.round(route.distance_miles || 10)));
    window.location.assign(`/?sport=${sport}&start=${lat.toFixed(5)},${lon.toFixed(5)}&sn=${encodeURIComponent('Start of a shared route')}&mode=loop&mi=${mi}&terrain=60,20,10,10`);
  };

  const first = route && route.coordinates.length ? route.coordinates[0] : null;
  const start = { lat: first ? first[1] : 0, lon: first ? first[0] : 0, name: 'Start' };

  const panel = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '16px 16px 24px' }}>
      {!shared && !error && <div role="status" style={muted}>Opening the route…</div>}
      {shared && route && (
        <>
          <div role="note" style={{ border: '1px solid var(--color-divider)', background: 'var(--color-card-bg)', borderRadius: 8, padding: '10px 12px' }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>This route was shared with you</div>
            <div style={muted}>Shared by {shared.shared_by}{source.kind === 'link' ? ' with a link' : ' with their friends'}.</div>
          </div>

          <div>
            <h1 style={{ fontSize: 20, lineHeight: '26px', fontWeight: 700, overflowWrap: 'anywhere' }}>{shared.name}</h1>
            <div style={{ ...muted, textTransform: 'capitalize' }}>{shared.sport.replace('_', ' ')}</div>
          </div>

          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
            <div>
              <div className="num-tabular" style={{ fontSize: 22, fontWeight: 700, color: 'var(--color-blaze-text)' }}>{(shared.distance_miles ?? 0).toFixed(1)} mi</div>
              <div style={muted}>Distance</div>
            </div>
            <div>
              <div className="num-tabular" style={{ fontSize: 22, fontWeight: 700 }}>{formatGain(shared.elevation_gain_ft)}</div>
              <div style={muted}>Climbing</div>
            </div>
          </div>

          {shared.trimmed && (
            <p style={muted}>The sharer left out the first or last part of this route to keep their start private.</p>
          )}

          <ElevationProfile
            coordinates={route.coordinates}
            surfaceStrip={route.surface_strip}
            surfaceBreakdown={route.surface_breakdown}
            distanceMiles={route.distance_miles}
            elevationGainFt={route.elevation_gain_ft}
            elevationLossFt={route.elevation_loss_ft}
          />

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button type="button" className="btn-secondary" style={{ flex: '1 1 140px' }} disabled={busy !== null} onClick={() => download('gpx')}>Download GPX</button>
              <button type="button" className="btn-secondary" style={{ flex: '1 1 140px' }} disabled={busy !== null} onClick={() => download('fit')}>Download FIT</button>
            </div>
            <button
              type="button"
              className="btn-secondary"
              disabled={busy !== null}
              onClick={() => run('garmin', async () => (await shareRouteGarmin(route)).message)}
            >
              Send to Garmin Connect
            </button>
            <button type="button" className="btn-primary" disabled={busy !== null} onClick={copyToMine}>Copy to my routes</button>
            <button type="button" className="btn-outline" onClick={planFromHere}>Plan a route from here</button>
          </div>

          {needSignIn && !user && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ fontSize: 14, fontWeight: 700 }}>Sign in to copy this route to your account</div>
              <SignInCard />
            </div>
          )}
          {needSignIn && user && !notice && (
            <button type="button" className="btn-primary" onClick={copyToMine}>Copy to my routes</button>
          )}
        </>
      )}
      {notice && <div role="status" style={{ fontSize: 13, color: 'var(--color-lichen)' }}>{notice}</div>}
      {error && <div role="alert" style={{ fontSize: 13, color: 'var(--color-blaze-text)' }}>{error}</div>}
      <div style={{ borderTop: '1px solid var(--color-divider)', paddingTop: 4 }}>
        <p style={{ ...muted, marginTop: 8 }}>Loam plans mountain bike and trail running routes on real trails.</p>
        <LegalLinks />
      </div>
    </div>
  );

  return (
    <div style={{ ...page, overflow: 'hidden' }}>
      <Header />
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: isMobile ? 'column' : 'row' }}>
        <main style={{ order: isMobile ? 2 : 1, width: isMobile ? '100%' : 420, minWidth: isMobile ? 0 : 420, flex: isMobile ? 1 : undefined, minHeight: 0, overflowY: 'auto', borderRight: isMobile ? undefined : '1px solid var(--color-divider)' }}>
          {panel}
        </main>
        <div role="region" aria-label="Route map" style={{ order: isMobile ? 1 : 2, flex: isMobile ? '0 0 38%' : 1, minHeight: 0, position: 'relative' }}>
          {route && first ? (
            <MapView route={route} start={start} isDarkMode />
          ) : (
            <div style={{ width: '100%', height: '100%', background: 'var(--color-bg-subtle)' }} />
          )}
        </div>
      </div>
    </div>
  );
};

export default SharedRoutePage;
