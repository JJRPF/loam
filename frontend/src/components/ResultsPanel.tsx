import React, { useEffect, useState } from 'react';
import type { RouteResponse } from '../types';
import { CandidateCard } from './CandidateCard';
import { ElevationProfile } from './ElevationProfile';
import { formatGain } from '../format';
import { useAuth } from '../services/auth';
import { fetchWeather, fetchMyNetwork, type WeatherPeriod, type NetworkStat } from '../services/api';
import { ReportBadRouteModal } from './ReportBadRouteModal';
import { 
  downloadGpx, downloadFit, shareRouteGarmin, saveRouteApi,
  submitTrailCheckin, createFlag
} from '../services/api';

interface ResultsPanelProps {
  route?: RouteResponse | null;
  options?: RouteResponse[];
  onSelectRoute?: (route: RouteResponse) => void;
  onHoverRoute?: (route: RouteResponse | null) => void;
  onBackToPlan: () => void;
  onScrubCoord?: (coord: [number, number] | null, index: number | null) => void;
  onRouteSaved?: () => void;
  isLoading?: boolean;
  noTrueLoopNearHere?: boolean;
  nearbyStartSuggestion?: string;
  optionsNotice?: string;
  /** The request body that produced these options (sent along with a bad-route report). */
  searchRequest?: Record<string, unknown> | null;
}

