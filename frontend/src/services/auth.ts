import type { AuthUser } from '../types';
import { verifyAuthToken } from './api';

const AUTH_USER_KEY = 'loam_auth_user_v1';

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

export async function loginWithGoogleCredential(credentialOrToken: string): Promise<AuthUser> {
  const verifiedUser = await verifyAuthToken({ token: credentialOrToken });
  setStoredUser(verifiedUser);
  return verifiedUser;
}

export async function mockGoogleLogin(email = 'justin@example.com', displayName = 'Justin Pfister'): Promise<AuthUser> {
  const uid = `google_${email.split('@')[0]}`;
  const verifiedUser = await verifyAuthToken({
    uid,
    email,
    displayName,
    token: `mock_google_token_${uid}`
  });
  setStoredUser(verifiedUser);
  return verifiedUser;
}

export function logoutUser() {
  setStoredUser(null);
}
