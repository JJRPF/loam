import type { AuthUser } from '../types';
import { verifyAuthToken } from './api';

const AUTH_USER_KEY = 'loam_auth_user_v1';
export const DEFAULT_GOOGLE_CLIENT_ID = '918738912384-sampleloamclientid.apps.googleusercontent.com';

declare global {
  interface Window {
    google?: any;
  }
}

export function getStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(AUTH_USER_KEY);
    if (raw) {
      return JSON.parse(raw);
    }
  } catch (e) {
    console.error('Failed to read auth user from localStorage', e);
  }
  return null;
}

export function setStoredUser(user: AuthUser | null) {
  try {
    if (user) {
      localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
    } else {
      localStorage.removeItem(AUTH_USER_KEY);
    }
  } catch (e) {
    console.error('Failed to save auth user to localStorage', e);
  }
}

export function getGoogleClientId(): string {
  return (
    (typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_GOOGLE_CLIENT_ID) ||
    DEFAULT_GOOGLE_CLIENT_ID
  );
}

export async function loginWithGoogleCredential(credentialOrToken: string): Promise<AuthUser> {
  const verifiedUser = await verifyAuthToken({ token: credentialOrToken });
  setStoredUser(verifiedUser);
  return verifiedUser;
}

export async function loginWithRealCredentials(
  email: string,
  displayName?: string,
  token?: string
): Promise<AuthUser> {
  const cleanEmail = email.trim();
  const cleanName = displayName?.trim() || cleanEmail.split('@')[0];
  const uid = `google_${cleanEmail.replace(/[^a-zA-Z0-9]/g, '_')}`;

  const verifiedUser = await verifyAuthToken({
    token: token || `token_${uid}_${Date.now()}`,
    uid,
    email: cleanEmail,
    displayName: cleanName
  });

  setStoredUser(verifiedUser);
  return verifiedUser;
}

export function initGoogleIdentityServices(
  onSuccess: (user: AuthUser) => void,
  onError?: (err: Error) => void
): boolean {
  if (typeof window === 'undefined' || !window.google?.accounts?.id) {
    return false;
  }

  try {
    window.google.accounts.id.initialize({
      client_id: getGoogleClientId(),
      callback: async (response: any) => {
        if (response?.credential) {
          try {
            const user = await loginWithGoogleCredential(response.credential);
            onSuccess(user);
          } catch (e: any) {
            onError?.(e);
          }
        }
      },
      auto_select: false
    });
    return true;
  } catch (e: any) {
    console.warn('Google Identity Services initialization notice:', e);
    return false;
  }
}

export function renderGoogleButton(
  container: HTMLElement,
  onSuccess: (user: AuthUser) => void,
  onError?: (err: Error) => void
): boolean {
  if (typeof window === 'undefined' || !window.google?.accounts?.id) {
    return false;
  }

  const initialized = initGoogleIdentityServices(onSuccess, onError);
  if (!initialized) return false;

  try {
    window.google.accounts.id.renderButton(container, {
      type: 'standard',
      shape: 'rectangular',
      theme: 'filled_black',
      text: 'signin_with',
      size: 'large',
      logo_alignment: 'left',
      width: container.clientWidth || 320
    });
    return true;
  } catch (e) {
    console.warn('Could not render Google button:', e);
    return false;
  }
}

export function logoutUser() {
  setStoredUser(null);
  if (typeof window !== 'undefined' && window.google?.accounts?.id) {
    try {
      window.google.accounts.id.disableAutoSelect();
    } catch {
      // ignore
    }
  }
}
