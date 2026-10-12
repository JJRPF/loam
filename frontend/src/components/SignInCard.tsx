import React, { useEffect, useState } from 'react';
import {
  emailLinkCooldownRemaining,
  isAuthConfigured,
  sendEmailLink,
  signInWithGoogle,
  signOut,
  useAuth
} from '../services/auth';

const cardStyle: React.CSSProperties = {
  backgroundColor: 'var(--color-card-bg)',
  borderRadius: 8,
  border: '1px solid var(--color-divider)',
  padding: 14
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 10px',
  borderRadius: 6,
  border: '1px solid var(--color-input-border)',
  backgroundColor: 'var(--color-input-bg)',
  color: 'var(--color-text-primary)',
  fontSize: 14,
  boxSizing: 'border-box'
};

/** Sign-in for the You panel: Google, or a passwordless email link. No passwords. */
export const SignInCard: React.FC = () => {
  const { user, ready, cachedProfile } = useAuth();
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState<'google' | 'email' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [linkSentTo, setLinkSentTo] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(() => emailLinkCooldownRemaining());

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = window.setInterval(() => setCooldown(emailLinkCooldownRemaining()), 1000);
    return () => window.clearInterval(t);
  }, [cooldown]);

  const shown = user || (!ready ? cachedProfile : null);

  if (shown) {
    const initials = shown.displayName.split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase() || 'U';
    return (
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          {shown.photoURL ? (
            <img src={shown.photoURL} alt="" width={44} height={44} style={{ borderRadius: '50%' }} referrerPolicy="no-referrer" />
          ) : (
            <div
              aria-hidden="true"
              style={{
                width: 44, height: 44, borderRadius: '50%', backgroundColor: 'var(--color-header-bg)',
                color: 'var(--color-header-text)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 18, fontWeight: 700
              }}
            >
              {initials}
            </div>
          )}
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text-primary)' }}>{shown.displayName}</div>
            <div style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>{shown.email}</div>
          </div>
        </div>
        <button type="button" onClick={() => signOut()} className="btn-outline" style={{ width: '100%', fontSize: 13, minHeight: 36 }} disabled={!user}>
          Sign out
        </button>
      </div>
    );
  }

  if (!isAuthConfigured()) {
    return (
      <div style={cardStyle}>
        <p style={{ fontSize: 14, color: 'var(--color-text-primary)', margin: 0 }}>
          Sign-in isn't set up on this server yet. You can still plan and export routes.
        </p>
      </div>
    );
  }

  const handleGoogle = async () => {
    setError(null);
    setBusy('google');
    try {
      await signInWithGoogle();
    } catch (e: any) {
      setError(e.message || 'Google sign-in failed.');
    } finally {
      setBusy(null);
    }
  };

  const handleEmail = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy('email');
    try {
      await sendEmailLink(email);
      setLinkSentTo(email.trim());
      setCooldown(emailLinkCooldownRemaining());
    } catch (err: any) {
      setError(err.message || 'Could not send the sign-in link.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ ...cardStyle, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <p style={{ fontSize: 14, color: 'var(--color-text-primary)', margin: 0 }}>
        Sign in to save routes, upload rides and keep your settings across devices.
      </p>
      <button type="button" onClick={handleGoogle} className="btn-primary" style={{ width: '100%' }} disabled={busy !== null}>
        {busy === 'google' ? 'Opening Google…' : 'Continue with Google'}
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{ flex: 1, height: 1, backgroundColor: 'var(--color-divider)' }} />
        <span style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>or</span>
        <div style={{ flex: 1, height: 1, backgroundColor: 'var(--color-divider)' }} />
      </div>

      {linkSentTo ? (
        <div role="status" style={{ fontSize: 13, color: 'var(--color-text-primary)' }}>
          Check your inbox. The link signs you in on this device.
          <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 4 }}>Sent to {linkSentTo}.</div>
          <button
            type="button"
            className="btn-outline"
            style={{ marginTop: 8, fontSize: 12, minHeight: 30 }}
            onClick={() => setLinkSentTo(null)}
            disabled={cooldown > 0}
          >
            {cooldown > 0 ? `Send again in ${Math.ceil(cooldown / 1000)} s` : 'Use a different email'}
          </button>
        </div>
      ) : (
        <form onSubmit={handleEmail} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <label htmlFor="signin-email" style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text-primary)' }}>
            Email
          </label>
          <input
            id="signin-email"
            type="email"
            autoComplete="email"
            inputMode="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={inputStyle}
          />
          <button type="submit" className="btn-secondary" disabled={busy !== null || cooldown > 0} style={{ width: '100%' }}>
            {busy === 'email' ? 'Sending…' : cooldown > 0 ? `Send again in ${Math.ceil(cooldown / 1000)} s` : 'Email me a sign-in link'}
          </button>
        </form>
      )}

      {error && (
        <div role="alert" style={{ fontSize: 13, color: 'var(--color-blaze)' }}>
          {error}
        </div>
      )}
    </div>
  );
};

export default SignInCard;
