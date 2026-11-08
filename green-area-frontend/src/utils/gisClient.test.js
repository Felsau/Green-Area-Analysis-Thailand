import { createGisClient, GisError, gisConfigured } from './gisClient';

const subject = '10000000-0000-4000-8000-000000000001';
const claims = { iss: 'http://127.0.0.1:55421/auth/v1', sub: subject, role: 'authenticated', exp: 9999999999 };
const token = value => `test.${btoa(JSON.stringify(value))}.test`;
const env = { VITE_GIS_ENABLED: 'true', VITE_GIS_API_URL: 'http://127.0.0.1:55422', VITE_API_URL: 'http://127.0.0.1:55422' };
const location = { hostname: '127.0.0.1', protocol: 'http:' };
const client = (overrides = {}, values = claims) => createGisClient({ enabled: true,
  getSession: async () => ({ data: { session: { access_token: token(values), user: { id: subject } } } }), ...overrides });

test.each(['geotiff-prepared','geotiff-prepare-jobs','geotiff-prepare-retry','geotiff-prepare-verification'])('GeoTIFF prepare route %s uses closed local client',async suffix=>{
  const fetcher=vi.fn(async()=>({ok:true,json:async()=>({preview_only:true})}));
  await client({fetcher})(`/editions/${subject}/${suffix}`,suffix==='geotiff-prepared'?{}:{method:'POST',key:subject,body:{job_id:subject}});
  expect(fetcher.mock.calls[0][0]).toContain(`/editions/${subject}/${suffix}`);
  expect(fetcher.mock.calls[0][1].cache).toBe('no-store');
});

test('GeoTIFF sends raw TIFF with exact local route, profile and idempotency', async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ upload_id: subject }) }));
  const body = new File(['II* test'], 'local.tif', { type: 'image/tiff' });
  await client({ fetcher })(`/datasets/${subject}/geotiff-uploads`, { method: 'POST', key: subject, body,
    query: { expected_revision: 3, crs: 'EPSG:32647', profile: 'ndvi_ready' } });
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toContain('/geotiff-uploads?'); expect(url).toContain('profile=ndvi_ready');
  expect(options.body).toBe(body); expect(options.headers['Content-Type']).toBe('image/tiff');
  expect(options.headers['Idempotency-Key']).toBe(subject);
});

test('LDD upload sends raw binary with revision and stable idempotency header', async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ id: subject }) }));
  const body = new File(['PK mock bytes'], 'sample.zip', { type: 'application/zip' });
  await client({ fetcher })(`/datasets/${subject}/ldd-uploads`, { method: 'POST', key: subject,
    query: { expected_revision: 3, crs: 'EPSG:32647', encoding: 'auto' }, body });
  const [url, options] = fetcher.mock.calls[0];
  expect(new URL(url).searchParams.get('expected_revision')).toBe('3');
  expect(options.body).toBe(body);
  expect(options.headers['Content-Type']).toBe('application/zip');
  expect(options.headers['Idempotency-Key']).toBe(subject);
  expect(options.redirect).toBe('error');
});

test('binary input cannot be sent to ordinary GIS commands', async () => {
  const fetcher = vi.fn();
  await expect(client({ fetcher })('/datasets', { method: 'POST', key: subject,
    body: new Blob(['bad']) })).rejects.toMatchObject({ status: 413 });
  expect(fetcher).not.toHaveBeenCalled();
});

test('processing uses the same authenticated client and a closed HTTP path list', async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ id: subject }) }));
  const request = client({ fetcher });
  const body = { province: 'Bangkok Metropolis', metric: 'ndvi', data_year: 2025, month: 0, mode: 'offline_synthetic' };
  await request('/processing-jobs', { method: 'POST', key: subject, body });
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(body);
  await expect(request('/gis_processing_worker')).rejects.toBeInstanceOf(GisError);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

