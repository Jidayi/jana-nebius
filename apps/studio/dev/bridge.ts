// Development preview only. Production uses native stdio commands and has no HTTP authoring routes.
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import path from "node:path";
import type { Plugin } from "vite";

export function studioBridge(): Plugin {
  const token = randomUUID();
  return { name: "jana-studio-local-bridge", apply: "serve",
    transformIndexHtml: (html) => html.replace("__STUDIO_DEV_TOKEN__", token),
    configureServer(server) {
      const root = fileURLToPath(new URL("../../../", import.meta.url));
      const workspace = process.env.JANA_STUDIO_WORKSPACE ?? root;
      const python = process.env.JANA_STUDIO_PYTHON ?? path.join(root, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
      const child = spawn(python, ["-m", "pack_builder.studio", "--workspace", workspace, "--stdio"],
        { cwd: root, stdio: ["pipe", "pipe", "inherit"] });
      const pending: { resolve(value: string): void; reject(error: Error): void }[] = [];
      let dead = false;
      const fail = () => { dead = true; for (const request of pending.splice(0)) request.reject(new Error("The authoring backend stopped. Restart the studio.")); };
      child.on("error", fail); child.on("exit", fail);
      const lines = createInterface({ input: child.stdout });
      lines.on("line", (line) => pending.shift()?.resolve(line));
      const close = () => { child.stdin.end(); child.kill(); lines.close(); fail(); };
      server.httpServer?.once("close", close);
      server.middlewares.use("/__studio/command", (request, response) => {
        const origin = request.headers.origin;
        const host = request.headers.host;
        if (request.method !== "POST" || request.headers["x-studio-token"] !== token ||
            (origin !== undefined && origin !== `http://${host}`) ||
            !/^(127\.0\.0\.1|localhost):5191$/.test(host ?? "") ||
            request.headers["content-type"] !== "application/json") {
          response.statusCode = 403; response.end(); return;
        }
        let body = "", tooLarge = false;
        request.setEncoding("utf8");
        request.on("data", (chunk: string) => {
          body += chunk;
          if (Buffer.byteLength(body) > 512 * 1024) { tooLarge = true; body = ""; }
        });
        request.on("end", () => {
          if (tooLarge || dead) { response.statusCode = tooLarge ? 413 : 503; response.end(); return; }
          try { JSON.parse(body); } catch { response.statusCode = 400; response.end(); return; }
          const result = new Promise<string>((resolve, reject) => pending.push({ resolve, reject }));
          child.stdin.write(body.replace(/\n/g, " ") + "\n");
          void result.then((line) => { response.setHeader("content-type", "application/json"); response.end(line); })
            .catch(() => { response.statusCode = 503; response.end(); });
        });
      });
    },
  };
}
