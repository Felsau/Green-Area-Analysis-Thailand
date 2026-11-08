import { LOCAL_TARGET, gisTarget } from './gisTarget';

const REF = 'abcdefghijklmnopqrst';
const CLOUD_AUTH = `https://${REF}.supabase.co`;
const CLOUD_API = 'https://green-area-backend.onrender.com';

const local = { VITE_GIS_ENABLED: 'true', VITE_GIS_API_URL: LOCAL_TARGET.api, VITE_API_URL: LOCAL_TARGET.api };
const cloud = { VITE_GIS_ENABLED: 'true', VITE_GIS_API_URL: CLOUD_API, VITE_API_URL: CLOUD_API };
const onLocalhost = { hostname: '127.0.0.1', protocol: 'http:' };
const onTheWeb = { hostname: 'green-area.vercel.app', protocol: 'https:' };

test('nothing is configured by default', () => {
  expect(gisTarget({}, onLocalhost, LOCAL_TARGET.auth)).toBe(null);
  expect(gisTarget({}, onTheWeb, CLOUD_AUTH)).toBe(null);
  expect(gisTarget(undefined, onTheWeb, CLOUD_AUTH)).toBe(null);
});

test('the sandbox keeps exactly the identity it had', () => {
  expect(gisTarget(local, onLocalhost, LOCAL_TARGET.auth)).toEqual(LOCAL_TARGET);
  expect(gisTarget(local, { hostname: 'localhost', protocol: 'http:' }, LOCAL_TARGET.auth)).toEqual(LOCAL_TARGET);
  expect(LOCAL_TARGET.issuer).toBe('http://127.0.0.1:55421/auth/v1');
});

test('a hosted project takes its issuer from the project it names', () => {
  expect(gisTarget(cloud, onTheWeb, CLOUD_AUTH)).toEqual({
    name: 'cloud', api: CLOUD_API, auth: CLOUD_AUTH, issuer: `${CLOUD_AUTH}/auth/v1` });
});

test('stray whitespace around a pasted value is not a misconfiguration', () => {
  const padded = { ...cloud, VITE_GIS_API_URL: `  ${CLOUD_API}`, VITE_API_URL: `${CLOUD_API}\n` };
  expect(gisTarget(padded, onTheWeb, ` ${CLOUD_AUTH} `)?.api).toBe(CLOUD_API);
});

test('the backend URL must be stated the same way twice', () => {
  expect(gisTarget({ ...cloud, VITE_API_URL: 'https://other.onrender.com' }, onTheWeb, CLOUD_AUTH)).toBe(null);
  expect(gisTarget({ ...local, VITE_API_URL: '' }, onLocalhost, LOCAL_TARGET.auth)).toBe(null);
});

test.each([
  ['the flag is off', { ...cloud, VITE_GIS_ENABLED: 'false' }, onTheWeb, CLOUD_AUTH],
  ['the flag is truthy but not true', { ...cloud, VITE_GIS_ENABLED: '1' }, onTheWeb, CLOUD_AUTH],
  ['the page is not served over TLS', cloud, { hostname: 'green-area.vercel.app', protocol: 'http:' }, CLOUD_AUTH],
  ['the backend is not served over TLS', { VITE_GIS_ENABLED: 'true', VITE_GIS_API_URL: 'http://green-area-backend.onrender.com', VITE_API_URL: 'http://green-area-backend.onrender.com' }, onTheWeb, CLOUD_AUTH],
  ['the auth host is not a project ref', cloud, onTheWeb, 'https://short.supabase.co'],
  ['the auth host only looks like one', cloud, onTheWeb, `https://${REF}.supabase.co.example.invalid`],
  ['the auth host has a path', cloud, onTheWeb, `${CLOUD_AUTH}/auth/v1`],
  ['the backend URL has a path', { ...cloud, VITE_GIS_API_URL: `${CLOUD_API}/gis`, VITE_API_URL: `${CLOUD_API}/gis` }, onTheWeb, CLOUD_AUTH],
  ['the backend URL has a query', { ...cloud, VITE_GIS_API_URL: `${CLOUD_API}?a=1`, VITE_API_URL: `${CLOUD_API}?a=1` }, onTheWeb, CLOUD_AUTH],
  ['the backend URL carries credentials', { ...cloud, VITE_GIS_API_URL: 'https://user:pw@green-area-backend.onrender.com', VITE_API_URL: 'https://user:pw@green-area-backend.onrender.com' }, onTheWeb, CLOUD_AUTH],
  ['the backend URL is a bare host', { ...cloud, VITE_GIS_API_URL: 'https://localhost', VITE_API_URL: 'https://localhost' }, onTheWeb, CLOUD_AUTH],
  ['the sandbox is claimed from the open web', local, onTheWeb, LOCAL_TARGET.auth],
  ['a hosted project is claimed on localhost over http', cloud, onLocalhost, CLOUD_AUTH],
  ['auth is missing entirely', cloud, onTheWeb, ''],
])('selects nothing when %s', (_why, env, location, authUrl) => {
  expect(gisTarget(env, location, authUrl)).toBe(null);
});

test('a selected target cannot be edited by whoever receives it', () => {
  const target = gisTarget(cloud, onTheWeb, CLOUD_AUTH);
  expect(() => { 'use strict'; target.api = 'https://example.invalid'; }).toThrow();
  expect(target.api).toBe(CLOUD_API);
  expect(Object.isFrozen(LOCAL_TARGET)).toBe(true);
});
