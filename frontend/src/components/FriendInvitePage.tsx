import React, { useEffect, useState } from 'react';
import { acceptInvite, lookAtInvite } from '../services/api';
import { useAuth } from '../services/auth';
import { SignInCard } from './SignInCard';
import { LegalLinks } from './LegalLinks';

const muted: React.CSSProperties = { fontSize: 13, lineHeight: '18px', color: 'var(--color-text-secondary)' };

/** /friends/invite/<token>: sign in, then accept or decline. No one is added until this person accepts. */
export const FriendInvitePage: React.FC<{ token: string }> = ({ token }) => {
  const { user, ready } = useAuth();
  const [inviter, setInviter] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    document.title = 'A friend invite on Loam';
    const meta = document.createElement('meta');
    meta.name = 'robots';
    meta.content = 'noindex, nofollow';
    const ref = document.createElement('meta');
    ref.name = 'referrer';
    ref.content = 'no-referrer';
    document.head.append(meta, ref);
    return () => { meta.remove(); ref.remove(); };
  }, []);

  useEffect(() => {
    if (!user) return;
    let ignore = false;
    setProblem(null);
    lookAtInvite(token)
      .then((r) => { if (!ignore) setInviter(r.inviter_name); })
      .catch((e) => { if (!ignore) setProblem(e instanceof Error ? e.message : 'This invite doesn\'t work.'); });
    return () => { ignore = true; };
  }, [user, token]);

  const accept = async () => {
    setBusy(true);
    setProblem(null);
    try {
      setAccepted((await acceptInvite(token)).friend_name);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not accept the invite.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--color-panel-bg)', color: 'var(--color-text-primary)' }}>
      <header style={{ padding: '10px 16px', backgroundColor: 'var(--color-header-bg)' }}>
        <a href="/" aria-label="Loam home" style={{ display: 'inline-flex', alignItems: 'center', minHeight: 44 }}>
          <img src="/brand/loam-logo-horizontal-reversed.svg" alt="loam" style={{ height: 26, width: 'auto', display: 'block' }} />
        </a>
      </header>
      <main style={{ flex: 1, overflowY: 'auto', padding: '24px 16px', display: 'flex', justifyContent: 'center' }}>
        <div style={{ maxWidth: 440, width: '100%', display: 'flex', flexDirection: 'column', gap: 14 }}>
          <h1 style={{ fontSize: 22, lineHeight: '28px', fontWeight: 700 }}>
            {accepted ? 'You are now friends' : 'You have been invited to share routes'}
          </h1>

          {accepted ? (
            <>
              <p style={{ fontSize: 15, lineHeight: '22px' }}>
                You and {accepted} can now see the planned routes each of you shares with friends. Only routes are shared, never rides.
              </p>
              <a href="/" className="btn-primary" style={{ textDecoration: 'none', width: 'fit-content' }}>Open Loam</a>
            </>
          ) : !ready ? (
            <div role="status" style={muted}>Loading…</div>
          ) : !user ? (
            <>
              <p style={{ fontSize: 15, lineHeight: '22px' }}>
                Someone sent you a Loam invite. Sign in to see who it's from and decide whether to accept.
                Friends can see each other's planned routes that are shared with friends, and nothing else.
              </p>
              <SignInCard />
            </>
          ) : problem ? (
            <>
              <div role="alert" style={{ fontSize: 15, lineHeight: '22px' }}>{problem}</div>
              <a href="/" className="btn-secondary" style={{ textDecoration: 'none', width: 'fit-content' }}>Go to Loam</a>
            </>
          ) : inviter === null ? (
            <div role="status" style={muted}>Checking the invite…</div>
          ) : (
            <>
              <p style={{ fontSize: 15, lineHeight: '22px' }}>
                <strong>{inviter}</strong> invited you to be friends on Loam. If you accept, you can see the planned routes you each share with friends.
                Your rides, privacy zones and email stay private, and you can remove or block a friend any time.
              </p>
              <div style={{ display: 'flex', gap: 8 }}>
                <button type="button" className="btn-primary" disabled={busy} onClick={accept} style={{ flex: 1 }}>
                  {busy ? 'Accepting…' : 'Accept'}
                </button>
                <button type="button" className="btn-secondary" disabled={busy} onClick={() => window.location.assign('/')} style={{ flex: 1 }}>
                  Decline
                </button>
              </div>
            </>
          )}
          <div style={{ borderTop: '1px solid var(--color-divider)', paddingTop: 4 }}>
            <LegalLinks />
          </div>
        </div>
      </main>
    </div>
  );
};

export default FriendInvitePage;
