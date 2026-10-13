import { initializeApp, type FirebaseApp } from 'firebase/app';
import { browserLocalPersistence, getAuth, setPersistence, type Auth } from 'firebase/auth';

// Firebase web config comes from the build env (VITE_FIREBASE_*). Without it the app
// still routes anonymously and the sign-in card says sign-in isn't configured.
const env = import.meta.env;
const config = {
  apiKey: env.VITE_FIREBASE_API_KEY as string | undefined,
  authDomain: env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined,
  projectId: env.VITE_FIREBASE_PROJECT_ID as string | undefined,
  appId: env.VITE_FIREBASE_APP_ID as string | undefined
};

export const firebaseConfigured = Boolean(config.apiKey && config.authDomain && config.projectId && config.appId);

let app: FirebaseApp | null = null;
let auth: Auth | null = null;

export function getFirebaseAuth(): Auth | null {
  if (!firebaseConfigured) return null;
  if (!auth) {
    app = initializeApp(config);
    auth = getAuth(app);
    setPersistence(auth, browserLocalPersistence).catch((e) => console.warn('Auth persistence:', e));
  }
  return auth;
}
