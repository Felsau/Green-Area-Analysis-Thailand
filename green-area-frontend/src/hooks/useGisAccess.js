import { useCallback, useEffect, useState } from 'react';
import { supabase } from '../lib/supabaseClient';
import { gisConfigured, gisRequest } from '../utils/gisClient';

export function useGisAccess(userId) {
  const [state, setState] = useState({ owner: null, loading: false, me: null, error: null });
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision(n => n + 1), []);
  useEffect(() => {
    if (!userId || !gisConfigured()) { setState({ owner: userId, loading: false, me: null, error: null }); return; }
    const abort = new AbortController();
    setState(old => ({ owner: userId, loading: true, me: old.owner === userId ? old.me : null, error: null }));
    gisRequest('/me', { signal: abort.signal }).then(me => {
      if (!abort.signal.aborted) setState({ owner: userId, loading: false, me, error: null });
    }).catch(error => {
      if (!abort.signal.aborted) setState({ owner: userId, loading: false, me: null, error });
    });
    return () => abort.abort();
  }, [userId, revision]);
  useEffect(() => {
    const { data } = supabase.auth.onAuthStateChange(refresh);
    return () => data.subscription.unsubscribe();
  }, [refresh]);
  const current = state.owner === userId ? state : { loading: true, me: null, error: null };
  return { ...current, allowed: current.me?.capabilities?.includes('read_catalog') === true, refresh };
}
