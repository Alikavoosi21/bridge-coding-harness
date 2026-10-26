// Test-only local server for the same static export loaded by Electron.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../out');
const types = { '.html':'text/html; charset=utf-8', '.js':'text/javascript', '.css':'text/css', '.svg':'image/svg+xml', '.png':'image/png', '.gif':'image/gif', '.woff2':'font/woff2' };
http.createServer((request, response) => {
  const base = path.resolve(root, '.' + decodeURIComponent(new URL(request.url, 'http://localhost').pathname));
  if (base !== root && !base.startsWith(root + path.sep)) { response.writeHead(403).end(); return; }
  const file = [base, base + '.html', path.join(base, 'index.html')].find(file => fs.existsSync(file) && fs.statSync(file).isFile());
  if (!file) { response.writeHead(404).end(); return; }
  response.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
  fs.createReadStream(file).pipe(response);
}).listen(Number(process.argv[2] || 3211), '127.0.0.1');