test('GIS is disabled by default and exact local configuration is required', () => {
  expect(gisConfigured({}, location, 'http://127.0.0.1:55421')).toBe(false);
  expect(gisConfigured(env, location, 'http://127.0.0.1:55421')).toBe(true);
  expect(gisConfigured(env, { hostname: 'localhost', protocol: 'http:' }, 'http://127.0.0.1:55421')).toBe(true);
});
test.each([
  [{ ...env, VITE_GIS_API_URL: 'https://example.invalid' }, location, 'http://127.0.0.1:55421'],
  [{ ...env, VITE_API_URL: 'https://example.invalid' }, location, 'http://127.0.0.1:55421'],
  [env, { ...location, hostname: 'example.invalid' }, 'http://127.0.0.1:55421'],
  [env, location, 'https://example.invalid'],
  [{ ...env, VITE_GIS_ENABLED: 'false' }, location, 'http://127.0.0.1:55421'],
])('rejects unknown host/API/Auth/flag (%#)', (e, l, a) => expect(gisConfigured(e, l, a)).toBe(false));
test.each(['/../account', 'https://example.invalid/gis/me', '//example.invalid', '/jobs?next=https://example.invalid'])('rejects non-allowlisted paths before session/network %s', async path => {
  const fetcher = vi.fn(); const session = vi.fn();
  await expect(client({ fetcher, getSession: session })(path)).rejects.toBeInstanceOf(GisError);
  expect(fetcher).not.toHaveBeenCalled(); expect(session).not.toHaveBeenCalled();
});
test.each([{ ...claims, iss: 'https://example.invalid/auth/v1' }, { ...claims, sub: 'other' }, { ...claims, exp: 0 },
  { ...claims, exp: undefined }, { ...claims, role: 'service_role' }])('never sends an incompatible session (%#)', async value => {
  const fetcher = vi.fn(); await expect(client({ fetcher }, value)('/me')).rejects.toMatchObject({ status: 401 }); expect(fetcher).not.toHaveBeenCalled();
});
test('request uses existing session, query encoding, abort and no redirects/cookies', async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ data: [] }) }));
  await client({ fetcher })('/datasets', { query: { province: 'A & B', month: 0, cursor: null } });
  const [url, options] = fetcher.mock.calls[0];
  expect(new URL(url).searchParams.get('province')).toBe('A & B'); expect(new URL(url).searchParams.get('month')).toBe('0');
  expect(options.redirect).toBe('error'); expect(options.credentials).toBe('omit'); expect(options.headers.Authorization).toBe(`Bearer ${token(claims)}`);
});
test('mutation requires UUID and sends unchanged body and idempotency key', async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ id: subject }) })); const req = client({ fetcher });
  await expect(req('/datasets', { method: 'POST', body: {} })).rejects.toMatchObject({ status: 422 }); expect(fetcher).not.toHaveBeenCalled();
  await req('/datasets', { method: 'POST', body: { title: 'ทดสอบ' }, key: subject });
  expect(fetcher.mock.calls[0][1].headers['Idempotency-Key']).toBe(subject);
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ title: 'ทดสอบ' });
});
test.each([401, 403, 409, 422, 429, 503])('sanitizes backend error %s without exposing raw response', async status => {
  const fetcher = vi.fn(async () => ({ ok: false, status, json: () => { throw new Error('sensitive diagnostic'); } }));
  await expect(client({ fetcher })('/me')).rejects.toMatchObject({ status });
  await expect(client({ fetcher })('/me')).rejects.not.toHaveProperty('message', 'sensitive diagnostic');
});
test('does not automatically retry ambiguous mutations', async () => {
  const fetcher = vi.fn(async () => { throw new TypeError('sensitive network diagnostic'); });
  await expect(client({ fetcher })('/datasets', { method: 'POST', key: subject, body: {} })).rejects.toMatchObject({ status: 0 });
  expect(fetcher).toHaveBeenCalledTimes(1);
});
test('unmount aborts an in-flight request', async () => {
  const abort = new AbortController();
  const fetcher = vi.fn((_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('cancelled')))));
  const pending = client({ fetcher })('/me', { signal: abort.signal });
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalled()); abort.abort();
  await expect(pending).rejects.toHaveProperty('name', 'AbortError');
});

const cloudAuth = 'https://abcdefghijklmnopqrst.supabase.co';
const cloudTarget = Object.freeze({ name: 'cloud', api: 'https://green-area-backend.onrender.com',
  auth: cloudAuth, issuer: `${cloudAuth}/auth/v1` });
const against = (target, values, fetcher) => createGisClient({ target, fetcher,
  getSession: async () => ({ data: { session: { access_token: token(values), user: { id: subject } } } }) });

test('a hosted target is the one the request is sent to', async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ data: [] }) }));
  await against(cloudTarget, { ...claims, iss: cloudTarget.issuer }, fetcher)('/datasets');
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toBe(`${cloudTarget.api}/gis/datasets`);
  // Everything the local client refused, the hosted one refuses too.
  expect(options.redirect).toBe('error'); expect(options.credentials).toBe('omit'); expect(options.cache).toBe('no-store');
});

test.each([
  ['a sandbox session against the hosted project', cloudTarget, 'http://127.0.0.1:55421/auth/v1'],
  ['a hosted session against the sandbox', undefined, `${cloudAuth}/auth/v1`],
  ['a session from a project nobody declared', cloudTarget, 'https://tsrqponmlkjihgfedcba.supabase.co/auth/v1'],
])('never sends %s', async (_why, target, iss) => {
  const fetcher = vi.fn();
  const request = target ? against(target, { ...claims, iss }, fetcher)
    : createGisClient({ enabled: true, fetcher,
        getSession: async () => ({ data: { session: { access_token: token({ ...claims, iss }), user: { id: subject } } } }) });
  await expect(request('/me')).rejects.toMatchObject({ status: 401 });
  expect(fetcher).not.toHaveBeenCalled();
});

test('the route allowlist still applies to a hosted target', async () => {
  const fetcher = vi.fn(); const session = vi.fn();
  const request = createGisClient({ target: cloudTarget, fetcher, getSession: session });
  for (const path of ['/../account', '//example.invalid', 'https://example.invalid/gis/me']) {
    await expect(request(path)).rejects.toBeInstanceOf(GisError);
  }
  expect(fetcher).not.toHaveBeenCalled(); expect(session).not.toHaveBeenCalled();
});
