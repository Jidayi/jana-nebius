// Development only: starts the agent core sidecar the way the shell does (ARC-04): the launch token goes over stdin,
// never argv or the environment, and the core answers `control.ready` with its loopback port. The Vite dev server
// hands the launch info to the page from a dev-only endpoint; production builds get it from the Tauri shell.
// The data folder starts empty, so the repository's O level content packs are built, development-signed and installed
// into it alongside the core's start (`seed_packs.py`; built packs are cached, so only the first run builds them).
// `JANA_DEV_PACKS=0` starts with no packs, as a fresh install without a USB kit does.
// Voice: the core asks the shell to start an installed speech pack's sidecar (`control.voice_start`, VOC-23); this
// stands in for the shell's supervisor (`src-tauri/src/voice.rs`) without its sandbox or restart policy.
// `JANA_DEV_HARDWARE=mid|high` makes the core treat this machine as that class, so conversation is offered.
import { spawn, type ChildProcess } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createInterface } from "node:readline";
import type { Plugin } from "vite";

export interface Launch {
  base_url: string;
  token: string;
}

const REPO = path.resolve(import.meta.dirname, "../../..");

export function startSidecar(devOrigin: string): Promise<{ launch: Launch; child: ChildProcess }> {
  const versions = readFileSync(path.join(REPO, "scripts", "jana_tools", "codegen", "versions.toml"), "utf8");
  const control = /\[interfaces\.control\][\s\S]*?^version\s*=\s*"(\d+)\.(\d+)"/m.exec(versions);
  if (control === null) throw new Error("control protocol version is missing");
  const token = randomBytes(32).toString("base64url");
  const child = spawn("uv", ["run", "--quiet", "python", "-m", "agent_core.api"], { cwd: REPO, stdio: ["pipe", "pipe", "inherit"] });
  const send = (message: unknown) => child.stdin?.write(`${JSON.stringify(message)}\n`);
  const voice = new DevVoice(send);
  child.on("exit", () => voice.stop());
  const runtime = process.env.JANA_DEV_RUNTIME; // "<url> <key> <model>": a local llama-server instead of the script
  const dataDir = process.env.JANA_DEV_DATA_DIR === undefined
    ? mkdtempSync(path.join(tmpdir(), "jana-dev-"))
    : path.resolve(process.env.JANA_DEV_DATA_DIR);
  mkdirSync(dataDir, { recursive: true, mode: 0o700 });
  if (process.env.JANA_DEV_PACKS !== "0") seedPacks(dataDir);
  send({ type: "control.hello", protocol: { major: Number(control[1]), minor: Number(control[2]) } });
  send({
    type: "control.config",
    data_dir: dataDir,
    content_root: path.join(REPO, "content", "agent"),
    skills_root: path.join(REPO, "skills"),
    release: false,
    dev_origins: [...new Set([devOrigin, devOrigin.replace("localhost", "127.0.0.1")])],
    scripted: runtime === undefined,
  });
  send({ type: "control.secret", name: "launch_token", value: token });
  return new Promise((resolve, reject) => {
    if (child.stdout === null) throw new Error("sidecar has no stdout");
    const lines = createInterface({ input: child.stdout });
    lines.on("line", (line) => {
      const message = JSON.parse(line) as { type: string; api_port?: number; code?: string };
      if (message.type === "control.voice_start") {
        voice.start(message as unknown as VoiceStart);
      } else if (message.type === "control.voice_stop") {
        voice.stop();
      } else if (message.type === "control.ready") {
        if (runtime !== undefined) {
          const [url, key, model] = runtime.split(" ");
          send({ type: "control.runtime_endpoint", url, key, model });
        }
        resolve({ launch: { base_url: `http://127.0.0.1:${message.api_port}`, token }, child });
      } else if (message.type === "control.error") {
        send({ type: "control.shutdown" });
        reject(new Error(message.code));
      }
    });
    child.on("exit", (code) => reject(new Error(`sidecar exited ${code}`)));
  });
}

interface VoiceStart {
  request_id: string;
  program: string;
  program_sha256: string;
  pack_dir: string;
  hardware: string;
  platform: string;
  app_version: string;
  environment: string;
  adapter_url: string;
  adapter_token: string;
}

