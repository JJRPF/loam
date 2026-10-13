import React, { useEffect, useState } from 'react';
import { DevConsolePanel } from './DevConsolePanel';
import { SignInCard } from './SignInCard';
import { getAuthMe } from '../services/api';
import { signOut, useAuth } from '../services/auth';

interface DevToolsPageProps {
  onBack: () => void;
  isDarkMode?: boolean;
}

/** Admin-only operations page. The server decides who is an admin (ADMIN_EMAILS). */
export const DevToolsPage: React.FC<DevToolsPageProps> = ({ onBack, isDarkMode = true }) => {
  const { user, ready } = useAuth();
  const [adminState, setAdminState] = useState<'unknown' | 'admin' | 'denied'>('unknown');

  useEffect(() => {
    let ignore = false;
    if (!user) {
      setAdminState('unknown');
      return;
    }
    getAuthMe()
      .then((me) => { if (!ignore) setAdminState(me.is_admin ? 'admin' : 'denied'); })
      .catch(() => { if (!ignore) setAdminState('denied'); });
    return () => { ignore = true; };
  }, [user]);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        width: '100vw',
        height: '100vh',
        backgroundColor: 'var(--color-bg, #0F1A17)',
        color: 'var(--color-text-primary, #E7ECEC)',
        overflow: 'hidden'
      }}
    >
      <header
        style={{
          padding: '12px 16px',
          backgroundColor: 'var(--color-header-bg, #142420)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          borderBottom: '1px solid var(--color-divider)'
        }}
      >
        <button type="button" onClick={onBack} className="btn-outline" style={{ fontSize: 13, minHeight: 34 }}>
          &larr; Back to Loam
        </button>
        <h1 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>Operations</h1>
        {user ? (
          <button type="button" onClick={() => signOut()} className="btn-outline" style={{ fontSize: 12, minHeight: 30 }}>
            Sign out
          </button>
        ) : <span />}
      </header>

      <main style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'flex', justifyContent: 'center' }}>
        <div style={{ width: '100%', maxWidth: 900 }}>
          {!ready ? (
            <p>Loading…</p>
          ) : !user ? (
            <div style={{ maxWidth: 420, margin: '24px auto' }}>
              <p style={{ fontSize: 14 }}>Sign in with an admin account.</p>
              <SignInCard />
            </div>
          ) : adminState === 'unknown' ? (
            <p>Checking access…</p>
          ) : adminState === 'denied' ? (
            <p role="alert" style={{ fontSize: 14 }}>
              {user.email} is not an admin.
            </p>
          ) : (
            <DevConsolePanel userEmail={user.email} isDarkMode={isDarkMode} />
          )}
        </div>
      </main>
    </div>
  );
};

export default DevToolsPage;
