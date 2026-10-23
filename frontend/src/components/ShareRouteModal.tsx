import React, { useEffect, useRef, useState } from 'react';
import type { SavedRoute } from '../types';
import { previewShare, revokeSavedRouteShare, shareSavedRoute } from '../services/api';
import { copyText } from '../services/clipboard';

type Visibility = NonNullable<SavedRoute['visibility']>;

interface Props {
  route: SavedRoute;
  onClose: () => void;
  onChanged: (visibility: Visibility) => void;
}

const OPTIONS: { id: Visibility; label: string; help: string }[] = [
  { id: 'link', label: 'Anyone with the link', help: 'Works without an account. Anyone you send the link to can open it, and so can anyone they pass it to.' },
  { id: 'friends', label: 'My friends', help: 'Only people you have accepted as friends in Loam can see it.' },
  { id: 'private', label: 'Private', help: 'Only you. This is the default for every route.' },
];

const cardText: React.CSSProperties = { fontSize: 13, lineHeight: '18px', color: 'var(--color-text-secondary)' };

/** Share dialog for one saved route: link, friends or private, with the privacy-zone notice (rule 3). */
export const ShareRouteModal: React.FC<Props> = ({ route, onClose, onChanged }) => {
  const current: Visibility = route.visibility ?? 'private';
  const [choice, setChoice] = useState<Visibility>(current);
  const [zoneOverlap, setZoneOverlap] = useState<boolean | null>(null);
  const [fullRoute, setFullRoute] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    let ignore = false;
    previewShare(route.id)
      .then((p) => { if (!ignore) setZoneOverlap(p.zone_overlap); })
      .catch(() => { if (!ignore) setZoneOverlap(null); });
    return () => { ignore = true; };
  }, [route.id]);

  const apply = async () => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      if (choice === 'private') {
        await revokeSavedRouteShare(route.id);
        setLink(null);
        setDone('This route is private again. Any link or friend access has stopped working.');
        onChanged('private');
      } else {
        const out = await shareSavedRoute(route.id, choice, !fullRoute);
        onChanged(choice);
        if (choice === 'link' && out.url) {
          setLink(out.url);
          setDone(out.trimmed ? 'Link ready. The parts of the route inside your privacy zones were left out.' : 'Link ready.');
        } else {
          setLink(null);
          setDone(out.trimmed
            ? 'Shared with your friends. The parts of the route inside your privacy zones were left out.'
            : 'Shared with your friends.');
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  };

  const showZoneNotice = zoneOverlap === true && choice !== 'private';
  const nothingToDo = choice === 'private' && current === 'private';
  const actionLabel = choice === 'private'
    ? 'Stop sharing'
    : choice === 'link'
      ? (current === 'link' ? 'Make a new link' : 'Create link')
      : (current === 'friends' ? 'Share again' : 'Share with friends');

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="share-dialog-title"
      style={{ position: 'fixed', inset: 0, zIndex: 2000, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{ background: 'var(--color-card-bg)', color: 'var(--color-text-primary)', border: '1px solid var(--color-divider)', borderRadius: 12, padding: 16, maxWidth: 440, width: '100%', maxHeight: '90vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h2 id="share-dialog-title" ref={headingRef} tabIndex={-1} style={{ fontSize: 16, fontWeight: 700, outline: 'none' }}>
          Share "{route.name}"
        </h2>
        <p style={cardText}>
          Only the planned route is shared: its line, distance and surface mix, plus the sharing name you choose in the You tab.
          Your rides, uploads, privacy zones and email are never part of it.
        </p>

        <fieldset style={{ border: 'none', display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
          <legend style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>Who can see it</legend>
          {OPTIONS.map((o) => (
            <label key={o.id} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '8px 10px', minHeight: 44, borderRadius: 8, border: `1px solid ${choice === o.id ? 'var(--color-blaze)' : 'var(--color-divider)'}`, cursor: 'pointer' }}>
              <input
                type="radio"
                name="share-visibility"
                value={o.id}
                checked={choice === o.id}
                onChange={() => { setChoice(o.id); setDone(null); setError(null); }}
                style={{ marginTop: 3, width: 18, height: 18, accentColor: 'var(--color-blaze)' }}
              />
              <span>
                <span style={{ display: 'block', fontSize: 14, fontWeight: 700 }}>
                  {o.label}{current === o.id ? ' (current)' : ''}
                </span>
                <span style={cardText}>{o.help}</span>
              </span>
            </label>
          ))}
        </fieldset>

        {showZoneNotice && (
          <div role="note" style={{ border: '1px solid var(--color-blaze)', borderRadius: 8, padding: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontSize: 13, lineHeight: '18px' }}>
              This route starts or ends inside one of your privacy zones. By default the parts inside the zone are left out of what you share, so nobody learns where you live or work.
            </div>
            <label style={{ display: 'flex', gap: 10, alignItems: 'center', minHeight: 44, fontSize: 13, cursor: 'pointer' }}>
              <input type="checkbox" checked={fullRoute} onChange={(e) => setFullRoute(e.target.checked)} style={{ width: 18, height: 18, accentColor: 'var(--color-blaze)' }} />
              Share the full route, including the part inside my privacy zone
            </label>
          </div>
        )}

        {choice === 'link' && current === 'link' && !link && (
          <p style={cardText}>A link is active. For safety Loam does not keep it, so it can't be shown again. Making a new link stops the old one from working.</p>
        )}

        {link && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <label htmlFor="share-link" style={{ fontSize: 12, fontWeight: 700 }}>Link</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input id="share-link" type="text" readOnly value={link} onFocus={(e) => e.currentTarget.select()} style={{ flex: 1, minWidth: 0, padding: '8px 10px', fontSize: 13, minHeight: 44 }} />
              <button type="button" className="btn-secondary" onClick={async () => { setCopied(await copyText(link)); }}>
                {copied ? 'Copied' : 'Copy link'}
              </button>
            </div>
            <p style={cardText}>Anyone with this link can see the route. Choose "Private" here to stop it working.</p>
          </div>
        )}

        {done && <div role="status" style={{ fontSize: 13, color: 'var(--color-lichen)' }}>{done}</div>}
        {error && <div role="alert" style={{ fontSize: 13, color: 'var(--color-blaze-text)' }}>{error}</div>}

        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" className="btn-secondary" onClick={onClose} style={{ flex: 1 }}>Close</button>
          <button type="button" className="btn-primary" onClick={apply} disabled={busy || nothingToDo} style={{ flex: 1, minHeight: 44, padding: '8px 12px' }}>
            {busy ? 'Working…' : actionLabel}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ShareRouteModal;
