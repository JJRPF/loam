import React, { useEffect, useState } from 'react';
import { API_BASE, authedFetch } from '../services/api';
import { useAuth } from '../services/auth';

/** GET /api/version on staging: the pull request this server is showing. */
interface VersionInfo {
  env?: string;
  pr?: number | null;
  pr_title?: string | null;
  pr_url?: string | null;
  ref?: string | null;
  sha?: string | null;
  short_sha?: string | null;
  commits_ahead?: number | null;
}

const IS_STAGING = import.meta.env.VITE_APP_ENV === 'staging';
const HEIGHT = 24;

/** The commit's page, derived from the PR link (https://github.com/<owner>/<repo>/pull/N). */
function commitUrl(info: VersionInfo): string | null {
  const repo = info.pr_url?.replace(/\/pull\/\d+.*$/, '');
  return repo && info.sha && /^[0-9a-f]{40}$/.test(info.sha) ? `${repo}/commit/${info.sha}` : null;
}

function safeLink(url?: string | null): string | null {
  return url && /^https:\/\/github\.com\//.test(url) ? url : null;
}

/** A thin strip on staging for signed-in users only: signed out, the page shows nothing about the deploy. */
export const StagingBanner: React.FC = () => {
  const { user } = useAuth();
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const signedIn = !!user;

  useEffect(() => {
    if (!IS_STAGING || !signedIn) return;
    let cancelled = false;
    authedFetch(`${API_BASE}/api/version`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (!cancelled) setInfo(j ?? {}); })
      .catch(() => { if (!cancelled) setInfo({}); });
    return () => { cancelled = true; };
  }, [signedIn]);

  // signing out hides the banner at once; the next sign-in fetches again
  const show = IS_STAGING && signedIn && info !== null;
  useEffect(() => {
    document.documentElement.style.setProperty('--staging-banner-h', show ? `${HEIGHT}px` : '0px');
    return () => document.documentElement.style.setProperty('--staging-banner-h', '0px');
  }, [show]);
  if (!show || !info) return null;

  const pr = safeLink(info.pr_url);
  const commit = safeLink(commitUrl(info));
  return (
    <div
      role="status"
      data-testid="staging-banner"
      style={{ position: 'fixed', top: 0, left: 0, right: 0, height: HEIGHT, zIndex: 3500, background: '#8A5A00', color: '#FFFFFF', fontSize: 12, lineHeight: `${HEIGHT}px`, padding: '0 12px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
    >
      <strong>STAGING</strong>
      {info.pr ? (
        <>
          {' · '}
          {pr ? <a href={pr} style={{ color: 'inherit' }}>PR #{info.pr}</a> : `PR #${info.pr}`}
          {info.pr_title ? ` ${info.pr_title}` : ''}
        </>
      ) : ' · main'}
      {info.ref ? ` · ${info.ref}` : ''}
      {info.short_sha ? <>{' · '}{commit ? <a href={commit} style={{ color: 'inherit' }}>{info.short_sha}</a> : info.short_sha}</> : ''}
      {typeof info.commits_ahead === 'number' ? ` · ${info.commits_ahead} ahead of main` : ''}
      {' · test data, not the real app'}
    </div>
  );
};

export default StagingBanner;
