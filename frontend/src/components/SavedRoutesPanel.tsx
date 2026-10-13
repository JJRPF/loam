import React, { useEffect, useState } from 'react';
import type { SavedRoute, RouteResponse } from '../types';
import { fetchSavedRoutes, deleteSavedRoute } from '../services/api';
import { useAuth } from '../services/auth';
import { formatGain } from '../format';
import { recentRoutes } from '../services/offlineRoutes';

interface SavedRoutesPanelProps {
  onLoadRoute: (route: RouteResponse) => void;
}

export const SavedRoutesPanel: React.FC<SavedRoutesPanelProps> = ({ onLoadRoute }) => {
  const [routes, setRoutes] = useState<SavedRoute[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const { user, ready } = useAuth();
  const [recent, setRecent] = useState<RouteResponse[]>([]);

  useEffect(() => {
    recentRoutes().then(setRecent);
  }, []);

  const loadRoutes = async () => {
    setIsLoading(true);
    try {
      const data = await fetchSavedRoutes();
      setRoutes(data);
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    let ignore = false;
    if (!ready) return;
    if (!user) {
      setRoutes([]);
      setIsLoading(false);
      return;
    }
    fetchSavedRoutes()
      .then(data => {
        if (!ignore) {
          setRoutes(data);
          setIsLoading(false);
        }
      })
      .catch(e => {
        console.error(e);
        if (!ignore) setIsLoading(false);
      });
    return () => { ignore = true; };
  }, [user, ready]);

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm('Delete this saved route?')) {
      await deleteSavedRoute(id);
      setRoutes(prev => prev.filter(r => r.id !== id));
    }
  };

  const handleSelect = (r: SavedRoute) => {
    const coords = r.coordinates || [];
    let bbox = [-71.5, 43.1, -71.2, 43.3];
    if (coords.length > 0) {
      let minLon = coords[0][0], maxLon = coords[0][0];
      let minLat = coords[0][1], maxLat = coords[0][1];
      for (const pt of coords) {
        if (pt[0] < minLon) minLon = pt[0];
        if (pt[0] > maxLon) maxLon = pt[0];
        if (pt[1] < minLat) minLat = pt[1];
        if (pt[1] > maxLat) maxLat = pt[1];
      }
      bbox = [minLon, minLat, maxLon, maxLat];
    }

    const resp: RouteResponse = {
      id: r.id,
      name: r.name,
      sport: r.sport,
      distance_miles: r.distance_miles,
      duration_minutes: (r.distance_miles / 10.0) * 60,
      elevation_gain_ft: r.elevation_gain_ft,
      elevation_loss_ft: r.elevation_loss_ft,
      surface_breakdown: r.surface_breakdown || {},
      surface_strip: r.surface_strip || [],
      coordinates: coords,
      bbox,
      warnings: [],
      verbal_summary: r.verbal_summary
    };
    onLoadRoute(resp);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '4px 0 24px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
          Saved Routes Library
        </h2>
        <button
          type="button"
          onClick={loadRoutes}
          className="btn-outline"
          style={{ fontSize: 12, padding: '2px 8px', minHeight: 28 }}
        >
          Refresh
        </button>
      </div>

      {recent.length > 0 && (
        <section aria-label="Recently viewed routes">
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', marginBottom: 6 }}>
            Recently viewed (available offline)
          </div>
          {recent.map((r, i) => (
            <div
              key={`${r.id || r.name}-${i}`}
              role="button"
              tabIndex={0}
              onClick={() => onLoadRoute(r)}
              onKeyDown={(e) => { if (e.key === 'Enter') onLoadRoute(r); }}
              style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', padding: '8px 12px', marginBottom: 6, cursor: 'pointer', fontSize: 13, color: 'var(--color-text-primary, #1D3B34)', display: 'flex', justifyContent: 'space-between' }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</span>
              <span className="num-tabular" style={{ flexShrink: 0, marginLeft: 8 }}>{(r.distance_miles ?? 0).toFixed(1)} mi</span>
            </div>
          ))}
        </section>
      )}

      {isLoading && (
        <div style={{ padding: 20, textAlign: 'center', color: 'var(--color-text-secondary, #42675E)', fontSize: 14 }}>
          Loading saved routes from database...
        </div>
      )}

      {!isLoading && routes.length === 0 && (
        <div style={{ padding: 24, textAlign: 'center', backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)' }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--color-text-primary, #1D3B34)', marginBottom: 4 }}>
            No saved routes yet
          </div>
          <div style={{ fontSize: 13, color: 'var(--color-text-secondary, #42675E)' }}>
            Plan a route in the Plan tab and tap "Save to Profile" to store it in your account. Routes you view are also kept on this device for offline use.
          </div>
        </div>
      )}

      {!isLoading && routes.map(r => (
        <div
          key={r.id}
          onClick={() => handleSelect(r)}
          style={{
            backgroundColor: 'var(--color-card-bg, #FFFFFF)',
            borderRadius: 8,
            border: '1px solid var(--color-divider, #D1D8D8)',
            padding: 12,
            cursor: 'pointer',
            transition: 'border-color 0.15s ease'
          }}
          onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-blaze, #FF5B14)')}
          onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-divider, #D1D8D8)')}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>{r.name}</div>
              <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)', textTransform: 'capitalize' }}>
                {(r.sport || 'mtb').replace('_', ' ')}
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <span className="num-tabular" style={{ fontSize: 18, fontWeight: 700, color: 'var(--color-blaze, #FF5B14)' }}>
                {(r.distance_miles ?? 0).toFixed(1)} mi
              </span>
              <div className="num-tabular" style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>
                {formatGain(r.elevation_gain_ft)}
              </div>
            </div>
          </div>

          {r.verbal_summary && (
            <div style={{ fontSize: 12, color: 'var(--color-text-primary, #1D3B34)', marginBottom: 8 }}>
              {r.verbal_summary}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--color-divider, #E7ECEC)' }}>
            <span style={{ fontSize: 11, color: 'var(--color-text-secondary, #888)' }}>
              {r.created_at ? new Date(r.created_at).toLocaleDateString() : ''}
            </span>
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  handleSelect(r);
                }}
                className="btn-outline"
                style={{ fontSize: 12, padding: '2px 8px', minHeight: 28, color: 'var(--color-text-primary, #1D3B34)' }}
              >
                Inspect
              </button>
              <button
                type="button"
                onClick={(e) => handleDelete(r.id, e)}
                style={{ fontSize: 12, padding: '2px 8px', minHeight: 28, backgroundColor: 'transparent', color: 'var(--color-blaze, #FF5B14)', border: 'none' }}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};

export default SavedRoutesPanel;
