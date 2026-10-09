import React, { useState, useEffect, useRef } from 'react';
import { DevConsolePanel } from './DevConsolePanel';
import { 
  getStoredUser, 
  renderGoogleButton, 
  loginWithRealCredentials, 
  logoutUser 
} from '../services/auth';
import type { AuthUser } from '../types';

interface DevToolsPageProps {
  onBack: () => void;
  isDarkMode?: boolean;
}

const AUTHORIZED_DEVELOPER_EMAILS = [
  'jjrpfister@gmail.com',
  'admin@loam.local'
];

export const DevToolsPage: React.FC<DevToolsPageProps> = ({ onBack, isDarkMode = false }) => {
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(() => getStoredUser());
  const [devKey, setDevKey] = useState<string>(() => localStorage.getItem('loam_dev_key') || '');
  const [inputKey, setInputKey] = useState<string>('');
  const [authError, setAuthError] = useState<string | null>(null);
  const [showManualLoginModal, setShowManualLoginModal] = useState(false);
  const [manualEmail, setManualEmail] = useState('');
  const [manualName, setManualName] = useState('');

  const googleBtnContainerRef = useRef<HTMLDivElement>(null);

  const isGoogleAuthed = Boolean(
    currentUser &&
    currentUser.email &&
    AUTHORIZED_DEVELOPER_EMAILS.includes(currentUser.email.toLowerCase().trim())
  );

  const isKeyAuthed = devKey.trim().length > 0;
  const isUnlocked = isGoogleAuthed || isKeyAuthed;

  // Render Google Identity Services button on mount
  useEffect(() => {
    if (!isUnlocked && googleBtnContainerRef.current) {
      renderGoogleButton(
        googleBtnContainerRef.current,
        (authedUser) => {
          setCurrentUser(authedUser);
          if (!AUTHORIZED_DEVELOPER_EMAILS.includes(authedUser.email.toLowerCase().trim())) {
            setAuthError(`Account ${authedUser.email} is not authorized for developer console.`);
          } else {
            setAuthError(null);
          }
        },
        (err) => console.warn('Google GIS Error on Dev page:', err)
      );
    }
  }, [isUnlocked]);

  const handleKeyUnlock = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputKey.trim()) {
      setAuthError('Please enter a valid developer access key.');
      return;
    }
    localStorage.setItem('loam_dev_key', inputKey.trim());
    setDevKey(inputKey.trim());
    setInputKey('');
    setAuthError(null);
  };

  const handleManualGoogleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualEmail.trim()) return;
    try {
      const user = await loginWithRealCredentials(manualEmail.trim(), manualName.trim() || 'Developer');
      setCurrentUser(user);
      setShowManualLoginModal(false);
      if (!AUTHORIZED_DEVELOPER_EMAILS.includes(user.email.toLowerCase().trim())) {
        setAuthError(`Account ${user.email} is not authorized for developer console.`);
      } else {
        setAuthError(null);
      }
    } catch (err: any) {
      setAuthError(err.message || 'Google authentication failed');
    }
  };

  const handleLock = () => {
    localStorage.removeItem('loam_dev_key');
    setDevKey('');
    if (isGoogleAuthed) {
      logoutUser();
      setCurrentUser(null);
    }
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
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {isGoogleAuthed && currentUser && (
                <span style={{ fontSize: 12, color: '#93C5FD' }}>
                  Signed in as <strong>{currentUser.email}</strong>
                </span>
              )}
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
            </div>
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
                margin: '40px auto 0 auto',
                display: 'flex',
                flexDirection: 'column',
                gap: 20
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: 28 }}>🔑</span>
                <div>
                  <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0, color: 'var(--color-text-primary, #1D3B34)' }}>
                    Developer Authentication
                  </h2>
                  <p style={{ fontSize: 13, color: 'var(--color-text-secondary, #42675E)', margin: '4px 0 0 0' }}>
                    Sign in with your authorized Google account or enter developer key.
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
                    fontSize: 13
                  }}
                >
                  {authError}
                </div>
              )}

              {/* 1. Google SSO Authentication Section */}
              <div
                style={{
                  backgroundColor: isDarkMode ? '#111F1C' : '#F8FAFC',
                  border: '1px solid var(--color-divider, #E2E8F0)',
                  borderRadius: 8,
                  padding: 16,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 12,
                  alignItems: 'center'
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text-primary, #1D3B34)' }}>
                  Sign in with Google SSO
                </div>
                <div ref={googleBtnContainerRef} style={{ minHeight: 40 }} />
                
                <button
                  type="button"
                  onClick={() => setShowManualLoginModal(true)}
                  className="btn-outline"
                  style={{
                    fontSize: 12,
                    padding: '6px 14px',
                    minHeight: 32,
                    borderColor: 'var(--color-divider, #CBD5E1)',
                    width: '100%'
                  }}
                >
                  Quick Sign In with Google Email
                </button>
              </div>

              {/* Divider */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ flex: 1, height: 1, backgroundColor: 'var(--color-divider, #D1D8D8)' }} />
                <span style={{ fontSize: 11, color: 'var(--color-text-secondary, #888)', fontWeight: 600 }}>OR DEV KEY</span>
                <div style={{ flex: 1, height: 1, backgroundColor: 'var(--color-divider, #D1D8D8)' }} />
              </div>

              {/* 2. Developer Key Form Section */}
              <form onSubmit={handleKeyUnlock} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div>
                  <label
                    htmlFor="dev-key-input"
                    style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--color-text-primary, #1D3B34)' }}
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
                  style={{ width: '100%', minHeight: 38, fontSize: 13, fontWeight: 700 }}
                >
                  Unlock with Key
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
                userEmail={currentUser?.email}
                idToken={currentUser?.idToken}
                isDarkMode={isDarkMode}
              />
            </div>
          )}
        </div>
      </main>

      {/* Quick Google Sign In Modal */}
      {showManualLoginModal && (
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
          onClick={() => setShowManualLoginModal(false)}
        >
          <div
            style={{
              backgroundColor: isDarkMode ? '#162823' : '#FFFFFF',
              color: isDarkMode ? '#E7ECEC' : '#1D3B34',
              borderRadius: 10,
              maxWidth: 400,
              width: '100%',
              padding: 24,
              boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
              display: 'flex',
              flexDirection: 'column',
              gap: 14,
              border: '1px solid var(--color-divider, #D1D8D8)'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>Google Developer SSO</h3>
            <p style={{ fontSize: 12, color: 'var(--color-text-secondary, #42675E)', margin: 0 }}>
              Enter your authorized Google developer email address:
            </p>
            <form onSubmit={handleManualGoogleAuth} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <input
                type="email"
                placeholder="Google Email (e.g. jjrpfister@gmail.com)"
                value={manualEmail}
                onChange={(e) => setManualEmail(e.target.value)}
                required
                style={{ padding: '8px 10px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13 }}
              />
              <input
                type="text"
                placeholder="Name"
                value={manualName}
                onChange={(e) => setManualName(e.target.value)}
                style={{ padding: '8px 10px', borderRadius: 6, border: '1px solid var(--color-input-border, #D1D8D8)', backgroundColor: 'var(--color-input-bg, #FFFFFF)', color: 'var(--color-text-primary, #1D3B34)', fontSize: 13 }}
              />
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
                <button
                  type="button"
                  onClick={() => setShowManualLoginModal(false)}
                  className="btn-outline"
                  style={{ fontSize: 12, minHeight: 32 }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn-primary"
                  style={{ fontSize: 12, minHeight: 32 }}
                >
                  Authorize Session
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default DevToolsPage;