export const ResultsPanel: React.FC<ResultsPanelProps> = ({
  route,
  options = [],
  onSelectRoute,
  onHoverRoute,
  onBackToPlan,
  onScrubCoord,
  onRouteSaved,
  isLoading = false,
  noTrueLoopNearHere = false,
  nearbyStartSuggestion,
  optionsNotice,
  searchRequest = null
}) => {
  const { user: signedInUser } = useAuth();
  const [reportTarget, setReportTarget] = useState<RouteResponse | null>(null);
  const [weather, setWeather] = useState<WeatherPeriod[] | null>(null);
  const [network, setNetwork] = useState<NetworkStat | null>(null);
  const wxRoute = route || (options.length > 0 ? options[0] : null);
  const wxLon = wxRoute?.coordinates?.[0]?.[0];
  const wxLat = wxRoute?.coordinates?.[0]?.[1];
  const wxKey = wxLat !== undefined && wxLon !== undefined ? `${wxLat.toFixed(1)},${wxLon.toFixed(1)}` : null;
  useEffect(() => {
    let ignore = false;
    setWeather(null);
    if (wxLat !== undefined && wxLon !== undefined) {
      fetchWeather(wxLat, wxLon).then((p) => { if (!ignore) setWeather(p); });
    }
    return () => { ignore = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wxKey]);

  // Contributor perk: how much of the nearby network this rider has ridden (only their own rides count).
  const signedInId = signedInUser?.id;
  useEffect(() => {
    let ignore = false;
    setNetwork(null);
    if (signedInId && wxLat !== undefined && wxLon !== undefined) {
      fetchMyNetwork(wxLat, wxLon).then((n) => { if (!ignore) setNetwork(n); });
    }
    return () => { ignore = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wxKey, signedInId]);
  const [isExportingGpx, setIsExportingGpx] = useState(false);
  const [isExportingFit, setIsExportingFit] = useState(false);
  const [isSharing, setIsSharing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [savedStatus, setSavedStatus] = useState<string | null>(null);
  const [shareStatus, setShareStatus] = useState<string | null>(null);
  const [showScoreBreakdown, setShowScoreBreakdown] = useState(true);

  // Trust Layer States
  const [checkinStatus, setCheckinStatus] = useState<string | null>(null);
  const [isCheckinLoading, setIsCheckinLoading] = useState(false);
  const [showFlagModal, setShowFlagModal] = useState(false);
  const [flagType, setFlagType] = useState<'gone' | 'blocked' | 'closed' | 'seasonal'>('blocked');
  const [flagDetails, setFlagDetails] = useState('');
  const [flagStatus, setFlagStatus] = useState<string | null>(null);

  // Loading skeleton while initial candidates are streaming
  if (!route && isLoading && options.length === 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '4px 0 24px 0' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <button
            type="button"
            onClick={onBackToPlan}
            className="btn-outline"
            style={{ fontSize: 13, padding: '4px 10px', minHeight: 32 }}
          >
            &larr; Edit Plan
          </button>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, backgroundColor: 'var(--color-slate-light, #E2ECF3)', padding: '4px 10px', borderRadius: 6 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-blaze, #FF5B14)' }}>
              Building candidate routes...
            </span>
          </div>
        </div>

        <div
          style={{
            backgroundColor: 'var(--color-card-bg, #FFFFFF)',
            padding: 32,
            borderRadius: 8,
            border: '1px solid var(--color-divider, #D1D8D8)',
            textAlign: 'center',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 12
          }}
        >
          <div style={{ fontSize: 36 }}>🧭</div>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', margin: 0 }}>
            Building Trail Routes...
          </h2>
          <p style={{ fontSize: 13, color: 'var(--color-text-secondary, #42675E)', maxWidth: 320, lineHeight: 1.4, margin: 0 }}>
            Calculating distinct candidate options, elevation profiles, surface strips, and recency heat.
          </p>
          <div
            style={{
              width: '100%',
              maxWidth: 200,
              height: 6,
              backgroundColor: 'var(--color-bg-subtle, #F3F7F7)',
              borderRadius: 3,
              overflow: 'hidden',
              marginTop: 8
            }}
          >
            <div
              style={{
                width: '75%',
                height: '100%',
                backgroundColor: 'var(--color-blaze, #FF5B14)',
                borderRadius: 3
              }}
            />
          </div>
        </div>
      </div>
    );
  }

  // Active route fallback
  const activeRoute: RouteResponse | null = route || (options.length > 0 ? options[0] : null);

  if (!activeRoute) {
    if (noTrueLoopNearHere) {
      return (
        <div style={{ padding: 24, textAlign: 'center', backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '2px solid #EF4444' }}>
          <div style={{ fontSize: 32, marginBottom: 8 }}>⚠️</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#DC2626', marginBottom: 4 }}>
            No true loop near here
          </div>
          <div style={{ fontSize: 13, color: 'var(--color-text-secondary, #42675E)', marginBottom: 16, lineHeight: 1.4 }}>
            {nearbyStartSuggestion || 'All routes in this network retrace > 10% of their distance. Try disabling "Loops only" or starting from a nearby junction.'}
          </div>
          <button
            type="button"
            onClick={onBackToPlan}
            className="btn-primary"
            style={{ width: '100%' }}
          >
            Adjust Plan
          </button>
        </div>
      );
    }
    return (
      <div style={{ padding: 24, textAlign: 'center', backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)' }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', marginBottom: 4 }}>
          No active route
        </div>
        <div style={{ fontSize: 13, color: 'var(--color-text-secondary, #42675E)', marginBottom: 16 }}>
          Configure your starting point and terrain preferences in the Plan tab, then tap "Build Routes".
        </div>
        <button
          type="button"
          onClick={onBackToPlan}
          className="btn-primary"
          style={{ width: '100%' }}
        >
          Go to Plan
        </button>
      </div>
    );
  }

  const handleCheckin = async () => {
    setIsCheckinLoading(true);
    try {
      const edgeId = 999202;
      const res = await submitTrailCheckin(edgeId, 'still_open', 'Checked in via Loam UI');
      setCheckinStatus(`✓ Trail checked in as still open! (Confidence: ${Math.round(res.confidence_score * 100)}%)`);
      setTimeout(() => setCheckinStatus(null), 4000);
    } catch (e: any) {
      setCheckinStatus(`Check-in: ${e.message}`);
    } finally {
      setIsCheckinLoading(false);
    }
  };

  const handleReportFlag = async () => {
    try {
      const edgeId = 999101;
      await createFlag(edgeId, flagType, flagDetails);
      setFlagStatus('✓ Flag submitted to community!');
      setTimeout(() => {
        setFlagStatus(null);
        setShowFlagModal(false);
        setFlagDetails('');
      }, 2000);
    } catch (e: any) {
      alert(`Flag failed: ${e.message}`);
    }
  };

  const handleDownloadGpx = async () => {
    setIsExportingGpx(true);
    try {
      await downloadGpx(activeRoute);
    } catch (e: any) {
      alert(`GPX Export failed: ${e.message}`);
    } finally {
      setIsExportingGpx(false);
    }
  };

  const handleDownloadFit = async () => {
    setIsExportingFit(true);
    try {
      await downloadFit(activeRoute);
    } catch (e: any) {
      alert(`FIT Export failed: ${e.message}`);
    } finally {
      setIsExportingFit(false);
    }
  };

  const handleShareGarmin = async () => {
    setIsSharing(true);
    setShareStatus(null);
    try {
      const res = await shareRouteGarmin(activeRoute);
      setShareStatus(res.message);
    } catch (e: any) {
      setShareStatus(`Share: ${e.message}`);
    } finally {
      setIsSharing(false);
    }
  };

  const handleSaveRoute = async () => {
    setIsSaving(true);
    try {
      await saveRouteApi(activeRoute);
      setSavedStatus('Saved to your routes.');
      onRouteSaved?.();
      setTimeout(() => setSavedStatus(null), 3000);
    } catch (e: any) {
      alert(`Save failed: ${e.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const durationMins = activeRoute.duration_minutes ?? 0;
  const hours = Math.floor(durationMins / 60);
  const mins = Math.round(durationMins % 60);
  const durationText = hours > 0 ? `${hours}h ${mins}m` : `${mins} min`;
  const breakdown = activeRoute.score_breakdown;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '4px 0 24px 0' }}>
      
      {/* Top Bar with Back Button & Option Count */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <button
          type="button"
          onClick={onBackToPlan}
          className="btn-outline"
          style={{ fontSize: 13, padding: '4px 10px', minHeight: 32 }}
        >
          &larr; Edit Plan
        </button>

        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, backgroundColor: 'var(--color-slate-light, #E2ECF3)', padding: '4px 10px', borderRadius: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-slate, #3F6C8F)' }}>
            {options.length > 0 ? `${options.length} candidate ${options.length === 1 ? 'route' : 'routes'}` : 'Selected route'}
          </span>
          {isLoading && (
            <span style={{ fontSize: 11, color: 'var(--color-blaze, #FF5B14)', fontWeight: 700 }}>
              (Streaming...)
            </span>
          )}
        </div>
      </div>

      {/* Honest option count: fewer than 5 routes passed the gates */}
      {optionsNotice && !isLoading && (
        <div role="status" style={{ padding: '8px 12px', backgroundColor: 'var(--color-bg-subtle)', border: '1px solid var(--color-divider)', borderRadius: 6, marginBottom: 8, fontSize: 13, color: 'var(--color-text-primary)' }}>
          {optionsNotice}
        </div>
      )}

      {/* "No true loop near here" warning banner if only out-and-backs were generated */}
      {noTrueLoopNearHere && (
        <div style={{ padding: '10px 12px', backgroundColor: '#FEF2F2', border: '1px solid #F87171', borderRadius: 6, marginBottom: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#991B1B' }}>
            No true loop near here
          </div>
          <div style={{ fontSize: 12, color: '#7F1D1D', marginTop: 2 }}>
            {nearbyStartSuggestion || activeRoute?.nearby_start_suggestion || 'All available routes in this network retrace >10% of their distance.'}
          </div>
        </div>
      )}

      {/* Nearby Start Suggestion Banner */}
      {!noTrueLoopNearHere && (nearbyStartSuggestion || activeRoute?.nearby_start_suggestion) && (
        <div style={{ padding: '8px 12px', backgroundColor: '#F0FDF4', border: '1px solid #86EFAC', borderRadius: 6, marginBottom: 8, fontSize: 12, color: '#166534', fontWeight: 600 }}>
          💡 {nearbyStartSuggestion || activeRoute?.nearby_start_suggestion}
        </div>
      )}

      {/* Candidate Route Cards List (Streamed Cards) */}
      {options.length > 1 && (
        <section style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <label style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
              Distinct Candidate Options ({options.length})
            </label>
            <span style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)' }}>Tap to inspect on map</span>
          </div>

          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              maxHeight: 280,
              overflowY: 'auto',
              paddingRight: 4
            }}
          >
            {options.map((opt, idx) => {
              const isSelected = (opt.id && opt.id === activeRoute.id) || opt.name === activeRoute.name || (!opt.id && idx === 0);
              return (
                <CandidateCard
                  key={opt.id || `${opt.name}-${idx}`}
                  route={opt}
                  isSelected={isSelected}
                  onSelect={() => onSelectRoute?.(opt)}
                  onHover={onHoverRoute}
                  onReportBad={signedInUser ? () => setReportTarget(opt) : undefined}
                />
              );
            })}
          </div>
        </section>
      )}

      {/* Active Route Detailed Header */}
      <div style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', padding: 14, borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
              {activeRoute.sector && (
                <span style={{ fontSize: 11, fontWeight: 700, backgroundColor: 'var(--color-header-bg, #1D3B34)', color: '#FFFFFF', padding: '1px 6px', borderRadius: 4 }}>
                  {activeRoute.sector}
                </span>
              )}
              <h2 style={{ fontSize: 18, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', margin: 0 }}>
                {activeRoute.name || 'Loam Route'}
              </h2>
            </div>
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)', textTransform: 'capitalize' }}>
              Sport: {(activeRoute.sport || 'mtb').replace('_', ' ')}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div className="num-tabular" style={{ fontSize: 26, fontWeight: 700, color: 'var(--color-blaze, #FF5B14)', lineHeight: 1 }}>
              {(activeRoute.distance_miles ?? 0).toFixed(1)} <span style={{ fontSize: 14 }}>mi</span>
            </div>
            <div className="num-tabular" style={{ fontSize: 13, color: 'var(--color-text-secondary, #42675E)', marginTop: 2 }}>
              {formatGain(activeRoute.elevation_gain_ft)} • {durationText}
            </div>
          </div>
        </div>

        {/* Verbal Explanation */}
        {activeRoute.verbal_summary && (
          <div style={{ fontSize: 13, color: 'var(--color-text-primary, #1D3B34)', backgroundColor: 'var(--color-bg-subtle, #F3F7F7)', padding: '8px 10px', borderRadius: 6, borderLeft: '3px solid #2E6F40', marginTop: 8 }}>
            {activeRoute.verbal_summary}
          </div>
        )}

        {/* Trust Layer Alert Banners */}
        {activeRoute.hard_block_waived && (
          <div style={{ backgroundColor: 'rgba(46, 111, 64, 0.15)', border: '1px solid rgba(46, 111, 64, 0.3)', padding: '8px 12px', borderRadius: 6, fontSize: 13, color: '#2E6F40', display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
            <span>✓</span>
            <div>
              <strong>Prior-Ride Waiver Active:</strong> Hard block waived based on your verified ride history on this trail.
            </div>
          </div>
        )}

        {activeRoute.dnr_warnings && activeRoute.dnr_warnings.length > 0 && (
          <div style={{ backgroundColor: 'rgba(230, 81, 0, 0.12)', border: '1px solid rgba(230, 81, 0, 0.3)', padding: '10px 12px', borderRadius: 6, fontSize: 12, color: '#C73E00', marginTop: 8 }}>
            <div style={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span>⚠️</span> Soft Do-Not-Ride (DNR) Warning ({activeRoute.dnr_warnings.length})
            </div>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {activeRoute.dnr_warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
            <div style={{ fontSize: 11, color: '#C73E00', marginTop: 4 }}>
              Override permitted & logged. Score penalty applied.
            </div>
          </div>
        )}

        {activeRoute.snowmobile_warnings && activeRoute.snowmobile_warnings.length > 0 && (
          <div style={{ backgroundColor: 'rgba(0, 96, 100, 0.12)', border: '1px solid rgba(0, 96, 100, 0.3)', padding: '10px 12px', borderRadius: 6, fontSize: 12, color: '#006064', marginTop: 8 }}>
            <div style={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span>❄️</span> Snowmobile Corridor Caution
            </div>
            <div>{activeRoute.snowmobile_warnings[0]}</div>
            <div style={{ fontSize: 11, color: '#00838F', marginTop: 4 }}>
              Permission-based & seasonal. Never presented as unrestricted public access.
            </div>
          </div>
        )}

        {activeRoute.community_flag_warnings && activeRoute.community_flag_warnings.length > 0 && (
          <div style={{ backgroundColor: 'rgba(245, 127, 23, 0.12)', border: '1px solid rgba(245, 127, 23, 0.3)', padding: '10px 12px', borderRadius: 6, fontSize: 12, color: '#F57F17', marginTop: 8 }}>
            <div style={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span>🚩</span> Community Trail Reports ({activeRoute.community_flag_warnings.length})
            </div>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {activeRoute.community_flag_warnings.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Trail Trust Actions: 1-Tap Check-in & Flag Report */}
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button
            type="button"
            onClick={handleCheckin}
            disabled={isCheckinLoading}
            className="btn-secondary"
            style={{ flex: 1, fontSize: 12, minHeight: 32, borderColor: 'var(--color-lichen, #A9BF7A)', color: 'var(--color-text-primary, #1D3B34)', fontWeight: 600 }}
          >
            {isCheckinLoading ? 'Checking in...' : '✓ "Still Open" Check-in'}
          </button>
          <button
            type="button"
            onClick={() => setShowFlagModal(!showFlagModal)}
            className="btn-secondary"
            style={{ flex: 1, fontSize: 12, minHeight: 32, borderColor: 'var(--color-divider, #D1D8D8)', color: 'var(--color-text-primary, #1D3B34)' }}
          >
            🚩 Report Trail Issue
          </button>
        </div>
        <div style={{ marginTop: 8 }}>
          {signedInUser ? (
            <button
              type="button"
              onClick={() => setReportTarget(activeRoute)}
              className="btn-secondary"
              style={{ width: '100%', fontSize: 12, minHeight: 32, borderColor: 'var(--color-divider, #D1D8D8)', color: 'var(--color-text-primary, #1D3B34)' }}
            >
              Report bad route
            </button>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)', textAlign: 'center' }}>
              Sign in to report a bad route (You tab).
            </div>
          )}
        </div>
        {reportTarget && (
          <ReportBadRouteModal
            route={reportTarget}
            options={options.length > 0 ? options : [reportTarget]}
            request={searchRequest}
            onClose={() => setReportTarget(null)}
          />
        )}

        {checkinStatus && (
          <div style={{ fontSize: 12, color: '#2E6F40', backgroundColor: 'rgba(46, 111, 64, 0.15)', padding: '6px 10px', borderRadius: 4, marginTop: 6 }}>
            {checkinStatus}
          </div>
        )}

        {showFlagModal && (
          <div style={{ backgroundColor: 'var(--color-bg-subtle, #F8F9FA)', border: '1px solid var(--color-divider, #D1D8D8)', borderRadius: 6, padding: 10, marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>Report Trail Condition</div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, color: 'var(--color-text-primary, #1D3B34)' }}>
              <label>
                Type:{' '}
                <select
                  value={flagType}
                  onChange={(e) => setFlagType(e.target.value as any)}
                  style={{ padding: '4px 6px', borderRadius: 4, border: '1px solid var(--color-divider, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)' }}
                >
                  <option value="blocked">Blocked (Trees/Mud)</option>
                  <option value="gone">Gone / Overgrown</option>
                  <option value="closed">Closed</option>
                  <option value="seasonal">Seasonal Mud Alert</option>
                </select>
              </label>
            </div>
            <input
              type="text"
              placeholder="Optional details (e.g. large oak down 0.5mi in)"
              value={flagDetails}
              onChange={(e) => setFlagDetails(e.target.value)}
              style={{ padding: '6px 8px', borderRadius: 4, border: '1px solid var(--color-divider, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 12 }}
            />
            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={() => setShowFlagModal(false)}
                className="btn-outline"
                style={{ fontSize: 11, minHeight: 28, padding: '2px 8px' }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleReportFlag}
                className="btn-primary"
                style={{ fontSize: 11, minHeight: 28, padding: '2px 10px' }}
              >
                Submit Flag
              </button>
            </div>
            {flagStatus && (
              <div style={{ fontSize: 11, color: 'var(--color-lichen, #2E6F40)' }}>{flagStatus}</div>
            )}
          </div>
        )}
      </div>

      {/* 5-Component Composite Score Breakdown Section */}
      {breakdown && (
        <section style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', overflow: 'hidden' }}>
          <div
            onClick={() => setShowScoreBreakdown(!showScoreBreakdown)}
            style={{
              padding: '10px 14px',
              backgroundColor: 'var(--color-bg-subtle, #F3F7F7)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              cursor: 'pointer'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
                Composite Score Breakdown
              </span>
              <span className="num-tabular" style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-blaze, #FF5B14)', backgroundColor: 'var(--color-card-bg, #FFFFFF)', padding: '2px 8px', borderRadius: 4, border: '1px solid var(--color-divider, #D1D8D8)' }}>
                {activeRoute.match_score ?? breakdown.composite} / 100
              </span>
            </div>
            <span style={{ fontSize: 12, color: 'var(--color-slate, #3F6C8F)', fontWeight: 600 }}>
              {showScoreBreakdown ? 'Hide details' : 'Show details'}
            </span>
          </div>

          {showScoreBreakdown && (
            <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              {[
                { label: '60% Input Match (Distance & Terrain)', val: breakdown.input_match, color: '#FF5B14' },
                { label: '15% Trail Heat (Activity Recency)', val: breakdown.heat, color: '#3F6C8F' },
                { label: '10% Mode Value (Trail Quality)', val: breakdown.mode_value, color: '#2E6F40' },
                { label: '10% Quality (Surface Continuity)', val: breakdown.quality, color: '#8D6E63' },
                { label: '5% Penalties (Repetition & DNR)', val: breakdown.penalties, color: 'var(--color-slate, #3F6C8F)' }
              ].map(item => (
                <div key={item.label}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 3 }}>
                    <span style={{ color: 'var(--color-text-primary, #1D3B34)', fontWeight: 600 }}>{item.label}</span>
                    <span className="num-tabular" style={{ fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
                      {item.val.toFixed(0)} / 100
                    </span>
                  </div>
                  <div style={{ height: 6, borderRadius: 3, backgroundColor: 'var(--color-divider, #E7ECEC)', overflow: 'hidden' }}>
                    <div
                      style={{
                        width: `${Math.min(100, Math.max(0, item.val))}%`,
                        height: '100%',
                        backgroundColor: item.color,
                        borderRadius: 3,
                        transition: 'width 0.3s ease'
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Interactive Elevation Profile & Signature Surface Strip */}
      <ElevationProfile
        coordinates={activeRoute.coordinates || []}
        surfaceStrip={activeRoute.surface_strip || []}
        surfaceBreakdown={activeRoute.surface_breakdown || {}}
        distanceMiles={activeRoute.distance_miles ?? 0}
        elevationGainFt={activeRoute.elevation_gain_ft}
        elevationLossFt={activeRoute.elevation_loss_ft}
        onScrub={onScrubCoord}
      />

      {/* Forecast at the start (National Weather Service); hidden when unavailable */}
      {weather && weather.length > 0 && (
        <section aria-label="Forecast at the start" style={{ fontSize: 12, color: 'var(--color-text-primary, #1D3B34)' }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Forecast at the start</div>
          <div style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 4 }}>
            {weather.slice(0, 8).map((p) => (
              <div key={p.start} style={{ flex: '0 0 auto', minWidth: 62, textAlign: 'center', padding: '4px 6px', borderRadius: 6, border: '1px solid var(--color-divider, #D1D8D8)' }}>
                <div className="num-tabular">{new Date(p.start).toLocaleTimeString([], { hour: 'numeric' })}</div>
                <div className="num-tabular" style={{ fontWeight: 700 }}>{p.temp_f !== null ? `${p.temp_f}°F` : '-'}</div>
                <div>{p.precip_pct !== null ? `${p.precip_pct}% rain` : ''}</div>
              </div>
            ))}
          </div>
          <div style={{ color: 'var(--color-text-secondary, #42675E)' }}>{weather[0].summary}. Source: National Weather Service.</div>
        </section>
      )}

      {network && network.ridden_percent !== null && network.ridden_miles > 0 && (
        <div style={{ fontSize: 12, color: 'var(--color-text-primary, #1D3B34)' }}>
          You have ridden {network.ridden_percent}% of the trail network within {network.radius_mi} mi of here
          ({network.ridden_miles} of {network.trail_miles} mi).
        </div>
      )}

      {/* Cue sheet from OSM trail names */}
      {activeRoute.cues && activeRoute.cues.length > 1 && (
        <details style={{ fontSize: 12, color: 'var(--color-text-primary, #1D3B34)' }}>
          <summary style={{ fontWeight: 700, cursor: 'pointer', minHeight: 32 }}>Directions ({activeRoute.cues.length} steps)</summary>
          <ol style={{ margin: '6px 0 0', paddingLeft: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
            {activeRoute.cues.map((c, i) => (
              <li key={i} style={{ display: 'flex', gap: 8 }}>
                <span className="num-tabular" style={{ minWidth: 48, color: 'var(--color-text-secondary, #42675E)' }}>{c.distance_miles.toFixed(1)} mi</span>
                <span>{c.text}</span>
              </li>
            ))}
          </ol>
          <div style={{ color: 'var(--color-text-secondary, #42675E)', marginTop: 4 }}>Trail names come from OpenStreetMap. This is a list to read, not voice navigation.</div>
        </details>
      )}

      {/* Export & Actions Section */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
        <label style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
          Garmin & Device Export
        </label>

        {/* Primary Garmin Action: Share to Garmin Connect */}
        <button
          type="button"
          onClick={handleShareGarmin}
          disabled={isSharing}
          className="btn-primary"
          style={{ width: '100%' }}
        >
          {isSharing ? 'Sharing...' : 'Share to Garmin Connect'}
        </button>

        {/* Export Buttons: GPX and FIT */}
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            type="button"
            onClick={handleDownloadFit}
            disabled={isExportingFit}
            className="btn-secondary"
            style={{ flex: 1, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}
            title="Binary Garmin Course format for fenix 7 Pro / Edge"
          >
            {isExportingFit ? 'Generating FIT...' : 'Download FIT'}
          </button>

          <button
            type="button"
            onClick={handleDownloadGpx}
            disabled={isExportingGpx}
            className="btn-secondary"
            style={{ flex: 1, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}
            title="Standard GPS Track XML"
          >
            {isExportingGpx ? 'Generating GPX...' : 'Download GPX'}
          </button>
        </div>

        {/* Save Route Action */}
        <button
          type="button"
          onClick={handleSaveRoute}
          disabled={isSaving}
          className="btn-secondary"
          style={{ width: '100%', borderColor: 'var(--color-lichen, #A9BF7A)', color: 'var(--color-text-primary, #1D3B34)' }}
        >
          {isSaving ? 'Saving...' : savedStatus || 'Save to Profile'}
        </button>

        {shareStatus && (
          <div style={{ fontSize: 12, color: 'var(--color-text-primary, #1D3B34)', backgroundColor: 'var(--color-bg-subtle, #E7ECEC)', padding: '6px 10px', borderRadius: 6 }}>
            {shareStatus}
          </div>
        )}
      </section>

    </div>
  );
};

export default ResultsPanel;
