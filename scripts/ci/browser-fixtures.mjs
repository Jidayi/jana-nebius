import { createServer } from "node:http";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

export async function fixtureServer({ root = path.resolve(`apps/desktop/dist/benchmark${process.env.JANA_GALLERY_BUILD_ID ? `-${process.env.JANA_GALLERY_BUILD_ID}` : ""}`) } = {}) {
  root = path.resolve(root);
  // Serve one immutable build: another verification process may rebuild the shared output directory mid-journey.
  const files = new Map();
  const collect = async (directory) => {
    await Promise.all((await readdir(directory, { withFileTypes: true })).map(async (entry) => {
      const file = path.join(directory, entry.name);
      if (entry.isDirectory()) await collect(file);
      else if (entry.isFile()) files.set(file, await readFile(file));
    }));
  };
  await collect(root);
  if (!files.has(path.join(root, "gallery.html"))) throw new Error("Build the gallery before starting the fixture server");
  const mime = { ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".woff2": "font/woff2", ".svg": "image/svg+xml" };
  const server = createServer((req, res) => {
    const file = path.resolve(root, `.${new URL(req.url, "http://localhost").pathname}`);
    if (!file.startsWith(`${root}${path.sep}`)) { res.writeHead(403).end(); return; }
    const bytes = files.get(file);
    if (bytes === undefined) { res.writeHead(404).end(); return; }
    res.setHeader("Content-Type", mime[path.extname(file)] ?? "application/octet-stream"); res.end(bytes);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return { url: `http://127.0.0.1:${server.address().port}`, close: () => new Promise((resolve) => server.close(resolve)) };
}
