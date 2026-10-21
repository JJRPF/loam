import React, { useCallback, useEffect, useState } from 'react';
import {
  blockFriend, cancelFriendInvite, createFriendInvite, getShareProfile, listFriendInvites, listFriends, listMyShares,
  removeFriend, revokeSavedRouteShare, saveShareDisplayName, unblockFriend,
  type FriendEntry, type InviteEntry, type ShareInfo
} from '../services/api';
import { copyText } from '../services/clipboard';

const card: React.CSSProperties = { backgroundColor: 'var(--color-card-bg)', borderRadius: 8, border: '1px solid var(--color-divider)', padding: 14, display: 'flex', flexDirection: 'column', gap: 12 };
const muted: React.CSSProperties = { fontSize: 12, lineHeight: '17px', color: 'var(--color-text-secondary)' };
const rowStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, padding: '6px 0', borderTop: '1px solid var(--color-divider)', fontSize: 13 };
const small: React.CSSProperties = { fontSize: 12, minHeight: 44, padding: '2px 10px' };

/** Friends and sharing in the You panel: sharing name, invites, friends, blocks and what is shared right now. */
export const FriendsSection: React.FC = () => {
  const [defaultName, setDefaultName] = useState('A Loam rider');
  const [name, setName] = useState('');
  const [savedName, setSavedName] = useState<string | null>(null);
  const [friends, setFriends] = useState<FriendEntry[]>([]);
  const [blocked, setBlocked] = useState<FriendEntry[]>([]);
  const [invites, setInvites] = useState<InviteEntry[]>([]);
  const [shares, setShares] = useState<ShareInfo[]>([]);
  const [newInvite, setNewInvite] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : 'Something went wrong.');

  const refresh = useCallback(async () => {
    try {
      const [profile, fr, inv, sh] = await Promise.all([getShareProfile(), listFriends(), listFriendInvites(), listMyShares()]);
      setDefaultName(profile.default_share_display_name);
      setSavedName(profile.share_display_name);
      setName(profile.share_display_name ?? '');
      setFriends(fr.friends);
      setBlocked(fr.blocked);
      setInvites(inv);
      setShares(sh);
    } catch (e) {
      fail(e);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const act = async (fn: () => Promise<unknown>, done?: string) => {
    setError(null);
    setMessage(null);
    try {
      await fn();
      if (done) setMessage(done);
      await refresh();
    } catch (e) {
      fail(e);
    }
  };

  return (
    <section aria-labelledby="friends-title" style={card}>
      <h3 id="friends-title" style={{ fontSize: 14, fontWeight: 700, margin: 0 }}>Friends and sharing</h3>
      <p style={muted}>
        You can share planned routes with a link or with friends. Your rides, uploads, privacy zones and email are never shared.
        Friends join only through an invite link you send, so nobody can search for you.
      </p>

      <form
        onSubmit={(e) => { e.preventDefault(); void act(async () => { await saveShareDisplayName(name); }, 'Sharing name saved.'); }}
        style={{ display: 'flex', flexDirection: 'column', gap: 6 }}
      >
        <label htmlFor="share-name" style={{ fontSize: 12, fontWeight: 700 }}>Name shown with routes you share</label>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            id="share-name"
            type="text"
            value={name}
            maxLength={40}
            placeholder={defaultName}
            onChange={(e) => setName(e.target.value)}
            style={{ flex: 1, minWidth: 0, padding: '8px 10px', fontSize: 14, minHeight: 44 }}
          />
          <button type="submit" className="btn-secondary" disabled={name.trim() === (savedName ?? '')}>Save</button>
        </div>
        <span style={muted}>Leave it empty to be shown as "{defaultName}". Use a nickname, not your real name or email.</span>
      </form>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ fontSize: 13, fontWeight: 700 }}>Invite a friend</div>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => void act(async () => { const inv = await createFriendInvite(); setNewInvite(inv.url); setCopied(false); })}
        >
          Make an invite link
        </button>
        {newInvite && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <label htmlFor="invite-link" style={{ fontSize: 12, fontWeight: 700 }}>Invite link (works once, for 7 days)</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input id="invite-link" type="text" readOnly value={newInvite} onFocus={(e) => e.currentTarget.select()} style={{ flex: 1, minWidth: 0, padding: '8px 10px', fontSize: 13, minHeight: 44 }} />
              <button type="button" className="btn-secondary" onClick={async () => setCopied(await copyText(newInvite))}>{copied ? 'Copied' : 'Copy'}</button>
            </div>
            <span style={muted}>Loam can't show this link again, so copy it now. Send it only to the person you want as a friend.</span>
          </div>
        )}
      </div>

      {invites.length > 0 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 700 }}>Waiting for a reply</div>
          {invites.map((i, n) => (
            <div key={i.id} style={rowStyle}>
              <span>Invite {n + 1}, expires {new Date(i.expires_at).toLocaleDateString()}</span>
              <button type="button" className="btn-outline" style={small} onClick={() => void act(() => cancelFriendInvite(i.id), 'Invite cancelled.')}>Cancel</button>
            </div>
          ))}
        </div>
      )}

      <div>
        <div style={{ fontSize: 13, fontWeight: 700 }}>Friends</div>
        {friends.length === 0 && <div style={muted}>No friends yet.</div>}
        {friends.map((f) => (
          <div key={f.id} style={rowStyle}>
            <span style={{ overflowWrap: 'anywhere' }}>{f.name} <span style={muted}>since {new Date(f.since).toLocaleDateString()}</span></span>
            <span style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
              <button type="button" className="btn-outline" style={small}
                onClick={() => { if (confirm(`Remove ${f.name} as a friend? You will stop seeing each other's shared routes.`)) void act(() => removeFriend(f.id), 'Friend removed.'); }}>
                Remove
              </button>
              <button type="button" className="btn-outline" style={small}
                onClick={() => { if (confirm(`Block ${f.name}? They are removed as a friend and can't send you an invite you could accept.`)) void act(() => blockFriend(f.id), 'Blocked.'); }}>
                Block
              </button>
            </span>
          </div>
        ))}
      </div>

      {blocked.length > 0 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 700 }}>Blocked</div>
          {blocked.map((b) => (
            <div key={b.id} style={rowStyle}>
              <span>{b.name}</span>
              <button type="button" className="btn-outline" style={small} onClick={() => void act(() => unblockFriend(b.id), 'Unblocked.')}>Unblock</button>
            </div>
          ))}
        </div>
      )}

      <div>
        <div style={{ fontSize: 13, fontWeight: 700 }}>Routes you are sharing</div>
        {shares.length === 0 && <div style={muted}>None. Open the Saved tab and tap Share on a route.</div>}
        {shares.map((s) => (
          <div key={s.route_id} style={rowStyle}>
            <span style={{ overflowWrap: 'anywhere' }}>
              {s.name}{' '}
              <span style={muted}>{s.mode === 'link' ? `link, opened ${s.view_count} time${s.view_count === 1 ? '' : 's'}` : 'friends'}</span>
            </span>
            <button type="button" className="btn-outline" style={small} onClick={() => void act(() => revokeSavedRouteShare(s.route_id), 'Stopped sharing.')}>Stop sharing</button>
          </div>
        ))}
      </div>

      {message && <div role="status" style={{ fontSize: 13, color: 'var(--color-lichen)' }}>{message}</div>}
      {error && <div role="alert" style={{ fontSize: 13, color: 'var(--color-blaze-text)' }}>{error}</div>}
    </section>
  );
};

export default FriendsSection;
