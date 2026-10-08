import React, { useState } from 'react';
import type { RouteResponse } from '../types';
import { CandidateCard } from './CandidateCard';
import { ElevationProfile } from './ElevationProfile';
import { 
  downloadGpx, downloadFit, shareRouteGarmin, saveRouteApi,
  submitTrailCheckin, createFlag
} from '../services/api';

interface ResultsPanelProps {
  route: RouteResponse;
  options?: RouteResponse[];
  onSelectRoute?: (route: RouteResponse) => void;
  onHoverRoute?: (route: RouteResponse | null) => void;
  onBackToPlan: () => void;
  onScrubCoord?: (coord: [number, number] | null, index: number | null) => void;
  onRouteSaved?: () => void;
  isLoading?: boolean;
}

export const ResultsPanel: React.FC<ResultsPanelProps> = ({
  route,
  options = [],
  onSelectRoute,
  onHoverRoute,
  onBackToPlan,
  onScrubCoord,
  onRouteSaved,
  isLoading = false
}) => {
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
      await downloadGpx(route);
    } catch (e: any) {
      alert(`GPX Export failed: ${e.message}`);
    } finally {
      setIsExportingGpx(false);
    }
  };

  const handleDownloadFit = async () => {
    setIsExportingFit(true);
    try {
      await downloadFit(route);
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
      const res = await shareRouteGarmin(route);
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
      await saveRouteApi(route);
      setSavedStatus('Saved to Profile!');
      onRouteSaved?.();
      setTimeout(() => setSavedStatus(null), 3000);
    } catch (e: any) {
      alert(`Save failed: ${e.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const hours = Math.floor(route.duration_minutes / 60);
  const mins = Math.round(route.duration_minutes % 60);
  const durationText = hours > 0 ? `${hours}h ${mins}m` : `${mins} min`;
  const breakdown = route.score_breakdown;

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

        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, backgroundColor: '#E2ECF3', padding: '4px 10px', borderRadius: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: '#3F6C8F' }}>
            {options.length > 0 ? `${options.length} Candidate Routes` : 'Selected Route'}
          </span>
          {isLoading && (
            <span style={{ fontSize: 11, color: '#FF5B14', fontWeight: 700 }}>
              (Streaming...)
            </span>
          )}
        </div>
      </div>

      {/* Candidate Route Cards List (Grid / Streamed Cards) */}
      {options.length > 1 && (
        <section style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <label style={{ fontSize: 13, fontWeight: 700, color: '#1D3B34' }}>
              Distinct Candidate Options ({options.length})
            </label>
            <span style={{ fontSize: 11, color: '#42675E' }}>Tap to inspect on map</span>
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
              const isSelected = opt.name === route.name || (opt.id && opt.id === route.id) || (!opt.id && idx === 0);
              return (
                <CandidateCard
                  key={opt.id || `${opt.name}-${idx}`}
                  route={opt}
                  isSelected={isSelected}
                  onSelect={() => onSelectRoute?.(opt)}
                  onHover={onHoverRoute}
                />
              );
            })}
          </div>
        </section>
      )}

      {/* Active Route Detailed Header */}
      <div style={{ backgroundColor: '#FFFFFF', padding: 14, borderRadius: 8, border: '1px solid #D1D8D8' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
              {route.sector && (
                <span style={{ fontSize: 11, fontWeight: 700, backgroundColor: '#1D3B34', color: '#FFFFFF', padding: '1px 6px', borderRadius: 4 }}>
                  {route.sector}
                </span>
              )}
              <h2 style={{ fontSize: 18, fontWeight: 700, color: '#1D3B34', margin: 0 }}>
                {route.name || 'Loam Route'}
              </h2>
            </div>
            <div style={{ fontSize: 12, color: '#42675E', textTransform: 'capitalize' }}>
              Sport: {route.sport.replace('_', ' ')}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div className="num-tabular" style={{ fontSize: 26, fontWeight: 700, color: '#FF5B14', lineHeight: 1 }}>
              {route.distance_miles.toFixed(1)} <span style={{ fontSize: 14 }}>mi</span>
            </div>
            <div className="num-tabular" style={{ fontSize: 13, color: '#42675E', marginTop: 2 }}>
              +{Math.round(route.elevation_gain_ft)} ft • {durationText}
            </div>
          </div>
        </div>

        {/* Verbal Explanation */}
        {route.verbal_summary && (
          <div style={{ fontSize: 13, color: '#1D3B34', backgroundColor: '#F3F7F7', padding: '8px 10px', borderRadius: 6, borderLeft: '3px solid #2E6F40', marginTop: 8 }}>
            {route.verbal_summary}
          </div>
        )}

        {/* Trust Layer Alert Banners */}
        {route.hard_block_waived && (
          <div style={{ backgroundColor: '#E8F5E9', border: '1px solid #C8E6C9', padding: '8px 12px', borderRadius: 6, fontSize: 13, color: '#1B5E20', display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
            <span>✓</span>
            <div>
              <strong>Prior-Ride Waiver Active:</strong> Hard block waived based on your verified ride history on this trail.
            </div>
          </div>
        )}

        {route.dnr_warnings && route.dnr_warnings.length > 0 && (
          <div style={{ backgroundColor: '#FFF3E0', border: '1px solid #FFE0B2', padding: '10px 12px', borderRadius: 6, fontSize: 12, color: '#E65100', marginTop: 8 }}>
            <div style={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span>⚠️</span> Soft Do-Not-Ride (DNR) Warning ({route.dnr_warnings.length})
            </div>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {route.dnr_warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
            <div style={{ fontSize: 11, color: '#BF360C', marginTop: 4 }}>
              Override permitted & logged. Score penalty applied.
            </div>
          </div>
        )}

        {route.snowmobile_warnings && route.snowmobile_warnings.length > 0 && (
          <div style={{ backgroundColor: '#E0F7FA', border: '1px solid #B2EBF2', padding: '10px 12px', borderRadius: 6, fontSize: 12, color: '#006064', marginTop: 8 }}>
            <div style={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span>❄️</span> Snowmobile Corridor Caution
            </div>
            <div>{route.snowmobile_warnings[0]}</div>
            <div style={{ fontSize: 11, color: '#00838F', marginTop: 4 }}>
              Permission-based & seasonal. Never presented as unrestricted public access.
            </div>
          </div>
        )}

        {route.community_flag_warnings && route.community_flag_warnings.length > 0 && (
          <div style={{ backgroundColor: '#FFFDE7', border: '1px solid #FFF9C4', padding: '10px 12px', borderRadius: 6, fontSize: 12, color: '#F57F17', marginTop: 8 }}>
            <div style={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span>🚩</span> Community Trail Reports ({route.community_flag_warnings.length})
            </div>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {route.community_flag_warnings.map((f, i) => (
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
            style={{ flex: 1, fontSize: 12, minHeight: 32, borderColor: '#A9BF7A', color: '#1D3B34', fontWeight: 600 }}
          >
            {isCheckinLoading ? 'Checking in...' : '✓ "Still Open" Check-in'}
          </button>
          <button
            type="button"
            onClick={() => setShowFlagModal(!showFlagModal)}
            className="btn-secondary"
            style={{ flex: 1, fontSize: 12, minHeight: 32, borderColor: '#D1D8D8', color: '#1D3B34' }}
          >
            🚩 Report Trail Issue
          </button>
        </div>

        {checkinStatus && (
          <div style={{ fontSize: 12, color: '#2E6F40', backgroundColor: '#E8F5E9', padding: '6px 10px', borderRadius: 4, marginTop: 6 }}>
            {checkinStatus}
          </div>
        )}

        {showFlagModal && (
          <div style={{ backgroundColor: '#F8F9FA', border: '1px solid #D1D8D8', borderRadius: 6, padding: 10, marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#1D3B34' }}>Report Trail Condition</div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12 }}>
              <label>
                Type:{' '}
                <select
                  value={flagType}
                  onChange={(e) => setFlagType(e.target.value as any)}
                  style={{ padding: '4px 6px', borderRadius: 4, border: '1px solid #D1D8D8' }}
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
              style={{ padding: '6px 8px', borderRadius: 4, border: '1px solid #D1D8D8', fontSize: 12 }}
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
              <div style={{ fontSize: 11, color: '#2E6F40' }}>{flagStatus}</div>
            )}
          </div>
        )}
      </div>

      {/* 5-Component Composite Score Breakdown Section */}
      {breakdown && (
        <section style={{ backgroundColor: '#FFFFFF', borderRadius: 8, border: '1px solid #D1D8D8', overflow: 'hidden' }}>
          <div
            onClick={() => setShowScoreBreakdown(!showScoreBreakdown)}
            style={{
              padding: '10px 14px',
              backgroundColor: '#F3F7F7',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              cursor: 'pointer'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: '#1D3B34' }}>
                Composite Score Breakdown
              </span>
              <span className="num-tabular" style={{ fontSize: 14, fontWeight: 700, color: '#FF5B14', backgroundColor: '#FFFFFF', padding: '2px 8px', borderRadius: 4, border: '1px solid #D1D8D8' }}>
                {route.match_score ?? breakdown.composite} / 100
              </span>
            </div>
            <span style={{ fontSize: 12, color: '#3F6C8F', fontWeight: 600 }}>
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
                { label: '5% Penalties (Repetition & DNR)', val: breakdown.penalties, color: '#1D3B34' }
              ].map(item => (
                <div key={item.label}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 3 }}>
                    <span style={{ color: '#1D3B34', fontWeight: 600 }}>{item.label}</span>
                    <span className="num-tabular" style={{ fontWeight: 700, color: '#1D3B34' }}>
                      {item.val.toFixed(0)} / 100
                    </span>
                  </div>
                  <div style={{ height: 6, borderRadius: 3, backgroundColor: '#E7ECEC', overflow: 'hidden' }}>
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
        coordinates={route.coordinates}
        surfaceStrip={route.surface_strip}
        surfaceBreakdown={route.surface_breakdown}
        distanceMiles={route.distance_miles}
        elevationGainFt={route.elevation_gain_ft}
        elevationLossFt={route.elevation_loss_ft}
        onScrub={onScrubCoord}
      />

      {/* Export & Actions Section */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
        <label style={{ fontSize: 13, fontWeight: 700, color: '#1D3B34' }}>
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
            style={{ flex: 1, fontWeight: 700, color: '#1D3B34' }}
            title="Binary Garmin Course format for fenix 7 Pro / Edge"
          >
            {isExportingFit ? 'Generating FIT...' : 'Download FIT'}
          </button>

          <button
            type="button"
            onClick={handleDownloadGpx}
            disabled={isExportingGpx}
            className="btn-secondary"
            style={{ flex: 1, fontWeight: 700, color: '#1D3B34' }}
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
          style={{ width: '100%', borderColor: '#A9BF7A', color: '#1D3B34' }}
        >
          {isSaving ? 'Saving...' : savedStatus || 'Save to Profile'}
        </button>

        {shareStatus && (
          <div style={{ fontSize: 12, color: '#1D3B34', backgroundColor: '#E7ECEC', padding: '6px 10px', borderRadius: 6 }}>
            {shareStatus}
          </div>
        )}
      </section>

    </div>
  );
};
