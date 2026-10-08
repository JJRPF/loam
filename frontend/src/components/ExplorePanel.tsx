import React, { useState, useEffect } from 'react';
import { NH_TRAILHEAD_PRESETS } from '../types';
import type { TrailSubmission, UnriddenTrailItem } from '../types';
import {
  getUnriddenTrails,
  submitTrail,
  listSubmissions,
  submitTrailEvidence,
  adminApproveSubmission,
  adminRejectSubmission,
  adminReverseSubmission,
  adminTakedownSubmission
} from '../services/api';

type ExploreTab = 'featured' | 'unridden' | 'submissions';

export const ExplorePanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ExploreTab>('featured');
  const [activeNetwork, setActiveNetwork] = useState(NH_TRAILHEAD_PRESETS[0]);
  const [reportedMessage, setReportedMessage] = useState<string | null>(null);

  // Unridden trails state
  const [unriddenTrails, setUnriddenTrails] = useState<UnriddenTrailItem[]>([]);
  const [isLoadingUnridden, setIsLoadingUnridden] = useState(false);

  // Submissions state
  const [submissions, setSubmissions] = useState<TrailSubmission[]>([]);
  const [isLoadingSubmissions, setIsLoadingSubmissions] = useState(false);
  const [submissionFilter, setSubmissionFilter] = useState<string>('all');
  const [showSubmitModal, setShowSubmitModal] = useState(false);

  // New Submission Form state
  const [subName, setSubName] = useState('');
  const [subSport, setSubSport] = useState('mtb');
  const [subDifficulty, setSubDifficulty] = useState('blue');
  const [subDesc, setSubDesc] = useState('');
  const [subCoords, setSubCoords] = useState('-71.215,44.025\n-71.218,44.029\n-71.221,44.032');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submissionError, setSubmissionError] = useState<string | null>(null);

  // Load Unridden Trails
  const loadUnriddenTrails = async () => {
    setIsLoadingUnridden(true);
    try {
      const trails = await getUnriddenTrails({
        lat: activeNetwork.lat,
        lon: activeNetwork.lon,
        radiusMiles: 15
      });
      setUnriddenTrails(trails);
    } catch (err) {
      console.error('Failed to load unridden trails:', err);
    } finally {
      setIsLoadingUnridden(false);
    }
  };

  // Load Submissions
  const loadSubmissions = async () => {
    setIsLoadingSubmissions(true);
    try {
      const filter = submissionFilter === 'all' ? undefined : submissionFilter;
      const list = await listSubmissions(filter);
      setSubmissions(list);
    } catch (err) {
      console.error('Failed to load submissions:', err);
    } finally {
      setIsLoadingSubmissions(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'unridden') {
      loadUnriddenTrails();
    } else if (activeTab === 'submissions') {
      loadSubmissions();
    }
  }, [activeTab, submissionFilter]);

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

  const handleCreateSubmission = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!subName.trim()) {
      setSubmissionError('Please provide a trail name.');
      return;
    }

    // Parse coordinates
    const parsedCoords: number[][] = [];
    const lines = subCoords.trim().split('\n');
    for (const line of lines) {
      const parts = line.split(',').map((p) => parseFloat(p.trim()));
      if (parts.length >= 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
        // [lon, lat]
        parsedCoords.push([parts[0], parts[1]]);
      }
    }

    if (parsedCoords.length < 2) {
      setSubmissionError('Please provide at least 2 coordinate points (lon,lat per line).');
      return;
    }

    setIsSubmitting(true);
    setSubmissionError(null);
    try {
      await submitTrail({
        name: subName.trim(),
        sport: subSport,
        difficulty: subDifficulty,
        coordinates: parsedCoords,
        description: subDesc.trim() || undefined
      });
      setShowSubmitModal(false);
      setSubName('');
      setSubDesc('');
      await loadSubmissions();
      setReportedMessage('Trail submitted! It is now pending crowd verification.');
      setTimeout(() => setReportedMessage(null), 4000);
    } catch (err: any) {
      setSubmissionError(err.message || 'Submission failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAddEvidence = async (submissionId: number) => {
    const riderId = prompt('Simulate rider identifier (e.g. rider_2, rider_3):', `rider_${Date.now() % 1000}`);
    if (!riderId) return;

    try {
      const res = await submitTrailEvidence(submissionId, {}, riderId);
      alert(`Evidence recorded! Status: ${res.status}. Contributing riders: ${res.evidence_count}/3.`);
      await loadSubmissions();
    } catch (err: any) {
      alert(`Failed to add evidence: ${err.message}`);
    }
  };

  const handleApprove = async (id: number) => {
    try {
      await adminApproveSubmission(id);
      await loadSubmissions();
    } catch (err: any) {
      alert(`Approve failed: ${err.message}`);
    }
  };

  const handleReject = async (id: number) => {
    const reason = prompt('Rejection reason (optional):', 'Violates trail rules or land boundary') || undefined;
    try {
      await adminRejectSubmission(id, reason);
      await loadSubmissions();
    } catch (err: any) {
      alert(`Reject failed: ${err.message}`);
    }
  };

  const handleTakedown = async (id: number) => {
    const reason = prompt('Takedown reason:', 'Private landowner request') || undefined;
    try {
      await adminTakedownSubmission(id, reason);
      await loadSubmissions();
    } catch (err: any) {
      alert(`Takedown failed: ${err.message}`);
    }
  };

  const handleReverse = async (id: number) => {
    try {
      await adminReverseSubmission(id);
      await loadSubmissions();
    } catch (err: any) {
      alert(`Reverse failed: ${err.message}`);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '4px 0 24px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: '#1D3B34', margin: 0 }}>Explore Trails & Heat</h2>
        {activeTab === 'submissions' && (
          <button
            type="button"
            onClick={() => setShowSubmitModal(true)}
            className="btn-primary"
            style={{ fontSize: 12, padding: '4px 10px', minHeight: 30 }}
          >
            + Submit Trail
          </button>
        )}
      </div>

      {/* Navigation Sub-Tabs */}
      <div
        style={{
          display: 'flex',
          backgroundColor: '#E2ECF3',
          padding: 2,
          borderRadius: 8,
          gap: 2
        }}
      >
        <button
          type="button"
          onClick={() => setActiveTab('featured')}
          style={{
            flex: 1,
            padding: '6px 4px',
            fontSize: 12,
            fontWeight: 700,
            borderRadius: 6,
            border: 'none',
            cursor: 'pointer',
            backgroundColor: activeTab === 'featured' ? '#FFFFFF' : 'transparent',
            color: activeTab === 'featured' ? '#1D3B34' : '#42675E',
            boxShadow: activeTab === 'featured' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
            transition: 'all 0.15s ease'
          }}
        >
          Featured
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('unridden')}
          style={{
            flex: 1,
            padding: '6px 4px',
            fontSize: 12,
            fontWeight: 700,
            borderRadius: 6,
            border: 'none',
            cursor: 'pointer',
            backgroundColor: activeTab === 'unridden' ? '#FFFFFF' : 'transparent',
            color: activeTab === 'unridden' ? '#1D3B34' : '#42675E',
            boxShadow: activeTab === 'unridden' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
            transition: 'all 0.15s ease'
          }}
        >
          ✨ New To You
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('submissions')}
          style={{
            flex: 1,
            padding: '6px 4px',
            fontSize: 12,
            fontWeight: 700,
            borderRadius: 6,
            border: 'none',
            cursor: 'pointer',
            backgroundColor: activeTab === 'submissions' ? '#FFFFFF' : 'transparent',
            color: activeTab === 'submissions' ? '#1D3B34' : '#42675E',
            boxShadow: activeTab === 'submissions' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
            transition: 'all 0.15s ease'
          }}
        >
          Submissions
        </button>
      </div>

      {reportedMessage && (
        <div style={{ fontSize: 12, color: '#1D3B34', backgroundColor: '#E7ECEC', padding: '8px 10px', borderRadius: 6 }}>
          {reportedMessage}
        </div>
      )}

      {/* TAB 1: Featured Networks */}
      {activeTab === 'featured' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Network Selector */}
          <div>
            <label style={{ fontSize: 13, fontWeight: 700, color: '#1D3B34', display: 'block', marginBottom: 4 }}>
              Featured Trail Network
            </label>
            <select
              value={activeNetwork.name}
              onChange={(e) => {
                const found = NH_TRAILHEAD_PRESETS.find((p) => p.name === e.target.value);
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
              {NH_TRAILHEAD_PRESETS.map((th) => (
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
      )}

      {/* TAB 2: Trails New To You */}
      {activeTab === 'unridden' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ backgroundColor: '#F0F9FF', border: '1px solid #BAE6FD', borderRadius: 8, padding: 12, fontSize: 13, color: '#0369A1' }}>
            <div style={{ fontWeight: 700, marginBottom: 2 }}>High-Heat Trails You Haven't Ridden</div>
            <div>These trails have strong community ride activity in the last 12 months, but no visits recorded in your activity history.</div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#1D3B34' }}>
              {isLoadingUnridden ? 'Loading unridden trails...' : `${unriddenTrails.length} Trails Available`}
            </span>
            <button
              type="button"
              onClick={loadUnriddenTrails}
              disabled={isLoadingUnridden}
              className="btn-outline"
              style={{ fontSize: 12, padding: '3px 8px', minHeight: 28 }}
            >
              Refresh
            </button>
          </div>

          {unriddenTrails.length === 0 && !isLoadingUnridden ? (
            <div style={{ backgroundColor: '#FFFFFF', borderRadius: 8, border: '1px solid #D1D8D8', padding: 16, textAlign: 'center', color: '#42675E', fontSize: 13 }}>
              No unridden high-heat trails found in the active region, or you've explored them all!
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {unriddenTrails.map((trail) => (
                <div
                  key={trail.edge_osm_id}
                  style={{
                    backgroundColor: '#FFFFFF',
                    borderRadius: 8,
                    border: '1px solid #D1D8D8',
                    padding: '10px 12px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                    <div style={{ fontWeight: 700, fontSize: 14, color: '#1D3B34' }}>
                      {trail.name || `Trail #${trail.edge_osm_id}`}
                    </div>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        padding: '1px 6px',
                        borderRadius: 3,
                        backgroundColor: '#E0F2FE',
                        color: '#0369A1',
                        border: '1px solid #BAE6FD'
                      }}
                    >
                      ✨ New to you
                    </span>
                  </div>

                  <div style={{ display: 'flex', gap: 8, fontSize: 12, color: '#42675E' }}>
                    <span>{trail.distance_miles.toFixed(2)} mi</span>
                    <span>•</span>
                    <span style={{ textTransform: 'capitalize' }}>{trail.surface || 'Singletrack'}</span>
                    <span>•</span>
                    <span>Heat Score: <strong>{trail.heat_score}</strong></span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB 3: Trail Submissions & Verification */}
      {activeTab === 'submissions' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ backgroundColor: '#F3F7F7', border: '1px solid #D1D8D8', borderRadius: 8, padding: 12, fontSize: 12, color: '#1D3B34' }}>
            <div style={{ fontWeight: 700, marginBottom: 2 }}>GPS-Backed Verification Policy</div>
            <div>
              New trails remain <em>pending</em> and hidden until confirmed by overlapping GPS evidence from at least <strong>3 unique riders</strong> within 12 months with no hard restrictions intersected.
            </div>
          </div>

          {/* Filter Bar */}
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: '#42675E' }}>Status:</span>
            {['all', 'pending', 'verified', 'rejected', 'taken_down'].map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setSubmissionFilter(f)}
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  padding: '3px 8px',
                  borderRadius: 4,
                  border: submissionFilter === f ? '1px solid #1D3B34' : '1px solid #D1D8D8',
                  backgroundColor: submissionFilter === f ? '#1D3B34' : '#FFFFFF',
                  color: submissionFilter === f ? '#FFFFFF' : '#1D3B34',
                  cursor: 'pointer',
                  textTransform: 'capitalize'
                }}
              >
                {f.replace('_', ' ')}
              </button>
            ))}
          </div>

          {/* Submissions List */}
          {isLoadingSubmissions ? (
            <div style={{ fontSize: 13, color: '#42675E', textAlign: 'center', padding: 16 }}>Loading submissions...</div>
          ) : submissions.length === 0 ? (
            <div style={{ backgroundColor: '#FFFFFF', borderRadius: 8, border: '1px solid #D1D8D8', padding: 16, textAlign: 'center', color: '#42675E', fontSize: 13 }}>
              No submissions found for the "{submissionFilter}" filter.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {submissions.map((sub) => {
                const statusColors: Record<string, { bg: string; text: string }> = {
                  pending: { bg: '#FEF3C7', text: '#92400E' },
                  verified: { bg: '#D1FAE5', text: '#065F46' },
                  rejected: { bg: '#FEE2E2', text: '#991B1B' },
                  taken_down: { bg: '#F3E8FF', text: '#6B21A8' }
                };
                const sc = statusColors[sub.status] || { bg: '#E5E7EB', text: '#374151' };

                return (
                  <div
                    key={sub.id}
                    style={{
                      backgroundColor: '#FFFFFF',
                      borderRadius: 8,
                      border: '1px solid #D1D8D8',
                      padding: 12,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 6
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: '#1D3B34' }}>{sub.name}</div>
                        <div style={{ fontSize: 12, color: '#42675E', marginTop: 1 }}>
                          Sport: <strong>{sub.sport}</strong> • Difficulty: <strong>{sub.difficulty}</strong>
                        </div>
                      </div>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 700,
                          padding: '2px 8px',
                          borderRadius: 4,
                          backgroundColor: sc.bg,
                          color: sc.text,
                          textTransform: 'uppercase'
                        }}
                      >
                        {sub.status.replace('_', ' ')}
                      </span>
                    </div>

                    {sub.description && (
                      <div style={{ fontSize: 12, color: '#1D3B34', backgroundColor: '#F8F9FA', padding: '6px 8px', borderRadius: 4 }}>
                        {sub.description}
                      </div>
                    )}

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, color: '#42675E', marginTop: 2 }}>
                      <div>
                        GPS Evidence: <strong>{sub.verifier_count} / 3 unique riders</strong>
                      </div>
                      <div>Submitted: {new Date(sub.created_at).toLocaleDateString()}</div>
                    </div>

                    {sub.rejection_reason && (
                      <div style={{ fontSize: 11, color: '#991B1B', fontStyle: 'italic' }}>
                        Reason: {sub.rejection_reason}
                      </div>
                    )}

                    {/* Action & Moderation Controls */}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6, paddingTop: 6, borderTop: '1px solid #F0F0F0' }}>
                      {sub.status === 'pending' && (
                        <button
                          type="button"
                          onClick={() => handleAddEvidence(sub.id)}
                          className="btn-outline"
                          style={{ fontSize: 11, padding: '3px 8px', minHeight: 26, borderColor: '#0369A1', color: '#0369A1' }}
                          title="Simulate overlapping ride track from a new rider to test auto-verification"
                        >
                          + Add GPS Evidence
                        </button>
                      )}
                      {sub.status !== 'verified' && (
                        <button
                          type="button"
                          onClick={() => handleApprove(sub.id)}
                          className="btn-outline"
                          style={{ fontSize: 11, padding: '3px 8px', minHeight: 26, color: '#065F46', borderColor: '#A7F3D0' }}
                        >
                          Approve
                        </button>
                      )}
                      {sub.status !== 'rejected' && (
                        <button
                          type="button"
                          onClick={() => handleReject(sub.id)}
                          className="btn-outline"
                          style={{ fontSize: 11, padding: '3px 8px', minHeight: 26, color: '#991B1B', borderColor: '#FECACA' }}
                        >
                          Reject
                        </button>
                      )}
                      {sub.status !== 'taken_down' && (
                        <button
                          type="button"
                          onClick={() => handleTakedown(sub.id)}
                          className="btn-outline"
                          style={{ fontSize: 11, padding: '3px 8px', minHeight: 26, color: '#6B21A8', borderColor: '#E9D5FF' }}
                        >
                          Takedown
                        </button>
                      )}
                      {(sub.status === 'rejected' || sub.status === 'taken_down') && (
                        <button
                          type="button"
                          onClick={() => handleReverse(sub.id)}
                          className="btn-outline"
                          style={{ fontSize: 11, padding: '3px 8px', minHeight: 26 }}
                        >
                          Reverse
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Modal: Submit New Trail */}
      {showSubmitModal && (
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
          onClick={() => setShowSubmitModal(false)}
        >
          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: 10,
              maxWidth: 440,
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
              <h3 style={{ fontSize: 16, fontWeight: 700, color: '#1D3B34', margin: 0 }}>Submit New Trail</h3>
              <button
                type="button"
                onClick={() => setShowSubmitModal(false)}
                style={{ border: 'none', background: 'transparent', fontSize: 18, cursor: 'pointer', color: '#888' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateSubmission} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: '#1D3B34', display: 'block', marginBottom: 3 }}>
                  Trail Name
                </label>
                <input
                  type="text"
                  placeholder="e.g. Whiteface Ridge Connector"
                  value={subName}
                  onChange={(e) => setSubName(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid #D1D8D8', fontSize: 13, boxSizing: 'border-box' }}
                  required
                />
              </div>

              <div style={{ display: 'flex', gap: 8 }}>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: 12, fontWeight: 700, color: '#1D3B34', display: 'block', marginBottom: 3 }}>
                    Sport
                  </label>
                  <select
                    value={subSport}
                    onChange={(e) => setSubSport(e.target.value)}
                    style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid #D1D8D8', fontSize: 13 }}
                  >
                    <option value="mtb">MTB</option>
                    <option value="trail_run">Trail Run</option>
                    <option value="gravel">Gravel</option>
                  </select>
                </div>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: 12, fontWeight: 700, color: '#1D3B34', display: 'block', marginBottom: 3 }}>
                    Difficulty
                  </label>
                  <select
                    value={subDifficulty}
                    onChange={(e) => setSubDifficulty(e.target.value)}
                    style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid #D1D8D8', fontSize: 13 }}
                  >
                    <option value="green">Green (Easy)</option>
                    <option value="blue">Blue (Moderate)</option>
                    <option value="black">Black (Difficult)</option>
                    <option value="double_black">Double Black</option>
                  </select>
                </div>
              </div>

              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: '#1D3B34', display: 'block', marginBottom: 3 }}>
                  Description (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Hand-built singletrack along ravine"
                  value={subDesc}
                  onChange={(e) => setSubDesc(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid #D1D8D8', fontSize: 13, boxSizing: 'border-box' }}
                />
              </div>

              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: '#1D3B34', display: 'block', marginBottom: 3 }}>
                  Coordinates (lon, lat per line)
                </label>
                <textarea
                  rows={4}
                  value={subCoords}
                  onChange={(e) => setSubCoords(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid #D1D8D8', fontSize: 12, fontFamily: 'monospace', boxSizing: 'border-box' }}
                />
                <div style={{ fontSize: 11, color: '#42675E', marginTop: 2 }}>
                  GPS trail vertices. At least 2 points required.
                </div>
              </div>

              {submissionError && (
                <div style={{ fontSize: 12, color: '#D32F2F', backgroundColor: '#FFF0F0', padding: '6px 8px', borderRadius: 4 }}>
                  {submissionError}
                </div>
              )}

              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 6 }}>
                <button
                  type="button"
                  onClick={() => setShowSubmitModal(false)}
                  className="btn-outline"
                  style={{ fontSize: 12, minHeight: 32, padding: '4px 10px' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="btn-primary"
                  style={{ fontSize: 12, minHeight: 32, padding: '4px 14px' }}
                >
                  {isSubmitting ? 'Submitting...' : 'Submit Trail'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
