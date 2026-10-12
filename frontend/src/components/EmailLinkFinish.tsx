import React, { useEffect, useState } from 'react';
import { completeEmailLinkSignIn, isEmailLinkInUrl, storedEmailForSignIn } from '../services/auth';

/**
 * Finishes a passwordless email-link sign-in when the app opens from the link.
 * If the link was opened on another device (no stored email), it asks for the address.
 */
export const EmailLinkFinish: React.FC = () => {
  const [active] = useState(() => isEmailLinkInUrl());
  const [needsEmail, setNeedsEmail] = useState(false);
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const finish = async (address: string) => {
    setBusy(true);
    setError(null);
    try {
      await completeEmailLinkSignIn(address);
      setDone(true);
    } catch (e: any) {
      setError(e.message || 'Sign-in failed.');
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!active) return;
    const stored = storedEmailForSignIn();
    if (stored) finish(stored);
    else setNeedsEmail(true);
  }, [active]);

  if (!active || (done && !error)) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="email-link-title"
      style={{
        position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.65)', display: 'flex',
        alignItems: 'center', justifyContent: 'center', zIndex: 2000, padding: 16
      }}
    >
      <div
        style={{
          backgroundColor: 'var(--color-card-bg)', color: 'var(--color-text-primary)', borderRadius: 10,
          maxWidth: 400, width: '100%', padding: 20, border: '1px solid var(--color-divider)',
          display: 'flex', flexDirection: 'column', gap: 12
        }}
      >
        <h2 id="email-link-title" style={{ fontSize: 16, margin: 0 }}>Finish signing in</h2>
        {needsEmail && !done ? (
          <form
            onSubmit={(e) => { e.preventDefault(); finish(email); }}
            style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
          >
            <label htmlFor="email-link-address" style={{ fontSize: 13 }}>
              This link was opened on a different device. Enter the email you used to request it.
            </label>
            <input
              id="email-link-address"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={{
                padding: '8px 10px', borderRadius: 6, border: '1px solid var(--color-input-border)',
                backgroundColor: 'var(--color-input-bg)', color: 'var(--color-text-primary)', fontSize: 14
              }}
            />
            <button type="submit" className="btn-primary" disabled={busy}>
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        ) : (
          !error && <p style={{ margin: 0 }}>Signing you in…</p>
        )}
        {error && (
          <>
            <p role="alert" style={{ margin: 0, color: 'var(--color-blaze)' }}>{error}</p>
            <button type="button" className="btn-outline" onClick={() => { setDone(true); setError(null); }}>
              Close
            </button>
          </>
        )}
      </div>
    </div>
  );
};

export default EmailLinkFinish;
