import React, { useState, useEffect } from 'react';
import { 
  uploadActivityFile, listUserDNR, createUserDNR, deleteUserDNR,
  exportMyData, deleteMyAccount,
  getConnectors, connectGarmin, verifyGarminMfa, connectStrava, connectTrailforks, bulkImportGarmin,
  syncConnector, disconnectConnector, importCubeTrekActivity
} from '../services/api';
import { signOut, useAuth } from '../services/auth';
import { SignInCard } from './SignInCard';
import type { UserDNR, ConnectorStatus } from '../types';

interface YouPanelProps {
  isDarkMode?: boolean;
  onToggleDarkMode?: () => void;
}

export const YouPanel: React.FC<YouPanelProps> = ({ isDarkMode = true }) => {
  const { user: currentUser } = useAuth();
  const isSignedIn = !!currentUser;
  const [privacyZoneEnabled, setPrivacyZoneEnabled] = useState(true);
  const [dnrList, setDnrList] = useState<UserDNR[]>([]);
  const [showAddDnr, setShowAddDnr] = useState(false);
  const [newDnrName, setNewDnrName] = useState('');
  const [newDnrType, setNewDnrType] = useState<'trail' | 'area'>('trail');
  const [newDnrEdgeId, setNewDnrEdgeId] = useState('');
  const [newDnrReason, setNewDnrReason] = useState('');
  const [isExporting, setIsExporting] = useState(false);
  const [exportMessage, setExportMessage] = useState<string | null>(null);

  const loadDnr = async () => {
    try {
      const items = await listUserDNR();
      setDnrList(items);
    } catch (e) {
      console.error('Failed to load DNR', e);
    }
  };

  useEffect(() => {
    let ignore = false;
    if (!currentUser) {
      setDnrList([]);
      return;
    }
    listUserDNR()
      .then((items) => {
        if (!ignore) setDnrList(items);
      })
      .catch((e) => console.error('Failed to load DNR', e));
    return () => {
      ignore = true;
    };
  }, [currentUser]);

  const handleCreateDnr = async () => {
    if (!newDnrName.trim()) return;
    try {
      await createUserDNR({
        name: newDnrName.trim(),
        dnr_type: newDnrType,
        edge_osm_id: newDnrEdgeId ? parseInt(newDnrEdgeId) : undefined,
        reason: newDnrReason.trim() || undefined,
        is_soft: true
      });
      setNewDnrName('');
      setNewDnrEdgeId('');
      setNewDnrReason('');
      setShowAddDnr(false);
      await loadDnr();
    } catch (e: any) {
      alert(`Failed to add DNR: ${e.message}`);
    }
  };

  const handleDeleteDnr = async (id: number) => {
    try {
      await deleteUserDNR(id);
      await loadDnr();
    } catch (e: any) {
      alert(`Failed to remove DNR: ${e.message}`);
    }
  };

  const handleExportData = async () => {
    setIsExporting(true);
    setExportMessage(null);
    try {
      const data = await exportMyData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `loam_data_export_${new Date().toISOString().split('T')[0]}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setExportMessage('✓ Data export downloaded successfully!');
      setTimeout(() => setExportMessage(null), 3000);
    } catch (e: any) {
      alert(`Export failed: ${e.message}`);
    } finally {
      setIsExporting(false);
    }
  };

  const handleDeleteAccount = async () => {
    const confirmed = window.confirm(
      'Are you sure you want to permanently delete your account and all associated rides, routes, and data? This action cannot be undone.'
    );
    if (!confirmed) return;

    try {
      await deleteMyAccount();
      await signOut();
      alert('Account and all personal data permanently deleted.');
    } catch (e: any) {
      alert(`Deletion failed: ${e.message}`);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '4px 0 24px 0' }}>
      <h2 style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
        Profile & Settings
      </h2>

      <SignInCard />

      {isSignedIn && (<>
      {/* Heat v1 Activity Upload Card */}
      <div style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', padding: 14 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', marginBottom: 6 }}>
          Upload Ride / Run (Heat Ingestion)
        </h3>
        <p style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)', marginBottom: 12 }}>
          Ingest your GPX or Garmin FIT files into Loam's recency heat layer. Starts & ends are automatically trimmed by 0.2 mi.
        </p>

        <ActivityUploadWidget isDarkMode={isDarkMode} />
      </div>

      {/* Connected Services (Stage 6 & GH-19) */}
      <ConnectedServicesSection isDarkMode={isDarkMode} />

      {/* Settings & Privacy */}
      <div style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>Preferences & Privacy</h3>

        {/* Display Theme (Dark Mode Only) */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13 }}>
          <div>
            <strong>Display Theme</strong>
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>Dark Mode exclusively (Round 4)</div>
          </div>
          <span
            style={{
              fontSize: 12,
              fontWeight: 700,
              padding: '4px 10px',
              borderRadius: 6,
              backgroundColor: 'var(--color-bg-subtle, #162C27)',
              color: 'var(--color-text-primary, #E7ECEC)',
              border: '1px solid var(--color-divider, #264A42)'
            }}
          >
            🌙 Dark Mode
          </span>
        </div>

        <div style={{ borderTop: '1px solid var(--color-divider, #E7ECEC)', paddingTop: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13 }}>
          <div>
            <strong>Distance & Elevation Units</strong>
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>Miles & Feet (Fixed policy)</div>
          </div>
          <span style={{ fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>Imperial (mi / ft)</span>
        </div>

        <div style={{ borderTop: '1px solid var(--color-divider, #E7ECEC)', paddingTop: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13 }}>
          <div>
            <strong>Endpoint Trimming Protection</strong>
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>Automatically strip first & last 0.2 mi of ride uploads</div>
          </div>
          <input
            type="checkbox"
            checked={privacyZoneEnabled}
            onChange={(e) => setPrivacyZoneEnabled(e.target.checked)}
            style={{ width: 18, height: 18, accentColor: 'var(--color-blaze, #FF5B14)' }}
          />
        </div>

        <div style={{ borderTop: '1px solid var(--color-divider, #E7ECEC)', paddingTop: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13 }}>
          <div>
            <strong>Privacy Threshold Invariant</strong>
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>Public routes only influenced when ≥ 3 unique riders contribute</div>
          </div>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>≥ 3 Riders</span>
        </div>

        <div style={{ borderTop: '1px solid var(--color-divider, #E7ECEC)', paddingTop: 10, fontSize: 13 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <strong>DNR (Do Not Ride) Trail List</strong>
            <button
              type="button"
              onClick={() => setShowAddDnr(!showAddDnr)}
              className="btn-outline"
              style={{ fontSize: 12, padding: '2px 8px', minHeight: 28 }}
            >
              {showAddDnr ? 'Cancel' : '+ Add DNR'}
            </button>
          </div>
          <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)', marginTop: 2, marginBottom: 8 }}>
            Manage private or overgrown trails you wish the router to strictly avoid.
          </div>

          {showAddDnr && (
            <div style={{ backgroundColor: 'var(--color-bg-subtle, #F3F7F7)', border: '1px solid var(--color-divider, #D1D8D8)', borderRadius: 6, padding: 10, marginBottom: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>Add Do-Not-Ride Rule</div>
              <input
                type="text"
                placeholder="Name / Label (e.g. Overgrown Logging Rd)"
                value={newDnrName}
                onChange={(e) => setNewDnrName(e.target.value)}
                style={{ padding: '6px 8px', borderRadius: 4, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13 }}
              />
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12 }}>
                <label>
                  Type:{' '}
                  <select
                    value={newDnrType}
                    onChange={(e) => setNewDnrType(e.target.value as any)}
                    style={{ padding: '4px 6px', borderRadius: 4, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)' }}
                  >
                    <option value="trail">Trail (OSM Way ID)</option>
                    <option value="area">Area Boundary</option>
                  </select>
                </label>
                {newDnrType === 'trail' && (
                  <input
                    type="number"
                    placeholder="OSM Edge ID (e.g. 999101)"
                    value={newDnrEdgeId}
                    onChange={(e) => setNewDnrEdgeId(e.target.value)}
                    style={{ flex: 1, padding: '4px 6px', borderRadius: 4, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 12 }}
                  />
                )}
              </div>
              <input
                type="text"
                placeholder="Reason (e.g. Private signs, active logging, blowdowns)"
                value={newDnrReason}
                onChange={(e) => setNewDnrReason(e.target.value)}
                style={{ padding: '6px 8px', borderRadius: 4, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13 }}
              />
              <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  onClick={() => setShowAddDnr(false)}
                  className="btn-outline"
                  style={{ fontSize: 12, minHeight: 28, padding: '2px 8px' }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleCreateDnr}
                  className="btn-primary"
                  style={{ fontSize: 12, minHeight: 28, padding: '2px 10px' }}
                >
                  Save DNR
                </button>
              </div>
            </div>
          )}

          {dnrList.length === 0 ? (
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #6A7D78)', fontStyle: 'italic', padding: '6px 0' }}>
              No custom DNR rules configured.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 }}>
              {dnrList.map(item => (
                <div
                  key={item.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '6px 10px',
                    backgroundColor: 'var(--color-bg-subtle, #F8F9FA)',
                    borderRadius: 6,
                    border: '1px solid var(--color-divider, #E0E0E0)',
                    fontSize: 12
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--color-text-primary, #1D3B34)' }}>
                      {item.name}
                      <span style={{ fontSize: 10, marginLeft: 6, padding: '1px 5px', borderRadius: 3, backgroundColor: item.is_soft ? 'rgba(230,81,0,0.15)' : 'rgba(198,40,40,0.15)', color: item.is_soft ? '#FF8C42' : '#FF6B6B', fontWeight: 700 }}>
                        {item.is_soft ? 'Soft DNR' : 'Hard DNR'}
                      </span>
                    </div>
                    {item.reason && <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)' }}>{item.reason}</div>}
                    {item.edge_osm_id && <div style={{ fontSize: 10, color: 'var(--color-text-secondary, #888)' }}>OSM ID: {item.edge_osm_id}</div>}
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDeleteDnr(item.id)}
                    style={{
                      border: 'none',
                      backgroundColor: 'transparent',
                      color: 'var(--color-blaze, #FF5B14)',
                      fontSize: 14,
                      cursor: 'pointer',
                      padding: '4px 6px'
                    }}
                    title="Remove DNR rule"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Privacy & Compliance (GDPR/CCPA/Full Export & Deletion) */}
      <div style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', margin: 0 }}>
          Data Rights & Privacy Compliance
        </h3>
        <p style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)', margin: 0 }}>
          You have complete ownership of your data under Loam's privacy guarantees. Raw GPS tracks are discarded after matching; personal rides are never exposed to other users.
        </p>

        {exportMessage && (
          <div style={{ fontSize: 12, color: '#A9BF7A', backgroundColor: 'var(--color-bg-subtle, #162C27)', padding: '6px 10px', borderRadius: 4, border: '1px solid var(--color-divider)' }}>
            {exportMessage}
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
          <button
            type="button"
            onClick={handleExportData}
            disabled={isExporting}
            className="btn-secondary"
            style={{ flex: 1, fontSize: 12, minHeight: 34 }}
          >
            {isExporting ? 'Preparing Export...' : '⬇ Export My Data (JSON)'}
          </button>
          <button
            type="button"
            onClick={handleDeleteAccount}
            className="btn-outline"
            style={{ flex: 1, fontSize: 12, minHeight: 34, color: 'var(--color-blaze, #FF5B14)', borderColor: 'var(--color-divider)' }}
          >
            Delete Account & Rides
          </button>
        </div>
      </div>

      </>)}

      {/* About & Stack & Dev Tools Link */}
      <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)', textAlign: 'center', lineHeight: 1.6, marginTop: 16 }}>
        <div>loam Trail Route Builder • Stage 4 Heat v1</div>
        <div>Built with MapLibre GL JS, GraphHopper & PostGIS</div>
        <div style={{ marginTop: 8 }}>
          <a
            href="#/dev"
            style={{
              fontSize: 11,
              color: 'var(--color-text-secondary, #42675E)',
              textDecoration: 'underline'
            }}
          >
            Developer Tools & Operations
          </a>
        </div>
      </div>
    </div>
  );
};

const ActivityUploadWidget: React.FC<{ isDarkMode?: boolean }> = () => {
  const [file, setFile] = useState<File | null>(null);
  const [sport, setSport] = useState('mtb');
  const [consent, setConsent] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    setResult(null);

    try {
      const res = await uploadActivityFile(file, sport, consent, false);
      setResult(res);
      setFile(null);
    } catch (err: any) {
      setError(err.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <input
        type="file"
        accept=".gpx,.fit"
        onChange={(e) => setFile(e.target.files?.[0] || null)}
        style={{ fontSize: 13, color: 'var(--color-text-primary, #1D3B34)' }}
      />

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', fontSize: 13, color: 'var(--color-text-primary, #1D3B34)' }}>
        <label>
          Sport:{' '}
          <select
            value={sport}
            onChange={(e) => setSport(e.target.value)}
            style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)' }}
          >
            <option value="mtb">MTB</option>
            <option value="trail_run">Trail Run</option>
            <option value="mtb_gravel">Gravel</option>
          </select>
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            style={{ accentColor: 'var(--color-blaze, #FF5B14)' }}
          />
          Contribute Heat
        </label>
      </div>

      <button
        type="button"
        disabled={!file || uploading}
        onClick={handleUpload}
        className="btn-primary"
        style={{ width: '100%', fontSize: 13, minHeight: 36, opacity: !file || uploading ? 0.6 : 1 }}
      >
        {uploading ? 'Processing & Map-Matching...' : 'Upload & Map-Match Track'}
      </button>

      {result && (
        <div style={{ backgroundColor: 'var(--color-bg-subtle, #F3F7F7)', border: '1px solid var(--color-divider, #B0C4DE)', borderRadius: 6, padding: 10, fontSize: 12, color: 'var(--color-text-primary, #1D3B34)' }}>
          <div style={{ fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>Upload & Map-Match Complete</div>
          <div>Distance: {result.distance_miles} mi • Matched edges: {result.matched_edges_count}</div>
          {result.message && <div style={{ color: 'var(--color-blaze, #8B4513)', marginTop: 4 }}>{result.message}</div>}
        </div>
      )}

      {error && (
        <div style={{ backgroundColor: 'rgba(255, 91, 20, 0.1)', border: '1px solid var(--color-blaze, #FF5B14)', borderRadius: 6, padding: 10, fontSize: 12, color: 'var(--color-blaze, #FF5B14)' }}>
          {error}
        </div>
      )}
    </div>
  );
};

const ConnectedServicesSection: React.FC<{ isDarkMode?: boolean }> = ({ isDarkMode = false }) => {
  const [connectors, setConnectors] = useState<ConnectorStatus[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  // Garmin connect form state
  const [showGarminModal, setShowGarminModal] = useState(false);
  const [garminUser, setGarminUser] = useState('');
  const [garminPass, setGarminPass] = useState('');
  const [garminImportHeat, setGarminImportHeat] = useState(true);
  const [garminSubmitting, setGarminSubmitting] = useState(false);
  const [garminNeedsMfa, setGarminNeedsMfa] = useState(false);
  const [garminMfaSessionId, setGarminMfaSessionId] = useState('');
  const [garminMfaCode, setGarminMfaCode] = useState('');
  const [garminMfaMessage, setGarminMfaMessage] = useState('');
  const [garminError, setGarminError] = useState<string | null>(null);

  // Trailforks connect form state
  const [showTrailforksModal, setShowTrailforksModal] = useState(false);
  const [tfUsername, setTfUsername] = useState('');
  const [tfToken, setTfToken] = useState('');
  const [tfSubmitting, setTfSubmitting] = useState(false);

  // Strava connect form state (Personal Token)
  const [showStravaModal, setShowStravaModal] = useState(false);
  const [stravaToken, setStravaToken] = useState('');
  const [stravaSubmitting, setStravaSubmitting] = useState(false);
  const [stravaError, setStravaError] = useState<string | null>(null);

  // CubeTrek import modal state
  const [showCubeTrekModal, setShowCubeTrekModal] = useState(false);
  const [cubetrekUrl, setCubetrekUrl] = useState('');
  const [cubetrekSport, setCubetrekSport] = useState('mtb');
  const [cubetrekName, setCubetrekName] = useState('');
  const [cubetrekImportHeat, setCubetrekImportHeat] = useState(true);
  const [cubetrekSubmitting, setCubetrekSubmitting] = useState(false);
  const [cubetrekResult, setCubetrekResult] = useState<any>(null);
  const [cubetrekError, setCubetrekError] = useState<string | null>(null);

  const { user: currentUser } = useAuth();

  const handleImportCubeTrek = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cubetrekUrl.trim()) return;

    setCubetrekSubmitting(true);
    setCubetrekError(null);
    setCubetrekResult(null);

    try {
      const res = await importCubeTrekActivity(
        cubetrekUrl.trim(),
        cubetrekSport,
        cubetrekName.trim() || undefined,
        cubetrekImportHeat
      );
      setCubetrekResult(res);
      setStatusMsg(res.message || 'CubeTrek track successfully imported.');
      setTimeout(() => setStatusMsg(null), 4000);
      await loadConnectors();
    } catch (err: any) {
      setCubetrekError(err.message || 'CubeTrek track import failed');
    } finally {
      setCubetrekSubmitting(false);
    }
  };

  const loadConnectors = async () => {
    setLoading(true);
    try {
      const data = await getConnectors();
      setConnectors(data);
    } catch (err) {
      console.error('Failed to load connectors:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (currentUser) loadConnectors();
    else setConnectors([]);
  }, [currentUser]);

  const handleConnectGarmin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!garminUser.trim() || !garminPass.trim()) return;

    setGarminSubmitting(true);
    setGarminError(null);
    try {
      const res = await connectGarmin({
        username: garminUser.trim(),
        password: garminPass.trim(),
        import_to_heat: garminImportHeat
      });
      if (res.needs_mfa) {
        setGarminNeedsMfa(true);
        setGarminMfaSessionId(res.mfa_session_id || '');
        setGarminMfaMessage(res.message || 'Garmin Two-Factor Authentication required. Please enter the security code sent to your email or phone.');
        return;
      }
      setShowGarminModal(false);
      setGarminUser('');
      setGarminPass('');
      setGarminNeedsMfa(false);
      setGarminMfaSessionId('');
      setGarminMfaCode('');
      setStatusMsg(res.message || 'Garmin connected! Activities synced to heat layer.');
      setTimeout(() => setStatusMsg(null), 5000);
      await loadConnectors();
    } catch (err: any) {
      setGarminError(err.message || 'Garmin connection failed. Please check credentials.');
    } finally {
      setGarminSubmitting(false);
    }
  };

  const handleVerifyGarminMfa = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!garminMfaCode.trim()) return;

    setGarminSubmitting(true);
    setGarminError(null);
    try {
      const res = await verifyGarminMfa(garminMfaSessionId, garminMfaCode.trim(), garminImportHeat);
      setShowGarminModal(false);
      setGarminNeedsMfa(false);
      setGarminMfaCode('');
      setGarminMfaSessionId('');
      setGarminUser('');
      setGarminPass('');
      setStatusMsg(res.message || 'Garmin 2FA verified! Activities synced to heat layer.');
      setTimeout(() => setStatusMsg(null), 5000);
      await loadConnectors();
    } catch (err: any) {
      setGarminError(err.message || 'Garmin 2FA code verification failed. Please try again.');
    } finally {
      setGarminSubmitting(false);
    }
  };

  const handleBulkImportGarmin = async () => {
    try {
      setStatusMsg('Bulk importing Garmin activities to heat...');
      const res = await bulkImportGarmin(true);
      setStatusMsg(res.message || `Bulk imported ${res.activities_imported} activities to heat.`);
      setTimeout(() => setStatusMsg(null), 5000);
      await loadConnectors();
    } catch (err: any) {
      alert(`Garmin bulk import failed: ${err.message}`);
    }
  };

  const handleConnectTrailforks = async (e: React.FormEvent) => {
    e.preventDefault();
    setTfSubmitting(true);
    try {
      const res = await connectTrailforks({
        username: tfUsername.trim() || undefined,
        token: tfToken.trim() || undefined
      });
      setShowTrailforksModal(false);
      setTfUsername('');
      setTfToken('');
      setStatusMsg(res.message || 'Trailforks connected! Trail reports active (© Trailforks).');
      setTimeout(() => setStatusMsg(null), 5000);
      await loadConnectors();
    } catch (err: any) {
      alert(`Trailforks connection failed: ${err.message}`);
    } finally {
      setTfSubmitting(false);
    }
  };

  const handleConnectStrava = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!stravaToken.trim()) return;

    setStravaSubmitting(true);
    setStravaError(null);
    try {
      const res = await connectStrava({ personal_token: stravaToken.trim() });
      setShowStravaModal(false);
      setStravaToken('');
      setStatusMsg(res.message || 'Strava personal API token connected! Encrypted at rest.');
      setTimeout(() => setStatusMsg(null), 4000);
      await loadConnectors();
    } catch (err: any) {
      setStravaError(err.message || 'Strava personal token authorization failed');
    } finally {
      setStravaSubmitting(false);
    }
  };

  const handleSync = async (provider: string) => {
    try {
      const res = await syncConnector(provider, true);
      setStatusMsg(res.message || `Synced ${provider}: ${res.activities_imported || 0} activities imported.`);
      setTimeout(() => setStatusMsg(null), 4000);
      await loadConnectors();
    } catch (err: any) {
      alert(`Sync failed: ${err.message}`);
    }
  };

  const handleDisconnect = async (provider: string) => {
    const confirm = window.confirm(`Disconnect ${provider} and remove stored session tokens?`);
    if (!confirm) return;

    try {
      await disconnectConnector(provider);
      setStatusMsg(`${provider} disconnected.`);
      setTimeout(() => setStatusMsg(null), 3000);
      await loadConnectors();
    } catch (err: any) {
      alert(`Disconnect failed: ${err.message}`);
    }
  };

  return (
    <div style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', margin: 0 }}>
          Connected Services (Connectors)
        </h3>
        <p style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)', margin: '4px 0 0 0' }}>
          Connect Garmin Connect and Trailforks to sync activities into your private heat layer and view condition reports. Passwords are never stored; tokens are AES-encrypted at rest.
        </p>
      </div>

      {statusMsg && (
        <div style={{ fontSize: 12, color: 'var(--color-text-primary, #1D3B34)', backgroundColor: 'var(--color-bg-subtle, #D1FAE5)', border: '1px solid var(--color-divider)', padding: '6px 10px', borderRadius: 4 }}>
          {statusMsg}
        </div>
      )}

      {loading && connectors.length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>Loading connectors...</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {connectors.map((c) => (
            <div
              key={c.name}
              style={{
                backgroundColor: 'var(--color-bg-subtle, #F8F9FA)',
                borderRadius: 6,
                border: '1px solid var(--color-divider, #E0E0E0)',
                padding: '10px 12px',
                display: 'flex',
                flexDirection: 'column',
                gap: 6
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <strong style={{ fontSize: 13, color: 'var(--color-text-primary, #1D3B34)' }}>{c.display_name}</strong>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      padding: '1px 5px',
                      borderRadius: 3,
                      backgroundColor: c.enabled 
                        ? (isDarkMode ? '#163826' : '#E8F5E9') 
                        : (isDarkMode ? '#243431' : '#ECEFF1'),
                      color: c.enabled 
                        ? (isDarkMode ? '#86EFAC' : '#2E6F40') 
                        : (isDarkMode ? '#94A3B8' : '#78909C')
                    }}
                  >
                    {c.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                  {c.connected && (
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        padding: '1px 5px',
                        borderRadius: 3,
                        backgroundColor: isDarkMode ? '#1E3A4C' : '#E0F2FE',
                        color: isDarkMode ? '#7DD3FC' : '#0369A1'
                      }}
                    >
                      ✓ Connected
                    </span>
                  )}
                </div>

                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {c.enabled && c.connected && (
                    <>
                      {c.name === 'garmin' && (
                        <button
                          type="button"
                          onClick={handleBulkImportGarmin}
                          className="btn-primary"
                          style={{ fontSize: 11, padding: '2px 8px', minHeight: 26 }}
                          title="Bulk import all activities to heat"
                        >
                          Bulk Import Heat
                        </button>
                      )}
                      {c.name === 'cubetrek' && (
                        <button
                          type="button"
                          onClick={() => setShowCubeTrekModal(true)}
                          className="btn-primary"
                          style={{ fontSize: 11, padding: '2px 8px', minHeight: 26 }}
                          title="Import 3D track from CubeTrek URL"
                        >
                          Import Track
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handleSync(c.name)}
                        className="btn-outline"
                        style={{ fontSize: 11, padding: '2px 8px', minHeight: 26 }}
                      >
                        Sync Now
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDisconnect(c.name)}
                        className="btn-outline"
                        style={{ fontSize: 11, padding: '2px 8px', minHeight: 26, color: 'var(--color-blaze, #FF5B14)', borderColor: 'var(--color-divider)' }}
                      >
                        Disconnect
                      </button>
                    </>
                  )}
                  {c.enabled && !c.connected && (
                    <button
                      type="button"
                      onClick={() => {
                        if (c.name === 'garmin') setShowGarminModal(true);
                        else if (c.name === 'trailforks') setShowTrailforksModal(true);
                        else if (c.name === 'strava') setShowStravaModal(true);
                        else if (c.name === 'cubetrek') setShowCubeTrekModal(true);
                        else alert(`${c.display_name} connector interface ready.`);
                      }}
                      className="btn-secondary"
                      style={{ fontSize: 11, padding: '2px 10px', minHeight: 26 }}
                    >
                      {c.name === 'cubetrek' ? 'Import / Connect' : 'Connect'}
                    </button>
                  )}
                </div>
              </div>

              <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)' }}>
                {c.description}
                {c.connected && c.last_synced_at && (
                  <span> • Last synced: {new Date(c.last_synced_at).toLocaleDateString()}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Garmin Connect Modal */}
      {showGarminModal && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: 16
          }}
          onClick={() => {
            setShowGarminModal(false);
            setGarminNeedsMfa(false);
            setGarminError(null);
          }}
        >
          <div
            style={{
              backgroundColor: 'var(--color-card-bg, #FFFFFF)',
              color: 'var(--color-text-primary, #1D3B34)',
              borderRadius: 10,
              maxWidth: 420,
              width: '100%',
              padding: 20,
              boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
              border: '1px solid var(--color-divider, #D1D8D8)'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', margin: 0 }}>
                {garminNeedsMfa ? 'Garmin Two-Factor Authentication' : 'Connect Garmin Account'}
              </h3>
              <button
                type="button"
                onClick={() => {
                  setShowGarminModal(false);
                  setGarminNeedsMfa(false);
                  setGarminError(null);
                }}
                style={{ border: 'none', background: 'transparent', fontSize: 18, cursor: 'pointer', color: 'var(--color-text-secondary, #888)' }}
              >
                ✕
              </button>
            </div>

            {garminError && (
              <div style={{ backgroundColor: '#FEE2E2', color: '#B91C1C', border: '1px solid #FCA5A5', padding: '8px 10px', borderRadius: 6, fontSize: 12 }}>
                <strong>Authentication Notice:</strong> {garminError}
              </div>
            )}

            {garminNeedsMfa ? (
              <form onSubmit={handleVerifyGarminMfa} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div style={{ backgroundColor: 'var(--color-bg-subtle, #F0FDF4)', border: '1px solid #BBF7D0', borderRadius: 6, padding: 10, fontSize: 12, color: '#166534' }}>
                  <strong>Security Verification:</strong> {garminMfaMessage}
                </div>

                <div>
                  <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 4 }}>
                    6-Digit Security Code
                  </label>
                  <input
                    type="text"
                    value={garminMfaCode}
                    onChange={(e) => setGarminMfaCode(e.target.value)}
                    placeholder="e.g. 123456"
                    maxLength={10}
                    autoFocus
                    required
                    style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 16, letterSpacing: '2px', fontWeight: 700, textAlign: 'center', boxSizing: 'border-box' }}
                  />
                </div>

                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
                  <button
                    type="button"
                    onClick={() => {
                      setGarminNeedsMfa(false);
                      setGarminError(null);
                    }}
                    className="btn-outline"
                    style={{ fontSize: 12, minHeight: 32, padding: '4px 10px' }}
                  >
                    Back to Login
                  </button>
                  <button
                    type="submit"
                    disabled={garminSubmitting}
                    className="btn-primary"
                    style={{ fontSize: 12, minHeight: 32, padding: '4px 16px' }}
                  >
                    {garminSubmitting ? 'Verifying...' : 'Verify & Connect'}
                  </button>
                </div>
              </form>
            ) : (
              <form onSubmit={handleConnectGarmin} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ backgroundColor: 'var(--color-bg-subtle, #F0F9FF)', border: '1px solid var(--color-divider, #BAE6FD)', borderRadius: 6, padding: 8, fontSize: 11, color: 'var(--color-text-secondary, #0369A1)' }}>
                  <strong>Zero Password Retention Guarantee:</strong> Passwords are never stored anywhere. Your session token is AES-256 encrypted at rest. Supports 2FA/MFA.
                </div>

                <div>
                  <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 3 }}>
                    Garmin Username / Email
                  </label>
                  <input
                    type="text"
                    value={garminUser}
                    onChange={(e) => setGarminUser(e.target.value)}
                    placeholder="user@garmin.com"
                    style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13, boxSizing: 'border-box' }}
                    required
                  />
                </div>

                <div>
                  <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 3 }}>
                    Garmin Password
                  </label>
                  <input
                    type="password"
                    value={garminPass}
                    onChange={(e) => setGarminPass(e.target.value)}
                    placeholder="••••••••••••"
                    style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13, boxSizing: 'border-box' }}
                    required
                  />
                </div>

                {/* Bulk import agreement checkbox */}
                <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, cursor: 'pointer', fontSize: 12, color: 'var(--color-text-primary, #1D3B34)', marginTop: 4 }}>
                  <input
                    type="checkbox"
                    checked={garminImportHeat}
                    onChange={(e) => setGarminImportHeat(e.target.checked)}
                    style={{ accentColor: 'var(--color-blaze, #FF5B14)', marginTop: 2 }}
                  />
                  <span>
                    <strong>Bulk import all activities to heat layer</strong> (anonymized; first/last 0.2 mi and privacy zones strictly trimmed).
                  </span>
                </label>

                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 6 }}>
                  <button
                    type="button"
                    onClick={() => {
                      setShowGarminModal(false);
                      setGarminError(null);
                    }}
                    className="btn-outline"
                    style={{ fontSize: 12, minHeight: 32, padding: '4px 10px' }}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={garminSubmitting}
                    className="btn-primary"
                    style={{ fontSize: 12, minHeight: 32, padding: '4px 14px' }}
                  >
                    {garminSubmitting ? 'Authenticating...' : 'Connect & Import'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* Trailforks Connect Modal */}
      {showTrailforksModal && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: 16
          }}
          onClick={() => setShowTrailforksModal(false)}
        >
          <div
            style={{
              backgroundColor: 'var(--color-card-bg, #FFFFFF)',
              color: 'var(--color-text-primary, #1D3B34)',
              borderRadius: 10,
              maxWidth: 420,
              width: '100%',
              padding: 20,
              boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
              border: '1px solid var(--color-divider, #D1D8D8)'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', margin: 0 }}>
                Connect Trailforks
              </h3>
              <button
                type="button"
                onClick={() => setShowTrailforksModal(false)}
                style={{ border: 'none', background: 'transparent', fontSize: 18, cursor: 'pointer', color: 'var(--color-text-secondary, #888)' }}
              >
                ✕
              </button>
            </div>

            <div style={{ backgroundColor: 'var(--color-bg-subtle, #F0F9FF)', border: '1px solid var(--color-divider, #BAE6FD)', borderRadius: 6, padding: 8, fontSize: 11, color: 'var(--color-text-secondary, #0369A1)' }}>
              <strong>Attribution Notice:</strong> Trail condition reports and difficulty metadata are credited to <strong>&copy; Trailforks</strong>. We respect rate limits and proprietary data policies.
            </div>

            <form onSubmit={handleConnectTrailforks} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 3 }}>
                  Trailforks Username / Account ID
                </label>
                <input
                  type="text"
                  value={tfUsername}
                  onChange={(e) => setTfUsername(e.target.value)}
                  placeholder="e.g. nh_rider"
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13, boxSizing: 'border-box' }}
                />
              </div>

              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 3 }}>
                  API Token / Secret (Optional)
                </label>
                <input
                  type="password"
                  value={tfToken}
                  onChange={(e) => setTfToken(e.target.value)}
                  placeholder="Optional Trailforks API token"
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13, boxSizing: 'border-box' }}
                />
              </div>

              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 6 }}>
                <button
                  type="button"
                  onClick={() => setShowTrailforksModal(false)}
                  className="btn-outline"
                  style={{ fontSize: 12, minHeight: 32, padding: '4px 10px' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={tfSubmitting}
                  className="btn-primary"
                  style={{ fontSize: 12, minHeight: 32, padding: '4px 14px' }}
                >
                  {tfSubmitting ? 'Connecting...' : 'Connect Trailforks'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Strava Connect Modal (Personal API Token) */}
      {showStravaModal && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: 16
          }}
          onClick={() => {
            setShowStravaModal(false);
            setStravaError(null);
          }}
        >
          <div
            style={{
              backgroundColor: 'var(--color-card-bg, #FFFFFF)',
              color: 'var(--color-text-primary, #1D3B34)',
              borderRadius: 10,
              maxWidth: 440,
              width: '100%',
              padding: 20,
              boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
              border: '1px solid var(--color-divider, #D1D8D8)'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', margin: 0 }}>
                Connect Strava (Personal API Token)
              </h3>
              <button
                type="button"
                onClick={() => {
                  setShowStravaModal(false);
                  setStravaError(null);
                }}
                style={{ border: 'none', background: 'transparent', fontSize: 18, cursor: 'pointer', color: 'var(--color-text-secondary, #888)' }}
              >
                ✕
              </button>
            </div>

            <div style={{ backgroundColor: 'var(--color-bg-subtle, #F0F9FF)', border: '1px solid var(--color-divider, #BAE6FD)', borderRadius: 6, padding: 10, fontSize: 12, color: 'var(--color-text-secondary, #0369A1)', lineHeight: 1.4 }}>
              <strong>Zero App Secret Architecture:</strong> Loam does not require an app-wide Strava client. You can generate a free personal API token on Strava to sync your rides and runs directly.
            </div>

            <div style={{ backgroundColor: 'var(--color-bg-subtle, #F8F9FA)', border: '1px solid var(--color-divider, #E5E7EB)', borderRadius: 6, padding: 10, fontSize: 11, color: 'var(--color-text-secondary, #4B5563)', lineHeight: 1.5 }}>
              <strong>How to get your Personal Access Token:</strong>
              <ol style={{ margin: '4px 0 0 0', paddingLeft: 18 }}>
                <li>Log in to <a href="https://www.strava.com/settings/api" target="_blank" rel="noopener noreferrer" style={{ color: '#FF5B14', fontWeight: 600 }}>strava.com/settings/api</a>.</li>
                <li>Under <em>My API Application</em>, copy <strong>Your Access Token</strong>.</li>
                <li>Paste it below. Your token is encrypted at rest using AES-256.</li>
              </ol>
            </div>

            {stravaError && (
              <div style={{ backgroundColor: '#FEE2E2', color: '#B91C1C', border: '1px solid #FCA5A5', padding: '8px 10px', borderRadius: 6, fontSize: 12 }}>
                <strong>Authorization Notice:</strong> {stravaError}
              </div>
            )}

            <form onSubmit={handleConnectStrava} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 4 }}>
                  Personal Access Token
                </label>
                <input
                  type="password"
                  value={stravaToken}
                  onChange={(e) => setStravaToken(e.target.value)}
                  placeholder="Paste your Strava personal access token"
                  style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13, boxSizing: 'border-box' }}
                  required
                />
              </div>

              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
                <button
                  type="button"
                  onClick={() => {
                    setShowStravaModal(false);
                    setStravaError(null);
                  }}
                  className="btn-outline"
                  style={{ fontSize: 12, minHeight: 32, padding: '4px 10px' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={stravaSubmitting}
                  className="btn-primary"
                  style={{ fontSize: 12, minHeight: 32, padding: '4px 14px' }}
                >
                  {stravaSubmitting ? 'Verifying Token...' : 'Connect Personal Token'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* CubeTrek Modal */}
      {showCubeTrekModal && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: 16
          }}
          onClick={() => {
            setShowCubeTrekModal(false);
            setCubetrekError(null);
            setCubetrekResult(null);
          }}
        >
          <div
            style={{
              backgroundColor: 'var(--color-card-bg, #FFFFFF)',
              color: 'var(--color-text-primary, #1D3B34)',
              borderRadius: 10,
              maxWidth: 450,
              width: '100%',
              padding: 20,
              boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
              border: '1px solid var(--color-divider, #D1D8D8)'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', margin: 0 }}>
                Import CubeTrek GPS Track
              </h3>
              <button
                type="button"
                onClick={() => {
                  setShowCubeTrekModal(false);
                  setCubetrekError(null);
                  setCubetrekResult(null);
                }}
                style={{ border: 'none', background: 'transparent', fontSize: 18, cursor: 'pointer', color: 'var(--color-text-secondary, #888)' }}
              >
                ✕
              </button>
            </div>

            <div style={{ backgroundColor: 'var(--color-bg-subtle, #F0FDF4)', border: '1px solid var(--color-divider, #BBF7D0)', borderRadius: 6, padding: 10, fontSize: 12, color: 'var(--color-text-secondary, #166534)', lineHeight: 1.4 }}>
              <strong>CubeTrek 3D Track Visualizer:</strong> Paste any public CubeTrek share URL or activity ID (e.g. <code>https://cubetrek.com/view?id=83724</code>). Loam will extract the GPS trackpoints, apply your privacy zones, map-match to OSM trail edges, and enrich community heat.
            </div>

            {cubetrekResult && (
              <div style={{ backgroundColor: '#DCFCE7', color: '#166534', border: '1px solid #86EFAC', padding: '10px 12px', borderRadius: 6, fontSize: 12 }}>
                <strong>✓ Import Successful:</strong> {cubetrekResult.message}
                <div style={{ marginTop: 4, fontSize: 11 }}>
                  Distance: {cubetrekResult.distance_miles} mi • Matched {cubetrekResult.matched_edges} edges
                </div>
              </div>
            )}

            {cubetrekError && (
              <div style={{ backgroundColor: '#FEE2E2', color: '#B91C1C', border: '1px solid #FCA5A5', padding: '8px 10px', borderRadius: 6, fontSize: 12 }}>
                <strong>Error:</strong> {cubetrekError}
              </div>
            )}

            <form onSubmit={handleImportCubeTrek} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 4 }}>
                  CubeTrek Share URL or Track ID *
                </label>
                <input
                  type="text"
                  value={cubetrekUrl}
                  onChange={(e) => setCubetrekUrl(e.target.value)}
                  placeholder="https://cubetrek.com/view?id=83724 or 83724"
                  style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13, boxSizing: 'border-box' }}
                  required
                />
              </div>

              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 4 }}>
                  Activity Name (Optional)
                </label>
                <input
                  type="text"
                  value={cubetrekName}
                  onChange={(e) => setCubetrekName(e.target.value)}
                  placeholder="e.g. Bear Brook Ridge Loop"
                  style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13, boxSizing: 'border-box' }}
                />
              </div>

              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 4 }}>
                  Sport Profile
                </label>
                <select
                  value={cubetrekSport}
                  onChange={(e) => setCubetrekSport(e.target.value)}
                  style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13 }}
                >
                  <option value="mtb">Mountain Biking (MTB)</option>
                  <option value="trail_run">Trail Running</option>
                  <option value="gravel">Gravel Cycling</option>
                  <option value="foot">Hiking / Foot</option>
                </select>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                <input
                  type="checkbox"
                  id="cubetrek-heat-check"
                  checked={cubetrekImportHeat}
                  onChange={(e) => setCubetrekImportHeat(e.target.checked)}
                />
                <label htmlFor="cubetrek-heat-check" style={{ fontSize: 12, color: 'var(--color-text-primary, #1D3B34)', cursor: 'pointer' }}>
                  Contribute ridden trail edges to community heat layer (with privacy zones applied)
                </label>
              </div>

              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 6 }}>
                <button
                  type="button"
                  onClick={() => {
                    setShowCubeTrekModal(false);
                    setCubetrekError(null);
                    setCubetrekResult(null);
                  }}
                  className="btn-outline"
                  style={{ fontSize: 12, minHeight: 32, padding: '4px 10px' }}
                >
                  Close
                </button>
                <button
                  type="submit"
                  disabled={cubetrekSubmitting}
                  className="btn-primary"
                  style={{ fontSize: 12, minHeight: 32, padding: '4px 14px' }}
                >
                  {cubetrekSubmitting ? 'Importing Track...' : 'Import Track'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default YouPanel;
