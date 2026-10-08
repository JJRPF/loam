import React, { useState } from 'react';
import { uploadActivityFile } from '../services/api';

export const YouPanel: React.FC = () => {

  const [isSignedIn, setIsSignedIn] = useState(true);
  const [user, setUser] = useState({
    name: 'Justin Pfister',
    email: 'justin@example.com',
    device: 'Garmin fenix 7 Pro'
  });
  const [privacyZoneEnabled, setPrivacyZoneEnabled] = useState(true);

  const handleSignInGoogle = () => {
    // Firebase Google Sign-In skeleton
    setIsSignedIn(true);
    setUser({
      name: 'Justin Pfister',
      email: 'justin@example.com',
      device: 'Garmin fenix 7 Pro'
    });
  };

  const handleSignOut = () => {
    setIsSignedIn(false);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '4px 0 24px 0' }}>
      <h2 style={{ fontSize: 16, fontWeight: 700, color: '#1D3B34' }}>Profile & Settings</h2>

      {/* Auth Card */}
      <div style={{ backgroundColor: '#FFFFFF', borderRadius: 8, border: '1px solid #D1D8D8', padding: 14 }}>
        {isSignedIn ? (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
              <div
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: '50%',
                  backgroundColor: '#1D3B34',
                  color: '#FFFFFF',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 18,
                  fontWeight: 700
                }}
              >
                JP
              </div>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: '#1D3B34' }}>{user.name}</div>
                <div style={{ fontSize: 13, color: '#42675E' }}>{user.email}</div>
              </div>
            </div>

            <div style={{ fontSize: 13, color: '#1D3B34', backgroundColor: '#F3F7F7', padding: '8px 10px', borderRadius: 6, marginBottom: 12 }}>
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
            <p style={{ fontSize: 14, color: '#1D3B34', marginBottom: 12 }}>
              Sign in with Google to sync routes across devices and export to Garmin Connect.
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
      <div style={{ backgroundColor: '#FFFFFF', borderRadius: 8, border: '1px solid #D1D8D8', padding: 14 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, color: '#1D3B34', marginBottom: 6 }}>
          Upload Ride / Run (Heat Ingestion)
        </h3>
        <p style={{ fontSize: 12, color: '#42675E', marginBottom: 12 }}>
          Ingest your GPX or Garmin FIT files into Loam's recency heat layer. Starts & ends are automatically trimmed by 0.2 mi.
        </p>

        <ActivityUploadWidget />
      </div>

      {/* Settings & Privacy */}
      <div style={{ backgroundColor: '#FFFFFF', borderRadius: 8, border: '1px solid #D1D8D8', padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, color: '#1D3B34' }}>Preferences & Privacy</h3>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13 }}>
          <div>
            <strong>Distance & Elevation Units</strong>
            <div style={{ fontSize: 12, color: '#42675E' }}>Miles & Feet (Fixed policy)</div>
          </div>
          <span style={{ fontWeight: 700, color: '#1D3B34' }}>Imperial (mi / ft)</span>
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
          <strong>DNR (Do Not Ride) Trail List</strong>
          <div style={{ fontSize: 12, color: '#42675E', marginTop: 2 }}>
            Manage private or overgrown trails you wish the router to strictly avoid.
          </div>
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

