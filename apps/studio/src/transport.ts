import { StudioError, type Command, type Workspace } from "./model.js";
type Native = { invoke(command: string, args?: Record<string, unknown>): Promise<unknown> };
const native = () => (globalThis as { __TAURI_INTERNALS__?: Native }).__TAURI_INTERNALS__;
export const command: Command = async <T,>(request: Record<string, unknown>): Promise<T> => {
  const host = native();
  const reply = host ? await host.invoke("studio_command", { request }) : await fetch("/__studio/command", {
    method: "POST", headers: { "content-type": "application/json", "x-studio-token": document.querySelector<HTMLMetaElement>('meta[name="studio-token"]')?.content ?? "" },
    body: JSON.stringify(request),
  }).then(async (r) => { if (!r.ok) throw new Error("The local studio backend is unavailable."); return r.json() as Promise<unknown>; });
  const message = reply as { result?: T; error?: string; message?: string };
  if (message.error) throw new StudioError(message.error, message.message ?? "The command failed.");
  return message.result as T;
};
export async function openWorkspace(): Promise<Workspace | null> {
  const host = native();
  if (host) {
    const reply = await host.invoke("studio_open") as { result?: Workspace; error?: string; message?: string } | null;
    if (reply === null) return null;
    if (reply.error) throw new Error(reply.message ?? "The workspace could not be opened.");
    return reply.result ?? null;
  }
  return command<Workspace>({ op: "workspace" });
}
export async function exitStudio(): Promise<void> { await native()?.invoke("studio_exit"); }
