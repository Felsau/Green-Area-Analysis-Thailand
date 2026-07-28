import { createClient } from '@supabase/supabase-js';

// Auth token lifecycle (signup/signin/verify/reset) talks to Supabase Auth
// (GoTrue) directly from the browser with the public anon key — this is the
// standard Supabase pattern and is safe: the anon key only grants what RLS
// allows, and `profiles` has no client-writable policies (see migrations/009).
// All other app data still goes through the FastAPI backend (API_BASE).
export const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || '';
export const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || '';

export const supabaseConfigured = !!(SUPABASE_URL && SUPABASE_ANON_KEY);

// Falls back to a harmless placeholder URL when unconfigured so createClient()
// never throws at import time — useAuth surfaces a clear error instead of a
// white-screen crash when the env vars are missing.
export const supabase = createClient(
  SUPABASE_URL || 'https://placeholder.supabase.co',
  SUPABASE_ANON_KEY || 'placeholder-anon-key',
);
