import React, { useState } from 'react';
import type { RouteResponse } from '../types';
import { submitBadRouteReport, type BadRouteReportResult } from '../services/api';

export const REPORT_NOTICE =
  "This report is filed as a public issue on GitHub, so anyone can read it. It includes your comment, your route settings and the route line with the first and last 0.5 mi removed; your start and end points are not included. Don't include personal details.";

interface Props {
  route: RouteResponse;
  options: RouteResponse[];
  request: Record<string, unknown> | null;
  source?: 'search' | 'saved' | 'shared' | 'other';
  savedRouteId?: string;
  onClose: () => void;
}

export const ReportBadRouteModal: React.FC<Props> = ({ route, options, request, source, savedRouteId, onClose }) => {
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BadRouteReportResult | null>(null);
  const valid = comment.trim().length >= 10 && comment.trim().length <= 2000;

  const submit = async () => {
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await submitBadRouteReport(comment.trim(), request, route, options, {
        source: savedRouteId ? 'saved' : request ? 'search' : (source ?? 'other'),
        savedRouteId
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not send the report.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Report bad route"
      style={{ position: 'fixed', inset: 0, zIndex: 2000, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{ background: 'var(--color-card-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', borderRadius: 10, padding: 16, maxWidth: 440, width: '100%', maxHeight: '90vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ fontSize: 16, fontWeight: 700 }}>Report bad route</div>
        {result ? (
          <>
            <div style={{ fontSize: 13 }}>
              {result.message}{' '}
              {result.issue_url && (
                <a href={result.issue_url} target="_blank" rel="noopener noreferrer">View the issue</a>
              )}
            </div>
            <button type="button" className="btn-secondary" onClick={onClose} style={{ minHeight: 36 }}>Close</button>
          </>
        ) : (
          <>
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>{route.name}</div>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              maxLength={2000}
              rows={5}
              placeholder="What's wrong with this route?"
              aria-label="What's wrong with this route?"
              style={{ width: '100%', boxSizing: 'border-box', padding: 8, borderRadius: 6, border: '1px solid var(--color-divider, #D1D8D8)', fontSize: 14, fontFamily: 'inherit', background: 'var(--color-input-bg, #FFFFFF)', color: 'inherit' }}
            />
            <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)' }}>
              {comment.trim().length}/2000 (at least 10 characters)
            </div>
            <div style={{ fontSize: 12, lineHeight: 1.4 }}>
              {REPORT_NOTICE}{' '}
              <a href="/legal/privacy/#reports" target="_blank" rel="noopener" style={{ color: 'inherit', textDecoration: 'underline' }}>Privacy Policy</a>
            </div>
            {!request && (
              <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>
                Sent without the search settings, since this route was saved earlier.
              </div>
            )}
            {error && <div role="alert" style={{ fontSize: 12, color: '#B3261E' }}>{error}</div>}
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" className="btn-secondary" onClick={onClose} style={{ flex: 1, minHeight: 36 }}>Cancel</button>
              <button type="button" className="btn-primary" onClick={submit} disabled={!valid || busy} style={{ flex: 1, minHeight: 36 }}>
                {busy ? 'Sending...' : 'Submit report'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default ReportBadRouteModal;