/** The shell's voice supervisor in miniature: check the entry point's digest, start it with a cleared environment and
 * the offline flags, send the launch on stdin (kept open: the sidecar stops when we go) and relay its readiness. */
class DevVoice {
  private child: ChildProcess | null = null;

  constructor(private readonly send: (message: unknown) => void) {}

  start(start: VoiceStart): void {
    this.stop();
    const failed = (why: string) => {
      process.stderr.write(`dev voice: ${why}\n`);
      this.send({ type: "control.voice_failed", request_id: start.request_id, code: "voice_start_failed" });
    };
    if (createHash("sha256").update(readFileSync(start.program)).digest("hex") !== start.program_sha256) {
      return failed("entry point digest mismatch");
    }
    const child = spawn(start.program, [], {
      cwd: start.pack_dir,
      env: { HOME: process.env.HOME ?? "", HF_HUB_OFFLINE: "1", TRANSFORMERS_OFFLINE: "1", PYTHONDONTWRITEBYTECODE: "1" },
      stdio: ["pipe", "pipe", "inherit"],
    });
    this.child = child;
    const realtime = randomBytes(32).toString("base64url");
    const keys = ["pack_dir", "hardware", "platform", "app_version", "environment", "adapter_url", "adapter_token"] as const;
    const launch = Object.fromEntries(keys.map((key) => [key, start[key]]));
    child.stdin?.write(`${JSON.stringify({ protocol: 1, ...launch, realtime_token: realtime })}\n`);
    let ready = false;
    if (child.stdout !== null) {
      createInterface({ input: child.stdout }).once("line", (line) => {
        const reply = JSON.parse(line) as { type?: string; port?: number; code?: string };
        if (reply.type !== "voice.ready") return failed(`sidecar answered ${line}`);
        ready = true;
        process.stderr.write(`dev voice: sidecar ready on ${reply.port}\n`);
        this.send({
          type: "control.voice_endpoint",
          request_id: start.request_id,
          url: `ws://127.0.0.1:${reply.port}/v1/realtime`,
          token: realtime,
        });
      });
    }
    child.on("exit", (code) => {
      if (this.child === child) this.child = null;
      if (!ready) failed(`sidecar exited ${code} before it was ready`);
    });
  }

  stop(): void {
    this.child?.kill();
    this.child = null;
  }
}

/** Build (or take from the cache) and install the O level packs into the dev data folder; the core reads the packs
 * folder as it changes, so the subjects appear once this finishes (refocus the window to refresh the notices). */
function seedPacks(dataDir: string): void {
  const seeder = spawn("uv", ["run", "--quiet", "python", path.join("apps", "desktop", "dev", "seed_packs.py"), dataDir], { cwd: REPO, stdio: ["ignore", "inherit", "inherit"] });
  seeder.on("exit", (code) => {
    if (code !== 0) process.stderr.write(`dev packs: seeding exited ${code}; the app starts with no subjects\n`);
  });
}

export function sidecarPlugin(): Plugin {
  let ready: Promise<Launch> | null = null;
  let child: ChildProcess | null = null;
  return {
    name: "jana-dev-sidecar",
    apply: "serve",
    configureServer(server) {
      server.httpServer?.once("listening", () => {
        const address = server.httpServer?.address();
        const port = typeof address === "object" && address !== null ? address.port : 5180;
        ready = startSidecar(`http://localhost:${port}`).then((started) => {
          child = started.child;
          server.config.logger.info(`  agent core: ${started.launch.base_url}`);
          return started.launch;
        });
        ready.catch((error: unknown) => server.config.logger.error(`agent core failed to start: ${String(error)}`));
      });
      server.httpServer?.once("close", () => child?.stdin?.write('{"type":"control.shutdown"}\n'));
      // The page waits here until the core is up (no polling, no error noise while it starts).
      server.middlewares.use("/__jana_dev/launch", (_req, res) => {
        res.setHeader("content-type", "application/json");
        res.setHeader("cache-control", "no-store");
        const answer = (status: number, body: unknown) => {
          res.statusCode = status;
          res.end(JSON.stringify(body));
        };
        if (ready === null) return answer(503, { error: "starting" });
        ready.then((launch) => answer(200, launch), () => answer(500, { error: "core_failed" }));
      });
    },
  };
}
