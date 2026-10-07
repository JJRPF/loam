import React, { useState } from 'react';
import { NH_TRAILHEAD_PRESETS } from '../types';

export const ExplorePanel: React.FC = () => {
  const [activeNetwork, setActiveNetwork] = useState(NH_TRAILHEAD_PRESETS[0]);
  const [reportedMessage, setReportedMessage] = useState<string | null>(null);

  const handleConfirmOpen = () => {
    setReportedMessage('Confirmed open! Thank you for updating trail conditions.');
    setTimeout(() => setReportedMessage(null), 3000);
  };

  const handleReportProblem = () => {
    const issue = prompt('Describe condition or issue (e.g. blowdown, mud, closure):');
    if (issue) {
      setReportedMessage(`Report submitted: "${issue}". Local trail stewards notified.`);
      setTimeout(() => setReportedMessage(null), 4000);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '4px 0 24px 0' }}>
      <h2 style={{ fontSize: 16, fontWeight: 700, color: '#1D3B34' }}>Explore Trails & Heat</h2>

      {/* Network Selector */}
      <div>
        <label style={{ fontSize: 13, fontWeight: 700, color: '#1D3B34', display: 'block', marginBottom: 4 }}>
          Featured Trail Network
        </label>
        <select
          value={activeNetwork.name}
          onChange={(e) => {
            const found = NH_TRAILHEAD_PRESETS.find(p => p.name === e.target.value);
            if (found) setActiveNetwork(found);
          }}
          style={{
            width: '100%',
            padding: '10px 12px',
            borderRadius: 8,
            border: '1px solid #D1D8D8',
            backgroundColor: '#FFFFFF',
            color: '#1D3B34',
            fontSize: 14,
            fontWeight: 600
          }}
        >
          {NH_TRAILHEAD_PRESETS.map(th => (
            <option key={th.name} value={th.name}>
              {th.name} ({th.region})
            </option>
          ))}
        </select>
      </div>

      {/* Trail Card & Conditions */}
      <div style={{ backgroundColor: '#FFFFFF', borderRadius: 8, border: '1px solid #D1D8D8', padding: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
          <div>
            <h3 style={{ fontSize: 16, fontWeight: 700, color: '#1D3B34' }}>{activeNetwork.name}</h3>
            <div style={{ fontSize: 12, color: '#42675E' }}>{activeNetwork.region}</div>
          </div>
          <span style={{ fontSize: 11, fontWeight: 700, backgroundColor: '#A9BF7A', color: '#1D3B34', padding: '3px 8px', borderRadius: 4 }}>
            Open
          </span>
        </div>

        <p style={{ fontSize: 13, color: '#1D3B34', lineHeight: 1.4, margin: '8px 0' }}>
          {activeNetwork.description}
        </p>

        {/* Trail Trust Info */}
        <div style={{ backgroundColor: '#F3F7F7', padding: 10, borderRadius: 6, fontSize: 12, color: '#1D3B34', display: 'flex', flexDirection: 'column', gap: 4, marginTop: 8 }}>
          <div>• <strong>Status:</strong> Confirmed open 2 days ago by 6 local riders.</div>
          <div>• <strong>Recency Heat:</strong> High usage in the last 12 months.</div>
          <div>• <strong>Access:</strong> Public multi-use state park. No active DNR restrictions.</div>
        </div>

        {/* Action Buttons */}
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button
            type="button"
            onClick={handleConfirmOpen}
            className="btn-secondary"
            style={{ flex: 1, fontSize: 13, borderColor: '#A9BF7A', color: '#1D3B34' }}
          >
            Still Open
          </button>
          <button
            type="button"
            onClick={handleReportProblem}
            className="btn-outline"
            style={{ flex: 1, fontSize: 13, color: '#C73E00' }}
          >
            Report Problem
          </button>
        </div>

        {reportedMessage && (
          <div style={{ fontSize: 12, color: '#1D3B34', backgroundColor: '#E7ECEC', padding: '8px 10px', borderRadius: 6, marginTop: 8 }}>
            {reportedMessage}
          </div>
        )}
      </div>

      {/* Heat Layer Guide */}
      <div style={{ backgroundColor: '#FFFFFF', borderRadius: 8, border: '1px solid #D1D8D8', padding: 14 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, color: '#1D3B34', marginBottom: 4 }}>
          Community Heat Layer
        </h3>
        <p style={{ fontSize: 13, color: '#42675E', lineHeight: 1.4 }}>
          Trails are weighted by verified activity over a 12-month window. Ghost trails and overgrown doubletracks are automatically deprioritized.
        </p>
      </div>
    </div>
  );
};
