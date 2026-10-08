import React, { useState, useEffect } from 'react';
import { 
  uploadActivityFile, listUserDNR, createUserDNR, deleteUserDNR,
  exportMyData, deleteMyAccount,
  getConnectors, connectGarmin, connectStrava, syncConnector, disconnectConnector
} from '../services/api';
import { getStoredUser, mockGoogleLogin, logoutUser } from '../services/auth';
import type { UserDNR, ConnectorStatus, AuthUser } from '../types';

interface YouPanelProps {
  isDarkMode?: boolean;
  onToggleDarkMode?: () => void;
}

export const YouPanel: React.FC<YouPanelProps> = ({ isDarkMode = false, onToggleDarkMode }) => {
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(() => getStoredUser());
  const isSignedIn = !!currentUser;
  const user = {
    name: currentUser?.displayName || 'Justin Pfister',
    email: currentUser?.email || 'justin@example.com',
    device: 'Garmin fenix 7 Pro'
  };
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
      const items = await listUserDNR('justin_default_user');
      setDnrList(items);
    } catch (e) {
      console.error('Failed to load DNR', e);
    }
  };

  useEffect(() => {
    let ignore = false;
    listUserDNR('justin_default_user')
      .then((items) => {
        if (!ignore) setDnrList(items);
      })
      .catch((e) => console.error('Failed to load DNR', e));
    return () => {
      ignore = true;
    };
  }, []);

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
      const data = await exportMyData('justin_default_user');
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
      await deleteMyAccount('justin_default_user');
      logoutUser();
      setCurrentUser(null);
      alert('Account and all personal data permanently deleted.');
    } catch (e: any) {
      alert(`Deletion failed: ${e.message}`);
    }
  };

  const handleSignInGoogle = async () => {
    try {
      const authUser = await mockGoogleLogin('justin@example.com', 'Justin Pfister');
      setCurrentUser(authUser);
    } catch (e: any) {
      alert(`Google Sign-In failed: ${e.message}`);
    }
  };

  const handleSignOut = () => {
    logoutUser();
    setCurrentUser(null);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '4px 0 24px 0' }}>
      <h2 style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>Profile & Settings</h2>

      {/* Auth Card */}
      <div style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', padding: 14 }}>
        {isSignedIn ? (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
              <div
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: '50%',
                  backgroundColor: 'var(--color-header-bg, #1D3B34)',
                  color: '#FFFFFF',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 18,
                  fontWeight: 700
                }}
              >
                {user.name.split(' ').map(n => n[0]).join('').slice(0, 2) || 'JP'}
              </div>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>{user.name}</div>
                <div style={{ fontSize: 13, color: 'var(--color-text-secondary, #42675E)' }}>{user.email}</div>
              </div>
            </div>

            <div style={{ fontSize: 13, color: 'var(--color-text-primary, #1D3B34)', backgroundColor: 'var(--color-bg-subtle, #F3F7F7)', padding: '8px 10px', borderRadius: 6, marginBottom: 12 }}>
              Connected Device: <strong>{user.device}</strong> (Garmin FIT & GPX enabled)
            </div>

            <button
              type="button"
              onClick={handleSignOut}
              className="btn-outline"
              style={{ width: '100%', fontSize: 13, minHeight: 36 }}
            >
              Sign Out
            </button>
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: '10px 0' }}>
            <p style={{ fontSize: 14, color: 'var(--color-text-primary, #1D3B34)', marginBottom: 12 }}>
              Sign in with Google to sync routes across devices, backup to PostgreSQL, and export to Garmin Connect.
            </p>
            <button
              type="button"
              onClick={handleSignInGoogle}
              className="btn-primary"
              style={{ width: '100%' }}
            >
              Sign In with Google
            </button>
          </div>
        )}
      </div>

      {/* Heat v1 Activity Upload Card */}
      <div style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', padding: 14 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', marginBottom: 6 }}>
          Upload Ride / Run (Heat Ingestion)
        </h3>
        <p style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)', marginBottom: 12 }}>
          Ingest your GPX or Garmin FIT files into Loam's recency heat layer. Starts & ends are automatically trimmed by 0.2 mi.
        </p>

        <ActivityUploadWidget />
      </div>

      {/* Connected Services (Stage 6) */}
      <ConnectedServicesSection />

      {/* Settings & Privacy */}
      <div style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>Preferences & Privacy</h3>

        {/* Display Theme Toggle */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13 }}>
          <div>
            <strong>Display Theme</strong>
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>Section 18 tokens (Fog / Spruce)</div>
          </div>
          <button
            type="button"
            onClick={onToggleDarkMode}
            className="btn-secondary"
            style={{ fontSize: 12, padding: '4px 10px', minHeight: 32 }}
          >
            {isDarkMode ? '🌙 Dark Mode' : '☀️ Light Mode'}
          </button>
        </div>

        <div style={{ borderTop: '1px solid var(--color-divider, #E7ECEC)', paddingTop: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13 }}>
          <div>
            <strong>Distance & Elevation Units</strong>
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>Miles & Feet (Fixed policy)</div>
          </div>
          <span style={{ fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>Imperial (mi / ft)</span>
        </div>

        <div style={{ borderTop: '1px solid #E7ECEC', paddingTop: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13 }}>
          <div>
            <strong>Endpoint Trimming Protection</strong>
            <div style={{ fontSize: 12, color: '#42675E' }}>Automatically strip first & last 0.2 mi of ride uploads</div>
          </div>
          <input
            type="checkbox"
            checked={privacyZoneEnabled}
            onChange={(e) => setPrivacyZoneEnabled(e.target.checked)}
            style={{ width: 18, height: 18, accentColor: '#FF5B14' }}
          />
        </div>

        <div style={{ borderTop: '1px solid #E7ECEC', paddingTop: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13 }}>
          <div>
            <strong>Privacy Threshold Invariant</strong>
            <div style={{ fontSize: 12, color: '#42675E' }}>Public routes only influenced when ≥ 3 unique riders contribute</div>
          </div>
          <span style={{ fontSize: 12, fontWeight: 700, color: '#1D3B34' }}>≥ 3 Riders</span>
        </div>

        <div style={{ borderTop: '1px solid #E7ECEC', paddingTop: 10, fontSize: 13 }}>
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
          <div style={{ fontSize: 12, color: '#42675E', marginTop: 2, marginBottom: 8 }}>
            Manage private or overgrown trails you wish the router to strictly avoid.
          </div>

          {showAddDnr && (
            <div style={{ backgroundColor: '#F3F7F7', border: '1px solid #D1D8D8', borderRadius: 6, padding: 10, marginBottom: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#1D3B34' }}>Add Do-Not-Ride Rule</div>
              <input
                type="text"
                placeholder="Name / Label (e.g. Overgrown Logging Rd)"
                value={newDnrName}
                onChange={(e) => setNewDnrName(e.target.value)}
                style={{ padding: '6px 8px', borderRadius: 4, border: '1px solid #D1D8D8', fontSize: 13 }}
              />
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12 }}>
                <label>
                  Type:{' '}
                  <select
                    value={newDnrType}
                    onChange={(e) => setNewDnrType(e.target.value as any)}
                    style={{ padding: '4px 6px', borderRadius: 4, border: '1px solid #D1D8D8' }}
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
                    style={{ flex: 1, padding: '4px 6px', borderRadius: 4, border: '1px solid #D1D8D8', fontSize: 12 }}
                  />
                )}
              </div>
              <input
                type="text"
                placeholder="Reason (e.g. Private signs, active logging, blowdowns)"
                value={newDnrReason}
                onChange={(e) => setNewDnrReason(e.target.value)}
                style={{ padding: '6px 8px', borderRadius: 4, border: '1px solid #D1D8D8', fontSize: 13 }}
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
            <div style={{ fontSize: 12, color: '#6A7D78', fontStyle: 'italic', padding: '6px 0' }}>
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
                    backgroundColor: '#F8F9FA',
                    borderRadius: 6,
                    border: '1px solid #E0E0E0',
                    fontSize: 12
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, color: '#1D3B34' }}>
                      {item.name}
                      <span style={{ fontSize: 10, marginLeft: 6, padding: '1px 5px', borderRadius: 3, backgroundColor: item.is_soft ? '#FFF3E0' : '#FFEBEE', color: item.is_soft ? '#E65100' : '#C62828', fontWeight: 700 }}>
                        {item.is_soft ? 'Soft DNR' : 'Hard DNR'}
                      </span>
                    </div>
                    {item.reason && <div style={{ fontSize: 11, color: '#42675E' }}>{item.reason}</div>}
                    {item.edge_osm_id && <div style={{ fontSize: 10, color: '#888' }}>OSM ID: {item.edge_osm_id}</div>}
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDeleteDnr(item.id)}
                    style={{
                      border: 'none',
                      backgroundColor: 'transparent',
                      color: '#C62828',
                      fontSize: 12,
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
      <div style={{ backgroundColor: '#FFFFFF', borderRadius: 8, border: '1px solid #D1D8D8', padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, color: '#1D3B34', margin: 0 }}>
          Data Rights & Privacy Compliance
        </h3>
        <p style={{ fontSize: 12, color: '#42675E', margin: 0 }}>
          You have complete ownership of your data under Loam's privacy guarantees. Raw GPS tracks are discarded after matching; personal rides are never exposed to other users.
        </p>

        {exportMessage && (
          <div style={{ fontSize: 12, color: '#2E6F40', backgroundColor: '#E8F5E9', padding: '6px 10px', borderRadius: 4 }}>
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
            style={{ flex: 1, fontSize: 12, minHeight: 34, color: '#C62828', borderColor: '#FFCDD2' }}
          >
            Delete Account & Rides
          </button>
        </div>
      </div>

      {/* About & Stack */}
      <div style={{ fontSize: 12, color: '#42675E', textAlign: 'center', lineHeight: 1.5 }}>
        Loam Trail Route Builder • Stage 4 Heat v1<br />
        Built with MapLibre GL JS, GraphHopper & PostGIS
      </div>
    </div>
  );
};

const ActivityUploadWidget: React.FC = () => {
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
      const res = await uploadActivityFile(file, sport, consent, false, 'justin_default_user');
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
        style={{ fontSize: 13 }}
      />

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', fontSize: 13 }}>
        <label>
          Sport:{' '}
          <select
            value={sport}
            onChange={(e) => setSport(e.target.value)}
            style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #D1D8D8' }}
          >
            <option value="mtb">MTB</option>
            <option value="trail_run">Trail Run</option>
            <option value="mtb_gravel">Gravel</option>
          </select>
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            style={{ accentColor: '#FF5B14' }}
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
        <div style={{ backgroundColor: '#F3F7F7', border: '1px solid #B0C4DE', borderRadius: 6, padding: 10, fontSize: 12 }}>
          <div style={{ fontWeight: 700, color: '#1D3B34' }}>Upload & Map-Match Complete</div>
          <div>Distance: {result.distance_miles} mi • Matched edges: {result.matched_edges_count}</div>
          {result.message && <div style={{ color: '#8B4513', marginTop: 4 }}>{result.message}</div>}
        </div>
      )}

      {error && (
        <div style={{ backgroundColor: '#FFF0F0', border: '1px solid #FFCCCC', borderRadius: 6, padding: 10, fontSize: 12, color: '#D32F2F' }}>
          {error}
        </div>
      )}
    </div>
  );
};

