import React, { useState, useEffect } from 'react';
import { getDevStatus, clearDevCache, recalculateDevHeat } from '../services/api';

interface DevConsolePanelProps {
  userEmail?: string;
  onClose?: () => void;
  isDarkMode?: boolean;
}

interface DevStatusData {
  status: string;
  app_name: string;
  app_version: string;
  database_connected: boolean;
  edge_count: number;
  activity_count: number;
  heat_edge_count: number;
  saved_route_count: number;
  connectors: Array<{
    name: string;
    display_name: string;
    enabled: boolean;
    connected: boolean;
    last_synced_at: string | null;
    description: string;
  }>;
  developer_email: string;
  uptime_seconds: number;
}

export const DevConsolePanel: React.FC<DevConsolePanelProps> = ({
  userEmail,
  onClose,
  isDarkMode = true
}) => {
  const [statusData, setStatusData] = useState<DevStatusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [actionLogs, setActionLogs] = useState<Array<{ time: string; msg: string; type: 'info' | 'success' | 'error' }>>([]);

  const addLog = (msg: string, type: 'info' | 'success' | 'error' = 'info') => {
    const time = new Date().toLocaleTimeString();
    setActionLogs((prev) => [{ time, msg, type }, ...prev.slice(0, 19)]);
  };

  const loadStatus = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getDevStatus();
      setStatusData(data);
      addLog(`Status refreshed: ${data.status.toUpperCase()} (${data.edge_count} edges, ${data.activity_count} activities)`, 'info');
    } catch (err: any) {
      setError(err.message || 'Failed to fetch developer status');
      addLog(`Error fetching status: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const handleClearCache = async () => {
    setActionInProgress('clearCache');
    try {
      const res = await clearDevCache();
      addLog(res.message || 'Cache successfully cleared.', 'success');
      await loadStatus();
    } catch (err: any) {
      addLog(`Failed to clear cache: ${err.message}`, 'error');
    } finally {
      setActionInProgress(null);
    }
  };

  const handleRecalculateHeat = async () => {
    setActionInProgress('recalculateHeat');
    try {
      const res = await recalculateDevHeat();
      addLog(`Heat recalculation completed: ${res.updated_edges ?? 0} edges updated.`, 'success');
      await loadStatus();
    } catch (err: any) {
      addLog(`Failed to recalculate heat: ${err.message}`, 'error');
    } finally {
      setActionInProgress(null);
    }
  };

  const formatUptime = (seconds: number) => {
    const d = Math.floor(seconds / (3600 * 24));
    const h = Math.floor((seconds % (3600 * 24)) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const parts = [];
    if (d > 0) parts.push(`${d}d`);
    if (h > 0) parts.push(`${h}h`);
    if (m > 0) parts.push(`${m}m`);
    parts.push(`${s}s`);
    return parts.join(' ');
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 16,
        padding: '16px',
        backgroundColor: isDarkMode ? '#1A2925' : 'var(--color-bg-panel, #FFFFFF)',
        color: isDarkMode ? '#E7ECEC' : 'var(--color-text-primary, #1D3B34)',
        borderRadius: 8
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--color-divider, #D1D8D8)', paddingBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 20 }}>🛠️</span>
          <div>
            <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: 'var(--color-text-primary, #1D3B34)' }}>
              Developer Console
            </h2>
            <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)' }}>
              Admin session ({userEmail})
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            type="button"
            onClick={loadStatus}
            disabled={loading}
            className="btn-outline"
            style={{ fontSize: 11, padding: '3px 8px', minHeight: 28 }}
            title="Refresh developer telemetry"
          >
            {loading ? '↻ Checking...' : '↻ Refresh'}
          </button>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              style={{
                border: 'none',
                background: 'transparent',
                fontSize: 18,
                cursor: 'pointer',
                color: 'var(--color-text-secondary, #888)',
                padding: '0 4px'
              }}
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {error && (
        <div
          style={{
            backgroundColor: '#FEE2E2',
            color: '#B91C1C',
            border: '1px solid #FCA5A5',
            padding: '8px 12px',
            borderRadius: 6,
            fontSize: 12
          }}
        >
          <strong>Auth / Access Error:</strong> {error}
        </div>
      )}

      {/* Health & Metrics Cards */}
      {statusData && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
          <div style={{ backgroundColor: 'var(--color-bg-subtle, #F8F9FA)', padding: 10, borderRadius: 6, border: '1px solid var(--color-divider, #E0E0E0)' }}>
            <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)', fontWeight: 600 }}>App Status</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: statusData.status === 'healthy' ? '#16A34A' : '#DC2626', marginTop: 2 }}>
              ● {statusData.status.toUpperCase()}
            </div>
            <div style={{ fontSize: 10, color: 'var(--color-text-secondary, #666)' }}>v{statusData.app_version}</div>
          </div>

          <div style={{ backgroundColor: 'var(--color-bg-subtle, #F8F9FA)', padding: 10, borderRadius: 6, border: '1px solid var(--color-divider, #E0E0E0)' }}>
            <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)', fontWeight: 600 }}>PostgreSQL / DB</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: statusData.database_connected ? '#16A34A' : '#EA580C', marginTop: 2 }}>
              {statusData.database_connected ? 'Connected' : 'Offline'}
            </div>
            <div style={{ fontSize: 10, color: 'var(--color-text-secondary, #666)' }}>PostGIS / Spatial</div>
          </div>

          <div style={{ backgroundColor: 'var(--color-bg-subtle, #F8F9FA)', padding: 10, borderRadius: 6, border: '1px solid var(--color-divider, #E0E0E0)' }}>
            <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)', fontWeight: 600 }}>Server Uptime</div>
            <div style={{ fontSize: 13, fontWeight: 700, marginTop: 2 }}>
              {formatUptime(statusData.uptime_seconds)}
            </div>
            <div style={{ fontSize: 10, color: 'var(--color-text-secondary, #666)' }}>Continuous daemon</div>
          </div>

          <div style={{ backgroundColor: 'var(--color-bg-subtle, #F8F9FA)', padding: 10, borderRadius: 6, border: '1px solid var(--color-divider, #E0E0E0)' }}>
            <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)', fontWeight: 600 }}>GraphHopper Edges</div>
            <div style={{ fontSize: 14, fontWeight: 700, marginTop: 2 }}>
              {statusData.edge_count.toLocaleString()}
            </div>
            <div style={{ fontSize: 10, color: 'var(--color-text-secondary, #666)' }}>Indexed trail network</div>
          </div>

          <div style={{ backgroundColor: 'var(--color-bg-subtle, #F8F9FA)', padding: 10, borderRadius: 6, border: '1px solid var(--color-divider, #E0E0E0)' }}>
            <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)', fontWeight: 600 }}>Heat Edges</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-blaze, #FF5B14)', marginTop: 2 }}>
              {statusData.heat_edge_count.toLocaleString()}
            </div>
            <div style={{ fontSize: 10, color: 'var(--color-text-secondary, #666)' }}>{statusData.activity_count} activities</div>
          </div>

          <div style={{ backgroundColor: 'var(--color-bg-subtle, #F8F9FA)', padding: 10, borderRadius: 6, border: '1px solid var(--color-divider, #E0E0E0)' }}>
            <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)', fontWeight: 600 }}>Saved Routes</div>
            <div style={{ fontSize: 14, fontWeight: 700, marginTop: 2 }}>
              {statusData.saved_route_count.toLocaleString()}
            </div>
            <div style={{ fontSize: 10, color: 'var(--color-text-secondary, #666)' }}>User route store</div>
          </div>
        </div>
      )}

      {/* Connectors Telemetry */}
      {statusData && (
        <div style={{ backgroundColor: 'var(--color-bg-subtle, #F8F9FA)', borderRadius: 6, border: '1px solid var(--color-divider, #E0E0E0)', padding: 12 }}>
          <h3 style={{ fontSize: 13, fontWeight: 700, margin: '0 0 8px 0', color: 'var(--color-text-primary, #1D3B34)' }}>
            Connector Integrations
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {statusData.connectors.map((c) => (
              <div
                key={c.name}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  fontSize: 12,
                  padding: '6px 8px',
                  backgroundColor: 'var(--color-card-bg, #FFFFFF)',
                  borderRadius: 4,
                  border: '1px solid var(--color-divider, #EAEAEA)'
                }}
              >
                <div>
                  <strong>{c.display_name}</strong>
                  <span style={{ fontSize: 10, color: 'var(--color-text-secondary, #666)', marginLeft: 6 }}>
                    ({c.name})
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      padding: '1px 5px',
                      borderRadius: 3,
                      backgroundColor: c.enabled ? '#DCFCE7' : '#F3F4F6',
                      color: c.enabled ? '#166534' : '#6B7280'
                    }}
                  >
                    {c.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      padding: '1px 5px',
                      borderRadius: 3,
                      backgroundColor: c.connected ? '#E0F2FE' : '#F3F4F6',
                      color: c.connected ? '#0369A1' : '#6B7280'
                    }}
                  >
                    {c.connected ? 'Connected' : 'Disconnected'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Admin Action Operations */}
      <div style={{ backgroundColor: 'var(--color-bg-subtle, #F8F9FA)', borderRadius: 6, border: '1px solid var(--color-divider, #E0E0E0)', padding: 12 }}>
        <h3 style={{ fontSize: 13, fontWeight: 700, margin: '0 0 8px 0', color: 'var(--color-text-primary, #1D3B34)' }}>
          Developer Actions
        </h3>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button
            type="button"
            onClick={handleClearCache}
            disabled={actionInProgress !== null}
            className="btn-outline"
            style={{ fontSize: 12, padding: '6px 12px', minHeight: 32 }}
          >
            {actionInProgress === 'clearCache' ? '⏳ Clearing...' : '🧹 Clear Transient Caches'}
          </button>

          <button
            type="button"
            onClick={handleRecalculateHeat}
            disabled={actionInProgress !== null}
            className="btn-primary"
            style={{ fontSize: 12, padding: '6px 12px', minHeight: 32 }}
          >
            {actionInProgress === 'recalculateHeat' ? '⏳ Recalculating...' : '🔥 Recalculate Heat Layer'}
          </button>

        </div>
      </div>

      {/* Audit Action Log */}
      <div style={{ backgroundColor: 'var(--color-bg-subtle, #F8F9FA)', borderRadius: 6, border: '1px solid var(--color-divider, #E0E0E0)', padding: 12 }}>
        <h3 style={{ fontSize: 12, fontWeight: 700, margin: '0 0 6px 0', color: 'var(--color-text-primary, #1D3B34)' }}>
          Session Audit Log
        </h3>
        {actionLogs.length === 0 ? (
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #888)', fontStyle: 'italic' }}>
            No actions executed in this session.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 140, overflowY: 'auto' }}>
            {actionLogs.map((log, i) => (
              <div
                key={i}
                style={{
                  fontSize: 11,
                  fontFamily: 'monospace',
                  padding: '3px 6px',
                  backgroundColor: 'var(--color-card-bg, #FFFFFF)',
                  borderRadius: 4,
                  borderLeft: `3px solid ${
                    log.type === 'success' ? '#16A34A' : log.type === 'error' ? '#DC2626' : '#2563EB'
                  }`
                }}
              >
                <span style={{ color: 'var(--color-text-secondary, #888)', marginRight: 6 }}>[{log.time}]</span>
                <span>{log.msg}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default DevConsolePanel;
