// Explicit local/test profile: never load the application's .env files.
import base from '../../green-area-frontend/vite.config.js';
import { fileURLToPath } from 'node:url';

const local = process.env.GIS_UI_LOCAL === 'true';
export default {
  ...base,
  root: fileURLToPath(new URL('../../green-area-frontend', import.meta.url)),
  envDir: fileURLToPath(new URL('./no-env-files', import.meta.url)),
  server: { host: '127.0.0.1', port: 3000, strictPort: true },
  define: {
    'import.meta.env.VITE_LOCAL_DEMO': JSON.stringify(local ? 'true' : 'false'),
    'import.meta.env.VITE_GIS_ENABLED': JSON.stringify(local ? 'true' : 'false'),
    'import.meta.env.VITE_GIS_API_URL': JSON.stringify('http://127.0.0.1:55422'),
    'import.meta.env.VITE_API_URL': JSON.stringify('http://127.0.0.1:55422'),
    'import.meta.env.VITE_SUPABASE_URL': JSON.stringify(local ? 'http://127.0.0.1:55421' : ''),
    'import.meta.env.VITE_SUPABASE_ANON_KEY': JSON.stringify(local ? process.env.GIS_UI_LOCAL_ANON_KEY || '' : ''),
  },
};
