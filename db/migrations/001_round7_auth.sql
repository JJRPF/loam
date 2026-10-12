-- Round 7 (GH-34) phase 1: Firebase Auth.
-- Users that have signed in with a verified Firebase ID token are marked 'firebase';
-- legacy rows (raw Google sub or client-made uids) keep NULL until they are re-keyed.
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider TEXT;
