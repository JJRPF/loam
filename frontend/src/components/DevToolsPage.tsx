import React, { useState } from 'react';
import { DevConsolePanel } from './DevConsolePanel';

interface DevToolsPageProps {
  onBack: () => void;
  isDarkMode?: boolean;
}

export const DevToolsPage: React.FC<DevToolsPageProps> = ({ onBack, isDarkMode = false }) => {
  const [devKey, setDevKey] = useState<string>(() => localStorage.getItem('loam_dev_key') || '');
  const [inputKey, setInputKey] = useState<string>('');
  const [authError, setAuthError] = useState<string | null>(null);

  const isUnlocked = devKey.trim().length > 0;

  const handleUnlock = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputKey.trim()) {
      setAuthError('Please enter a valid developer key.');
      return;
    }
    localStorage.setItem('loam_dev_key', inputKey.trim());
    setDevKey(inputKey.trim());
    setInputKey('');
    setAuthError(null);
  };

  const handleLock = () => {
    localStorage.removeItem('loam_dev_key');
    setDevKey('');
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        width: '100vw',
        height: '100vh',
        backgroundColor: isDarkMode ? '#0F1A17' : '#F4F7F7',
        color: isDarkMode ? '#E7ECEC' : '#1D3B34',
        overflow: 'hidden'
      }}
    >
      {/* Top Header */}
      <header
        style={{
          padding: '12px 24px',
          backgroundColor: isDarkMode ? '#142420' : '#1D3B34',
          color: '#FFFFFF',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid rgba(255,255,255,0.1)',
          zIndex: 10
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <button
            type="button"
            onClick={onBack}
            className="btn-outline"
            style={{
              color: '#FFFFFF',
              borderColor: 'rgba(255,255,255,0.3)',
              backgroundColor: 'rgba(255,255,255,0.1)',
              fontSize: 13,
              padding: '6px 14px',
              minHeight: 34,
              borderRadius: 6
            }}
          >
            &larr; Back to Loam
          </button>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 20 }}>🛠️</span>
            <div>
              <h1 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>
                Developer Tools & Operations
              </h1>
              <div style={{ fontSize: 11, color: '#A0B2B0' }}>
                System Telemetry • Cache Controls • Trail Heat Computation
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {isUnlocked && (
            <button
              type="button"
              onClick={handleLock}
              className="btn-outline"
              style={{
                color: '#FFFFFF',
                borderColor: 'rgba(255,255,255,0.3)',
                fontSize: 12,
                padding: '4px 10px',
                minHeight: 30
              }}
            >
              🔒 Lock Console
            </button>
          )}
        </div>
      </header>

      {/* Main Content Area */}
      <main style={{ flex: 1, overflowY: 'auto', padding: '24px', display: 'flex', justifyContent: 'center' }}>
        <div style={{ width: '100%', maxWidth: 900 }}>
          {!isUnlocked ? (
            <div
              style={{
                backgroundColor: isDarkMode ? '#162823' : '#FFFFFF',
                borderRadius: 10,
                border: '1px solid var(--color-divider, #D1D8D8)',
                padding: '32px 28px',
                boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
                maxWidth: 480,
                margin: '40px auto 0 auto'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                <span style={{ fontSize: 28 }}>🔑</span>
                <div>
                  <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0, color: 'var(--color-text-primary, #1D3B34)' }}>
                    Developer Authentication
                  </h2>
                  <p style={{ fontSize: 13, color: 'var(--color-text-secondary, #42675E)', margin: '4px 0 0 0' }}>
                    Access to system telemetry, transient caches, and heat recalculations.
                  </p>
                </div>
              </div>

              {authError && (
                <div
                  style={{
                    backgroundColor: '#FEE2E2',
                    color: '#B91C1C',
                    padding: '8px 12px',
                    borderRadius: 6,
                    fontSize: 13,
                    marginBottom: 16
                  }}
                >
                  {authError}
                </div>
              )}

              <form onSubmit={handleUnlock} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div>
                  <label
                    htmlFor="dev-key-input"
                    style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6, color: 'var(--color-text-primary, #1D3B34)' }}
                  >
                    Developer Access Key
                  </label>
                  <input
                    id="dev-key-input"
                    type="password"
                    placeholder="Enter Developer Key..."
                    value={inputKey}
                    onChange={(e) => setInputKey(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      borderRadius: 6,
                      border: '1px solid var(--color-input-border, #D1D8D8)',
                      backgroundColor: 'var(--color-input-bg, #FFFFFF)',
                      color: 'var(--color-text-primary, #1D3B34)',
                      fontSize: 14,
                      boxSizing: 'border-box'
                    }}
                  />
                </div>

                <button
                  type="submit"
                  className="btn-primary"
                  style={{ width: '100%', minHeight: 40, fontSize: 14, fontWeight: 700 }}
                >
                  Unlock Developer Tools
                </button>
              </form>
            </div>
          ) : (
            <div
              style={{
                backgroundColor: isDarkMode ? '#162823' : '#FFFFFF',
                borderRadius: 10,
                border: '1px solid var(--color-divider, #D1D8D8)',
                padding: '24px',
                boxShadow: '0 4px 16px rgba(0,0,0,0.08)'
              }}
            >
              <DevConsolePanel
                devKey={devKey}
                isDarkMode={isDarkMode}
              />
            </div>
          )}
        </div>
      </main>
    </div>
  );
};

export default DevToolsPage;
