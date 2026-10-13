import { useSyncExternalStore } from 'react';
import {
  GoogleAuthProvider,
  isSignInWithEmailLink,
  onAuthStateChanged,
  sendSignInLinkToEmail,
  signInWithEmailLink,
  signInWithPopup,
  signInWithRedirect,
  getRedirectResult,
  signOut as firebaseSignOut,
  type User
} from 'firebase/auth';
import type { AuthUser } from '../types';
import { firebaseConfigured, getFirebaseAuth } from './firebase';

// Firebase's onAuthStateChanged is the source of truth. The localStorage copy below only
// pre-renders the avatar before Firebase restores the session; it never authorizes anything.
const PROFILE_CACHE_KEY = 'loam_profile_cache_v2';
export const EMAIL_FOR_SIGNIN_KEY = 'loam_email_for_signin';
const LAST_LINK_SENT_KEY = 'loam_email_link_sent_at';
export const EMAIL_LINK_COOLDOWN_MS = 60_000;

export interface AuthState {
  user: AuthUser | null;
  ready: boolean; // Firebase has reported the initial auth state
  cachedProfile: AuthUser | null;
}

function readCachedProfile(): AuthUser | null {
  try {
    const raw = localStorage.getItem(PROFILE_CACHE_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

function writeCachedProfile(user: AuthUser | null) {
  try {
    if (user) localStorage.setItem(PROFILE_CACHE_KEY, JSON.stringify(user));
    else localStorage.removeItem(PROFILE_CACHE_KEY);
  } catch {
    // storage unavailable (private mode); the cache is only cosmetic
  }
}

let state: AuthState = { user: null, ready: !firebaseConfigured, cachedProfile: readCachedProfile() };
const listeners = new Set<() => void>();
let firebaseUser: User | null = null;

function setState(next: Partial<AuthState>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

function toAuthUser(u: User): AuthUser {
  return {
    id: u.uid,
    email: u.email || '',
    displayName: u.displayName || (u.email ? u.email.split('@')[0] : 'Rider'),
    photoURL: u.photoURL || undefined
  };
}

let started = false;
function start() {
  if (started) return;
  started = true;
  const auth = getFirebaseAuth();
  if (!auth) return;
  onAuthStateChanged(auth, (u) => {
    firebaseUser = u;
    const user = u ? toAuthUser(u) : null;
    writeCachedProfile(user);
    setState({ user, ready: true, cachedProfile: user });
  });
  getRedirectResult(auth).catch((e) => console.warn('Sign-in redirect:', e));
}

function subscribe(listener: () => void) {
  start();
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useAuth(): AuthState {
  return useSyncExternalStore(subscribe, () => state, () => state);
}

export function getAuthState(): AuthState {
  start();
  return state;
}

export function isAuthConfigured(): boolean {
  return firebaseConfigured;
}

/** A fresh Firebase ID token for the signed-in user, or null when signed out. */
export async function getIdToken(forceRefresh = false): Promise<string | null> {
  start();
  if (!firebaseUser) return null;
  return firebaseUser.getIdToken(forceRefresh);
}

function isIosStandalone(): boolean {
  const nav = window.navigator as Navigator & { standalone?: boolean };
  return Boolean(nav.standalone) || window.matchMedia?.('(display-mode: standalone)').matches;
}

export async function signInWithGoogle(): Promise<void> {
  const auth = getFirebaseAuth();
  if (!auth) throw new Error('Sign-in is not configured on this server.');
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: 'select_account' });
  if (isIosStandalone()) {
    await signInWithRedirect(auth, provider);
    return;
  }
  try {
    await signInWithPopup(auth, provider);
  } catch (e: any) {
    const code = e?.code || '';
    if (code === 'auth/popup-blocked' || code === 'auth/operation-not-supported-in-this-environment') {
      await signInWithRedirect(auth, provider);
      return;
    }
    if (code === 'auth/popup-closed-by-user' || code === 'auth/cancelled-popup-request') return;
    throw new Error(friendlyAuthError(e));
  }
}

export function emailLinkCooldownRemaining(): number {
  try {
    const last = Number(localStorage.getItem(LAST_LINK_SENT_KEY) || 0);
    return Math.max(0, last + EMAIL_LINK_COOLDOWN_MS - Date.now());
  } catch {
    return 0;
  }
}

export async function sendEmailLink(email: string): Promise<void> {
  const auth = getFirebaseAuth();
  if (!auth) throw new Error('Sign-in is not configured on this server.');
  const clean = email.trim();
  if (!clean) throw new Error('Enter your email address.');
  const wait = emailLinkCooldownRemaining();
  if (wait > 0) throw new Error(`Please wait ${Math.ceil(wait / 1000)} s before sending another link.`);
  try {
    await sendSignInLinkToEmail(auth, clean, {
      url: `${window.location.origin}/auth/finish`,
      handleCodeInApp: true
    });
  } catch (e) {
    throw new Error(friendlyAuthError(e));
  }
  try {
    localStorage.setItem(EMAIL_FOR_SIGNIN_KEY, clean);
    localStorage.setItem(LAST_LINK_SENT_KEY, String(Date.now()));
  } catch {
    // without storage the user is asked for the email when the link opens
  }
}

/** True when the current URL is a Firebase email sign-in link. */
export function isEmailLinkInUrl(): boolean {
  const auth = getFirebaseAuth();
  return Boolean(auth && isSignInWithEmailLink(auth, window.location.href));
}

export function storedEmailForSignIn(): string | null {
  try {
    return localStorage.getItem(EMAIL_FOR_SIGNIN_KEY);
  } catch {
    return null;
  }
}

/** Finishes an email-link sign-in, then removes the one-time code from the URL. */
export async function completeEmailLinkSignIn(email: string): Promise<void> {
  const auth = getFirebaseAuth();
  if (!auth) throw new Error('Sign-in is not configured on this server.');
  try {
    await signInWithEmailLink(auth, email.trim(), window.location.href);
  } catch (e) {
    throw new Error(friendlyAuthError(e));
  } finally {
    window.history.replaceState(null, '', '/');
  }
  try {
    localStorage.removeItem(EMAIL_FOR_SIGNIN_KEY);
  } catch {
    // ignore
  }
}

export async function signOut(): Promise<void> {
  const auth = getFirebaseAuth();
  writeCachedProfile(null);
  if (auth) await firebaseSignOut(auth);
  setState({ user: null, cachedProfile: null });
}

function friendlyAuthError(e: any): string {
  const code: string = e?.code || '';
  switch (code) {
    case 'auth/invalid-email':
      return 'That email address is not valid.';
    case 'auth/invalid-action-code':
    case 'auth/expired-action-code':
      return 'This sign-in link has expired or was already used. Request a new one.';
    case 'auth/network-request-failed':
      return 'Network error. Check your connection and try again.';
    case 'auth/too-many-requests':
    case 'auth/quota-exceeded':
      return 'Too many attempts. Wait a few minutes and try again.';
    case 'auth/unauthorized-domain':
    case 'auth/unauthorized-continue-uri':
      return 'This address is not authorized for sign-in yet.';
    case 'auth/operation-not-allowed':
      return 'This sign-in method is not enabled yet.';
    default:
      return e?.message || 'Sign-in failed.';
  }
}
