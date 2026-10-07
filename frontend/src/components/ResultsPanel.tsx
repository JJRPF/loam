import React, { useState } from 'react';
import type { RouteResponse } from '../types';
import { ElevationProfile } from './ElevationProfile';
import { downloadGpx, downloadFit, shareRouteGarmin, saveRouteApi } from '../services/api';

interface ResultsPanelProps {
  route: RouteResponse;
  onBackToPlan: () => void;
  onScrubCoord?: (coord: [number, number] | null, index: number | null) => void;
  onRouteSaved?: () => void;
}

export const ResultsPanel: React.FC<ResultsPanelProps> = ({
  route,
  onBackToPlan,
  onScrubCoord,
  onRouteSaved
}) => {
  const [isExportingGpx, setIsExportingGpx] = useState(false);
  const [isExportingFit, setIsExportingFit] = useState(false);
  const [isSharing, setIsSharing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [savedStatus, setSavedStatus] = useState<string | null>(null);
  const [shareStatus, setShareStatus] = useState<string | null>(null);

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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '4px 0 24px 0' }}>
      
      {/* Top Bar with Back Button & Match Score Badge */}
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
          <span style={{ fontSize: 12, fontWeight: 600, color: '#3F6C8F' }}>Match Score:</span>
          <span className="num-tabular" style={{ fontSize: 16, fontWeight: 700, color: '#1D3B34' }}>
            {route.match_score || 95}
          </span>
        </div>
      </div>

      {/* Main Stats Header */}
      <div style={{ backgroundColor: '#FFFFFF', padding: 14, borderRadius: 8, border: '1px solid #D1D8D8' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
          <div>
            <h2 style={{ fontSize: 18, fontWeight: 700, color: '#1D3B34', marginBottom: 2 }}>
              {route.name || 'Loam Route'}
            </h2>
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
      </div>

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
