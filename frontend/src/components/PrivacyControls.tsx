import React, { useEffect, useState } from 'react';
import {
  listPrivacyZones, createPrivacyZone, deletePrivacyZone, getContribution, setContribution, type PrivacyZone
} from '../services/api';

const RADII = [
  { label: '0.25 mi', m: 400 },
  { label: '0.5 mi', m: 800 },
  { label: '1 mi', m: 1609 }
];

/** Contribution consent and privacy zones: both change what the backend does with a rider's uploads. */
export const PrivacyControls: React.FC = () => {
  const [consent, setConsent] = useState<boolean | null>(null);
  const [zones, setZones] = useState<PrivacyZone[]>([]);
  const [radius, setRadius] = useState(800);
  const [name, setName] = useState('Home');
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    getContribution().then(setConsent).catch(() => setConsent(null));
    listPrivacyZones().then(setZones).catch(() => setZones([]));
  }, []);

  const toggleConsent = async (next: boolean) => {
    try {
      setConsent(await setContribution(next));
    } catch (e) {
      setStatus(e instanceof Error ? e.message : 'Could not save.');
    }
  };

  const addHere = () => {
    setStatus(null);
    if (!navigator.geolocation) {
      setStatus('This browser cannot share your location.');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const z = await createPrivacyZone({ name: name.trim() || 'Home', lat: pos.coords.latitude, lon: pos.coords.longitude, radius_m: radius });
          setZones((prev) => [...prev, z]);
        } catch (e) {
          setStatus(e instanceof Error ? e.message : 'Could not save the zone.');
        }
      },
      (err) => setStatus(`Location access failed: ${err.message}`),
      { enableHighAccuracy: true, timeout: 8000 }
    );
  };

  const remove = async (id: number) => {
    try {
      await deletePrivacyZone(id);
      setZones((prev) => prev.filter((z) => z.id !== id));
    } catch (e) {
      setStatus(e instanceof Error ? e.message : 'Could not delete the zone.');
    }
  };

  return (
    <div style={{ borderTop: '1px solid var(--color-divider, #E7ECEC)', paddingTop: 10, fontSize: 13, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input
          type="checkbox"
          checked={consent === true}
          disabled={consent === null}
          onChange={(e) => toggleConsent(e.target.checked)}
        />
        <span>
          <strong>Contribute my rides to the heat layer</strong>
          <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>
            Off: new uploads are not used for anyone's routing.{' '}
            <a href="/legal/privacy/#heat" target="_blank" rel="noopener" style={{ color: 'inherit', textDecoration: 'underline' }}>How heat works</a>
          </span>
        </span>
      </label>

      <div>
        <strong>Privacy zones</strong>
        <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)', margin: '2px 0 6px' }}>
          Points inside a zone are dropped from your uploaded rides before anything is matched or stored. The zone's location is saved to your account so it can be applied, and is deleted with it.
        </div>
        {zones.map((z) => (
          <div key={z.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
            <span>{z.name} ({(z.radius_m / 1609.344).toFixed(2)} mi)</span>
            <button type="button" className="btn-outline" onClick={() => remove(z.id)} style={{ fontSize: 12, padding: '2px 8px', minHeight: 28 }}>
              Remove
            </button>
          </div>
        ))}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginTop: 6 }}>
          <input
            aria-label="Zone name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={40}
            style={{ flex: '1 1 90px', minWidth: 0, padding: '4px 8px', minHeight: 32, borderRadius: 6, border: '1px solid var(--color-divider, #D1D8D8)' }}
          />
          <select
            aria-label="Zone radius"
            value={radius}
            onChange={(e) => setRadius(Number(e.target.value))}
            style={{ minHeight: 32, borderRadius: 6 }}
          >
            {RADII.map((r) => <option key={r.m} value={r.m}>{r.label}</option>)}
          </select>
          <button type="button" className="btn-outline" onClick={addHere} style={{ fontSize: 12, padding: '2px 8px', minHeight: 32 }}>
            Add zone here
          </button>
        </div>
        {status && <div role="alert" style={{ fontSize: 12, color: '#B3261E', marginTop: 4 }}>{status}</div>}
      </div>
    </div>
  );
};

export default PrivacyControls;
