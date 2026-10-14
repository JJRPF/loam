// A small stand-in for Firebase Hosting, for the browser tests: serves frontend/dist with the headers and
// rewrite from firebase.json (including its Content-Security-Policy), so CSP and CORS behave as in production.
// The API runs on another origin, as it does in production; the test build points VITE_API_BASE at it.
//   node tests/browser/hosting-server.mjs <port>   env: CSP_CONNECT_EXTRA (space separated origins added to connect-src)
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const dist = path.join(root, 'frontend', 'dist');
const cfg = JSON.parse(fs.readFileSync(path.join(root, 'firebase.json'), 'utf8')).hosting;
const port = Number(process.argv[2] || 5180);
const extra = (process.env.CSP_CONNECT_EXTRA || '').trim();

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8', '.xml': 'application/xml', '.webmanifest': 'application/manifest+json',
};

function globToRegex(g) {
  const re = g.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*\*/g, '\u0000').replace(/\*/g, '[^/]*').replace(/\u0000/g, '.*');
  return new RegExp('^' + re + '$');
}
const rules = cfg.headers.map((h) => ({ re: globToRegex(h.source), headers: h.headers }));

function headersFor(urlPath) {
  const out = {};
  for (const r of rules) {
    if (!r.re.test(urlPath)) continue;
    for (const { key, value } of r.headers) {
      out[key] = key === 'Content-Security-Policy' && extra ? value.replace('connect-src ', `connect-src ${extra} `) : value;
    }
  }
  return out;
}

function resolveFile(urlPath) {
  const p = path.normalize(path.join(dist, decodeURIComponent(urlPath)));
  if (!p.startsWith(dist)) return null;
  if (fs.existsSync(p) && fs.statSync(p).isFile()) return p;
  const idx = path.join(p, 'index.html');
  if (fs.existsSync(idx)) return idx;
  return null;
}

http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  let urlPath = u.pathname;
  // trailingSlash: true -> a directory with an index.html answers 301 to the slashed URL
  if (!urlPath.endsWith('/') && fs.existsSync(path.join(dist, urlPath)) && fs.statSync(path.join(dist, urlPath)).isDirectory()) {
    res.writeHead(301, { Location: urlPath + '/' + u.search });
    return res.end();
  }
  let file = resolveFile(urlPath);
  let servedPath = urlPath;
  if (!file) { file = path.join(dist, 'index.html'); servedPath = '/index.html'; } // SPA rewrite
  const headers = { ...headersFor(servedPath.endsWith('/') ? servedPath + 'index.html' : servedPath) };
  headers['Content-Type'] = TYPES[path.extname(file)] || 'application/octet-stream';
  res.writeHead(200, headers);
  if (req.method === 'HEAD') return res.end();
  fs.createReadStream(file).pipe(res);
}).listen(port, '127.0.0.1', () => console.log(`hosting stand-in on http://127.0.0.1:${port}`));