const ConnectedServicesSection: React.FC = () => {
  const [connectors, setConnectors] = useState<ConnectorStatus[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  // Garmin connect form state
  const [showGarminModal, setShowGarminModal] = useState(false);
  const [garminUser, setGarminUser] = useState('');
  const [garminPass, setGarminPass] = useState('');
  const [garminSubmitting, setGarminSubmitting] = useState(false);

  // Strava connect form state
  const [showStravaModal, setShowStravaModal] = useState(false);
  const [stravaCode, setStravaCode] = useState('');
  const [stravaSubmitting, setStravaSubmitting] = useState(false);

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
    loadConnectors();
  }, []);

  const handleConnectGarmin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!garminUser.trim() || !garminPass.trim()) return;

    setGarminSubmitting(true);
    try {
      await connectGarmin({ username: garminUser.trim(), password: garminPass.trim() });
      setShowGarminModal(false);
      setGarminUser('');
      setGarminPass('');
      setStatusMsg('Garmin session connected successfully! Tokens stored AES-encrypted at rest.');
      setTimeout(() => setStatusMsg(null), 4000);
      await loadConnectors();
    } catch (err: any) {
      alert(`Garmin connection failed: ${err.message}`);
    } finally {
      setGarminSubmitting(false);
    }
  };

  const handleConnectStrava = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!stravaCode.trim()) return;

    setStravaSubmitting(true);
    try {
      await connectStrava(stravaCode.trim());
      setShowStravaModal(false);
      setStravaCode('');
      setStatusMsg('Strava account authorized successfully!');
      setTimeout(() => setStatusMsg(null), 4000);
      await loadConnectors();
    } catch (err: any) {
      alert(`Strava authorization failed: ${err.message}`);
    } finally {
      setStravaSubmitting(false);
    }
  };

  const handleSync = async (provider: string) => {
    try {
      const res = await syncConnector(provider);
      setStatusMsg(`Synced ${provider}: ${res.activities_imported || 0} activities imported.`);
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
    <div style={{ backgroundColor: '#FFFFFF', borderRadius: 8, border: '1px solid #D1D8D8', padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <h3 style={{ fontSize: 14, fontWeight: 700, color: '#1D3B34', margin: 0 }}>
          Connected Services (Connectors)
        </h3>
        <p style={{ fontSize: 12, color: '#42675E', margin: '4px 0 0 0' }}>
          Connect third-party platforms to automatically sync activities into your private heat layer.
          Connectors are disabled by default. Passwords are never stored; session tokens are AES-encrypted at rest.
        </p>
      </div>

      {statusMsg && (
        <div style={{ fontSize: 12, color: '#065F46', backgroundColor: '#D1FAE5', padding: '6px 10px', borderRadius: 4 }}>
          {statusMsg}
        </div>
      )}

      {loading && connectors.length === 0 ? (
        <div style={{ fontSize: 12, color: '#42675E' }}>Loading connectors...</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {connectors.map((c) => (
            <div
              key={c.name}
              style={{
                backgroundColor: '#F8F9FA',
                borderRadius: 6,
                border: '1px solid #E0E0E0',
                padding: '10px 12px',
                display: 'flex',
                flexDirection: 'column',
                gap: 6
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <strong style={{ fontSize: 13, color: '#1D3B34' }}>{c.display_name}</strong>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      padding: '1px 5px',
                      borderRadius: 3,
                      backgroundColor: c.enabled ? '#E8F5E9' : '#ECEFF1',
                      color: c.enabled ? '#2E6F40' : '#78909C'
                    }}
                  >
                    {c.enabled ? 'Enabled' : 'Disabled (off by default)'}
                  </span>
                  {c.connected && (
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        padding: '1px 5px',
                        borderRadius: 3,
                        backgroundColor: '#E0F2FE',
                        color: '#0369A1'
                      }}
                    >
                      ✓ Connected
                    </span>
                  )}
                </div>

                <div style={{ display: 'flex', gap: 6 }}>
                  {c.enabled && c.connected && (
                    <>
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
                        style={{ fontSize: 11, padding: '2px 8px', minHeight: 26, color: '#C62828', borderColor: '#FFCDD2' }}
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
                        else if (c.name === 'strava') setShowStravaModal(true);
                        else alert(`${c.display_name} connector interface ready.`);
                      }}
                      className="btn-secondary"
                      style={{ fontSize: 11, padding: '2px 10px', minHeight: 26 }}
                    >
                      Connect
                    </button>
                  )}
                </div>
              </div>

              <div style={{ fontSize: 11, color: '#42675E' }}>
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
            backgroundColor: 'rgba(0,0,0,0.45)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: 16
          }}
          onClick={() => setShowGarminModal(false)}
        >
          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: 10,
              maxWidth: 400,
              width: '100%',
              padding: 18,
              boxShadow: '0 8px 24px rgba(0,0,0,0.2)',
              display: 'flex',
              flexDirection: 'column',
              gap: 12
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: '#1D3B34', margin: 0 }}>Connect Garmin Account</h3>
              <button
                type="button"
                onClick={() => setShowGarminModal(false)}
                style={{ border: 'none', background: 'transparent', fontSize: 18, cursor: 'pointer', color: '#888' }}
              >
                ✕
              </button>
            </div>

            <div style={{ backgroundColor: '#F0F9FF', border: '1px solid #BAE6FD', borderRadius: 6, padding: 8, fontSize: 11, color: '#0369A1' }}>
              <strong>Zero Password Retention Guarantee:</strong> Your password is used solely in memory to authenticate a session token and is discarded immediately. The resulting session token is AES-256 encrypted at rest.
            </div>

            <form onSubmit={handleConnectGarmin} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: '#1D3B34', display: 'block', marginBottom: 3 }}>
                  Garmin Username / Email
                </label>
                <input
                  type="text"
                  value={garminUser}
                  onChange={(e) => setGarminUser(e.target.value)}
                  placeholder="user@garmin.com"
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid #D1D8D8', fontSize: 13, boxSizing: 'border-box' }}
                  required
                />
              </div>

              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: '#1D3B34', display: 'block', marginBottom: 3 }}>
                  Garmin Password
                </label>
                <input
                  type="password"
                  value={garminPass}
                  onChange={(e) => setGarminPass(e.target.value)}
                  placeholder="••••••••••••"
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid #D1D8D8', fontSize: 13, boxSizing: 'border-box' }}
                  required
                />
              </div>

              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
                <button
                  type="button"
                  onClick={() => setShowGarminModal(false)}
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
                  {garminSubmitting ? 'Authenticating...' : 'Connect Garmin'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Strava Connect Modal */}
      {showStravaModal && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.45)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: 16
          }}
          onClick={() => setShowStravaModal(false)}
        >
          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: 10,
              maxWidth: 400,
              width: '100%',
              padding: 18,
              boxShadow: '0 8px 24px rgba(0,0,0,0.2)',
              display: 'flex',
              flexDirection: 'column',
              gap: 12
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: '#1D3B34', margin: 0 }}>Authorize Strava</h3>
              <button
                type="button"
                onClick={() => setShowStravaModal(false)}
                style={{ border: 'none', background: 'transparent', fontSize: 18, cursor: 'pointer', color: '#888' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleConnectStrava} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: '#1D3B34', display: 'block', marginBottom: 3 }}>
                  Strava Authorization Code / Token
                </label>
                <input
                  type="text"
                  value={stravaCode}
                  onChange={(e) => setStravaCode(e.target.value)}
                  placeholder="e.g. strava_auth_code_xyz"
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid #D1D8D8', fontSize: 13, boxSizing: 'border-box' }}
                  required
                />
              </div>

              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
                <button
                  type="button"
                  onClick={() => setShowStravaModal(false)}
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
                  {stravaSubmitting ? 'Authorizing...' : 'Authorize Strava'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};


