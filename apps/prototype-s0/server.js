// Jana — tiny zero-dependency server.
// Serves the UI and proxies /ollama/* to the local Ollama daemon, so nothing leaves the machine.
const http = require("http");
const fs = require("fs");
const path = require("path");
const { exec } = require("child_process");

const PORT = Number(process.env.PORT) || 5178;
const HOST = "127.0.0.1";
const OLLAMA = process.env.OLLAMA_HOST_URL || "http://127.0.0.1:11434";

const PUBLIC = path.join(__dirname, "public");
const NM = path.join(__dirname, "node_modules");

// Only these vendor files/folders are exposed.
const VENDOR = {
  "/vendor/katex/": path.join(NM, "katex/dist/"),
  "/vendor/marked/": path.join(NM, "marked/lib/"),
  "/vendor/function-plot/": path.join(NM, "function-plot/dist/"),
};

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".ttf": "font/ttf",
};

function sendFile(res, file) {
  fs.stat(file, (err, st) => {
    if (err || !st.isFile()) {
      res.writeHead(404).end("Not found");
      return;
    }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
}

function safeJoin(root, rel) {
  const p = path.normalize(path.join(root, rel));
  const base = root.endsWith(path.sep) ? root : root + path.sep;
  return p === root || p.startsWith(base) ? p : null;
}

// Only the endpoints the UI needs are forwarded. Anything else (delete, pull, push, create…) is refused,
// so a web page in the same browser cannot drive Ollama through this proxy.
const ALLOWED = { "/api/tags": ["GET"], "/api/show": ["POST"], "/api/chat": ["POST"], "/api/version": ["GET"] };

async function proxy(req, res, upstreamPath) {
  const pathOnly = upstreamPath.split("?")[0];
  if (!ALLOWED[pathOnly]?.includes(req.method)) {
    res.writeHead(405, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ error: `${req.method} ${pathOnly} is not proxied.` }));
  }
  const ac = new AbortController();
  res.on("close", () => ac.abort()); // stop generation when the browser hits Stop
  try {
    const body = ["GET", "HEAD"].includes(req.method) ? undefined : req;
    const r = await fetch(OLLAMA + upstreamPath, {
      method: req.method,
      headers: { "Content-Type": "application/json" },
      body,
      duplex: "half",
      signal: ac.signal,
    });
    res.writeHead(r.status, { "Content-Type": r.headers.get("content-type") || "application/json" });
    if (!r.body) return res.end();
    for await (const chunk of r.body) res.write(chunk);
    res.end();
  } catch (e) {
    if (ac.signal.aborted) return;
    if (res.headersSent) return res.destroy(); // upstream died mid-stream: drop this response, keep the server up
    res.writeHead(502, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: `Can't reach Ollama at ${OLLAMA}. Is it running? (${e.cause?.code || e.message})` }));
  }
}

// Requests must come from this server's own origin (the UI), never from another site open in the browser.
function sameOrigin(req) {
  const host = req.headers.host || "";
  if (!/^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/.test(host)) return false;
  const origin = req.headers.origin;
  if (origin && origin !== `http://${host}`) return false;
  return true;
}

const server = http.createServer((req, res) => {
  if (!sameOrigin(req)) {
    res.writeHead(403, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ error: "Forbidden: cross-origin request." }));
  }
  const url = new URL(req.url, `http://${req.headers.host}`);
  let p;
  try {
    p = decodeURIComponent(url.pathname);
  } catch {
    res.writeHead(400).end("Bad request"); // malformed %-encoding must not crash the server
    return;
  }

  if (p.startsWith("/ollama/")) {
    proxy(req, res, p.slice("/ollama".length) + url.search).catch((e) => {
      console.error("proxy error:", e.message);
      if (!res.headersSent) res.writeHead(500).end();
      else res.destroy();
    });
    return;
  }

  for (const [prefix, dir] of Object.entries(VENDOR)) {
    if (p.startsWith(prefix)) {
      const f = safeJoin(dir, p.slice(prefix.length));
      return f ? sendFile(res, f) : res.writeHead(403).end();
    }
  }

  const f = safeJoin(PUBLIC, p === "/" ? "index.html" : p);
  return f ? sendFile(res, f) : res.writeHead(403).end();
});

server.listen(PORT, HOST, () => {
  const url = `http://localhost:${PORT}`;
  console.log(`\n  Jana running at ${url}`);
  console.log(`  Using Ollama at ${OLLAMA}\n  Press Ctrl+C to stop.\n`);
  if (!process.env.NO_OPEN && process.platform === "darwin") exec(`open ${url}`);
});
