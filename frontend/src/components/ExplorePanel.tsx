import React, { useState, useEffect } from 'react';
import type { LatLon, Trailhead, TrailSubmission, UnriddenTrailItem } from '../types';
import trailheadData from '../data/trailheads.json';
import {
  getUnriddenTrails,
  submitTrail,
  listSubmissions,
  adminApproveSubmission,
  adminRejectSubmission,
  adminReverseSubmission,
  adminTakedownSubmission,
  fetchHeatMeta,
  heatInfoText,
  type HeatMeta
} from '../services/api';

type ExploreTab = 'featured' | 'unridden' | 'submissions';

const TRAILHEADS: Trailhead[] = trailheadData.trailheads;

interface ExplorePanelProps {
  onPlanFrom?: (start: LatLon) => void;
}

export const ExplorePanel: React.FC<ExplorePanelProps> = ({ onPlanFrom }) => {
  const [activeTab, setActiveTab] = useState<ExploreTab>('featured');
  const [activeNetwork, setActiveNetwork] = useState<Trailhead>(TRAILHEADS[0]);
  const [heatMeta, setHeatMeta] = useState<HeatMeta | null>(null);
  useEffect(() => {
    fetchHeatMeta().then(setHeatMeta).catch(() => setHeatMeta(null));
  }, []);

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
  const [subCoords, setSubCoords] = useState('');
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
        description: subDesc.trim() || undefined,
        coordinates: parsedCoords
      });
      setShowSubmitModal(false);
      setSubName('');
      setSubDesc('');
      await loadSubmissions();
    } catch (err: any) {
      setSubmissionError(err.message || 'Failed to submit trail');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleApprove = async (id: number) => {
    try {
      await adminApproveSubmission(id);
      await loadSubmissions();
    } catch (err: any) {
      alert(`Approval failed: ${err.message}`);
    }
  };

  const handleReject = async (id: number) => {
    const reason = prompt('Rejection reason (e.g. intersects private conservation easement):') || 'Rejected by steward';
    try {
      await adminRejectSubmission(id, reason);
      await loadSubmissions();
    } catch (err: any) {
      alert(`Rejection failed: ${err.message}`);
    }
  };

  const handleTakedown = async (id: number) => {
    const reason = prompt('Takedown reason (e.g. land manager formal request):') || 'Steward takedown';
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
        <h2 style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', margin: 0 }}>
          Explore Trails & Heat
        </h2>
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
          backgroundColor: 'var(--color-slate-light, #E2ECF3)',
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
            backgroundColor: activeTab === 'featured' ? 'var(--color-card-bg, #FFFFFF)' : 'transparent',
            color: activeTab === 'featured' ? 'var(--color-text-primary, #1D3B34)' : 'var(--color-text-secondary, #42675E)',
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
            backgroundColor: activeTab === 'unridden' ? 'var(--color-card-bg, #FFFFFF)' : 'transparent',
            color: activeTab === 'unridden' ? 'var(--color-text-primary, #1D3B34)' : 'var(--color-text-secondary, #42675E)',
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
            backgroundColor: activeTab === 'submissions' ? 'var(--color-card-bg, #FFFFFF)' : 'transparent',
            color: activeTab === 'submissions' ? 'var(--color-text-primary, #1D3B34)' : 'var(--color-text-secondary, #42675E)',
            boxShadow: activeTab === 'submissions' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
            transition: 'all 0.15s ease'
          }}
        >
          Submissions
        </button>
      </div>


      {/* TAB 1: Featured Networks */}
      {activeTab === 'featured' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Network Selector */}
          <div>
            <label style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 4 }}>
              Trail area
            </label>
            <select
              aria-label="Trail area"
              value={activeNetwork.name}
              onChange={(e) => {
                const found = TRAILHEADS.find((p) => p.name === e.target.value);
                if (found) setActiveNetwork(found);
              }}
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: 8,
                border: '1px solid var(--color-input-border, #D1D8D8)',
                backgroundColor: 'var(--color-input-bg, #FFFFFF)',
                color: 'var(--color-text-primary, #1D3B34)',
                fontSize: 14,
                fontWeight: 600
              }}
            >
              {TRAILHEADS.map((th) => (
                <option key={th.name} value={th.name}>
                  {th.area} ({th.town})
                </option>
              ))}
            </select>
          </div>

          {/* Trail area card: everything here comes from OSM */}
          <div style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', padding: 14 }}>
            <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>{activeNetwork.area}</h3>
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>{activeNetwork.town}, NH</div>
            <p style={{ fontSize: 13, color: 'var(--color-text-primary, #1D3B34)', lineHeight: 1.4, margin: '8px 0' }}>
              Start: {activeNetwork.parking_name || 'public parking'}
              {activeNetwork.distance_to_area_m > 0 ? `, ${(activeNetwork.distance_to_area_m * 0.000621371).toFixed(1)} mi from the area boundary` : ', inside the area'}.
            </p>
            <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)' }}>
              Parking and boundary from © OpenStreetMap contributors ({activeNetwork.parking_osm}).
            </div>
            {onPlanFrom && (
              <button
                type="button"
                onClick={() => onPlanFrom({ lat: activeNetwork.lat, lon: activeNetwork.lon, name: activeNetwork.name })}
                className="btn-primary"
                style={{ width: '100%', fontSize: 13, marginTop: 12 }}
              >
                Plan a route from here
              </button>
            )}
          </div>

          {/* Heat Layer Guide */}
          <div style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', padding: 14 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', marginBottom: 4 }}>
              Community Heat Layer
            </h3>
            <p style={{ fontSize: 13, color: 'var(--color-text-secondary, #42675E)', lineHeight: 1.4 }}>
              Trails are weighted by verified activity over a 12-month window. Ghost trails and overgrown doubletracks are automatically deprioritized.
            </p>
            {heatMeta && (
              <p role="note" style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 6 }}>{heatInfoText(heatMeta)}</p>
            )}
          </div>
        </div>
      )}

      {/* TAB 2: Trails New To You */}
      {activeTab === 'unridden' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ backgroundColor: 'var(--color-bg-subtle, #F0F9FF)', border: '1px solid var(--color-divider, #BAE6FD)', borderRadius: 8, padding: 12, fontSize: 13, color: 'var(--color-text-secondary, #0369A1)' }}>
            <div style={{ fontWeight: 700, marginBottom: 2 }}>High-Heat Trails You Haven't Ridden</div>
            <div>These trails have strong community ride activity in the last 12 months, but no visits recorded in your activity history.</div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
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
            <div style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', padding: 16, textAlign: 'center', color: 'var(--color-text-secondary, #42675E)', fontSize: 13 }}>
              No unridden high-heat trails found in the active region, or you've explored them all!
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {unriddenTrails.map((trail) => (
                <div
                  key={trail.edge_osm_id}
                  style={{
                    backgroundColor: 'var(--color-card-bg, #FFFFFF)',
                    borderRadius: 8,
                    border: '1px solid var(--color-divider, #D1D8D8)',
                    padding: '10px 12px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                    <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--color-text-primary, #1D3B34)' }}>
                      {trail.name || 'Named Trail'}
                    </div>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        padding: '1px 6px',
                        borderRadius: 3,
                        backgroundColor: 'var(--color-slate-light, #E0F2FE)',
                        color: 'var(--color-slate, #0369A1)',
                        border: '1px solid var(--color-divider)'
                      }}
                    >
                      ✨ New to you
                    </span>
                  </div>

                  <div style={{ display: 'flex', gap: 8, fontSize: 12, color: 'var(--color-text-secondary, #42675E)' }}>
                    <span>{trail.distance_miles.toFixed(2)} mi</span>
                    <span>•</span>
                    <span style={{ textTransform: 'capitalize' }}>{trail.surface || 'Trail'}</span>
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
          <div style={{ backgroundColor: 'var(--color-bg-subtle, #F3F7F7)', border: '1px solid var(--color-divider, #D1D8D8)', borderRadius: 8, padding: 12, fontSize: 12, color: 'var(--color-text-primary, #1D3B34)' }}>
            <div style={{ fontWeight: 700, marginBottom: 2 }}>GPS-Backed Verification Policy</div>
            <div>
              New trails remain <em>pending</em> and hidden until confirmed by overlapping GPS evidence from at least <strong>3 unique riders</strong> within 12 months with no hard restrictions intersected.
            </div>
          </div>

          {/* Filter Bar */}
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-secondary, #42675E)' }}>Status:</span>
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
                  border: submissionFilter === f ? '1px solid var(--color-blaze, #FF5B14)' : '1px solid var(--color-divider, #D1D8D8)',
                  backgroundColor: submissionFilter === f ? 'var(--color-blaze-dark, #C73E00)' : 'var(--color-card-bg, #FFFFFF)',
                  color: submissionFilter === f ? '#FFFFFF' : 'var(--color-text-primary, #1D3B34)',
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
            <div style={{ fontSize: 13, color: 'var(--color-text-secondary, #42675E)', textAlign: 'center', padding: 16 }}>Loading submissions...</div>
          ) : submissions.length === 0 ? (
            <div style={{ backgroundColor: 'var(--color-card-bg, #FFFFFF)', borderRadius: 8, border: '1px solid var(--color-divider, #D1D8D8)', padding: 16, textAlign: 'center', color: 'var(--color-text-secondary, #42675E)', fontSize: 13 }}>
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
                      backgroundColor: 'var(--color-card-bg, #FFFFFF)',
                      borderRadius: 8,
                      border: '1px solid var(--color-divider, #D1D8D8)',
                      padding: 12,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 6
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>{sub.name}</div>
                        <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)', marginTop: 1 }}>
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
                      <div style={{ fontSize: 12, color: 'var(--color-text-primary, #1D3B34)', backgroundColor: 'var(--color-bg-subtle, #F8F9FA)', padding: '6px 8px', borderRadius: 4, border: '1px solid var(--color-divider)' }}>
                        {sub.description}
                      </div>
                    )}

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, color: 'var(--color-text-secondary, #42675E)', marginTop: 2 }}>
                      <div>
                        GPS Evidence: <strong>{sub.verifier_count} / 3 unique riders</strong>
                      </div>
                      <div>Submitted: {new Date(sub.created_at).toLocaleDateString()}</div>
                    </div>

                    {sub.rejection_reason && (
                      <div style={{ fontSize: 11, color: '#FF6B6B', fontStyle: 'italic' }}>
                        Reason: {sub.rejection_reason}
                      </div>
                    )}

                    {/* Action & Moderation Controls */}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6, paddingTop: 6, borderTop: '1px solid var(--color-divider, #F0F0F0)' }}>
                      {sub.status !== 'verified' && (
                        <button
                          type="button"
                          onClick={() => handleApprove(sub.id)}
                          className="btn-outline"
                          style={{ fontSize: 11, padding: '3px 8px', minHeight: 26, color: '#A9BF7A', borderColor: 'var(--color-divider)' }}
                        >
                          Approve
                        </button>
                      )}
                      {sub.status !== 'rejected' && (
                        <button
                          type="button"
                          onClick={() => handleReject(sub.id)}
                          className="btn-outline"
                          style={{ fontSize: 11, padding: '3px 8px', minHeight: 26, color: '#FF6B6B', borderColor: 'var(--color-divider)' }}
                        >
                          Reject
                        </button>
                      )}
                      {sub.status !== 'taken_down' && (
                        <button
                          type="button"
                          onClick={() => handleTakedown(sub.id)}
                          className="btn-outline"
                          style={{ fontSize: 11, padding: '3px 8px', minHeight: 26, color: '#C084FC', borderColor: 'var(--color-divider)' }}
                        >
                          Takedown
                        </button>
                      )}
                      {(sub.status === 'rejected' || sub.status === 'taken_down') && (
                        <button
                          type="button"
                          onClick={() => handleReverse(sub.id)}
                          className="btn-outline"
                          style={{ fontSize: 11, padding: '3px 8px', minHeight: 26, borderColor: 'var(--color-divider)' }}
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
            backgroundColor: 'rgba(0,0,0,0.65)',
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
              backgroundColor: 'var(--color-card-bg, #FFFFFF)',
              color: 'var(--color-text-primary, #1D3B34)',
              borderRadius: 10,
              maxWidth: 440,
              width: '100%',
              padding: 18,
              boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
              border: '1px solid var(--color-divider, #D1D8D8)'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', margin: 0 }}>
                Submit New Trail
              </h3>
              <button
                type="button"
                onClick={() => setShowSubmitModal(false)}
                style={{ border: 'none', background: 'transparent', fontSize: 18, cursor: 'pointer', color: 'var(--color-text-secondary, #888)' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateSubmission} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 3 }}>
                  Trail Name
                </label>
                <input
                  type="text"
                  placeholder="e.g. Whiteface Ridge Connector"
                  value={subName}
                  onChange={(e) => setSubName(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13, boxSizing: 'border-box' }}
                  required
                />
              </div>

              <div style={{ display: 'flex', gap: 8 }}>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 3 }}>
                    Sport
                  </label>
                  <select
                    aria-label="Sport"
                    value={subSport}
                    onChange={(e) => setSubSport(e.target.value)}
                    style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13 }}
                  >
                    <option value="mtb">MTB</option>
                    <option value="trail_run">Trail Run</option>
                    <option value="gravel">Gravel</option>
                  </select>
                </div>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 3 }}>
                    Difficulty
                  </label>
                  <select
                    aria-label="Difficulty"
                    value={subDifficulty}
                    onChange={(e) => setSubDifficulty(e.target.value)}
                    style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13 }}
                  >
                    <option value="green">Green (Easy)</option>
                    <option value="blue">Blue (Moderate)</option>
                    <option value="black">Black (Difficult)</option>
                    <option value="double_black">Double Black</option>
                  </select>
                </div>
              </div>

              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 3 }}>
                  Description (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Hand-built singletrack along ravine"
                  value={subDesc}
                  onChange={(e) => setSubDesc(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13, boxSizing: 'border-box' }}
                />
              </div>

              <div>
                <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)', display: 'block', marginBottom: 3 }}>
                  Coordinates (lon, lat per line)
                </label>
                <textarea
                  rows={4}
                  value={subCoords}
                  onChange={(e) => setSubCoords(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 12, fontFamily: 'monospace', boxSizing: 'border-box' }}
                />
                <div style={{ fontSize: 11, color: 'var(--color-text-secondary, #42675E)', marginTop: 2 }}>
                  GPS trail vertices. At least 2 points required.
                </div>
              </div>

              {submissionError && (
                <div style={{ fontSize: 12, color: '#FF6B6B', backgroundColor: 'rgba(255, 107, 107, 0.1)', padding: '6px 8px', borderRadius: 4, border: '1px solid var(--color-divider)' }}>
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

export default ExplorePanel;
