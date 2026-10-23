import { useEffect, useState } from "react";
import { ErrorState } from "@jana/ui";
import { object, type Data } from "./model.js";
import { command } from "./transport.js";

/** A readable adjacency view; the shared CLI validator remains the authority for cross-pack cycles. */
export function KCGraph({ pack, record, onOpen }: { pack: string; record: Data; onOpen(id: string): void }) {
  const [nodes, setNodes] = useState<Data[] | null>(null), [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    setNodes(null); setError("");
    void command<{ nodes: Data[] }>({ op: "graph", pack }).then((reply) => {
      if (current) setNodes(reply.nodes);
    }).catch((failure: unknown) => { if (current) setError(String(failure)); });
    return () => { current = false; };
  }, [pack]);
  const current = nodes?.map((node) => node.id === record.id ? record : node) ?? [];
  return <details className="kc-graph"><summary>Prerequisite graph · {current.length} knowledge components</summary>
    {error ? <ErrorState message={error} /> : nodes === null ? <p role="status">Loading prerequisite graph…</p> :
      <ul aria-label="Knowledge component prerequisites">{current.map((node) => <li key={String(node.id)}>
        <button type="button" className="quiet" aria-current={node.id === record.id ? "true" : undefined}
          onClick={() => onOpen(String(node.id))}>{String(node.title ?? node.id)}</button>
        {Array.isArray(node.prerequisites) && node.prerequisites.length > 0 ? <ul>{node.prerequisites.map((edge) => {
          const id = String(object(edge).kc_id);
          return <li key={id}>requires <button type="button" className="quiet" onClick={() => onOpen(id)}>{id}</button>
            {` · ${String(object(edge).strength ?? "")}`}</li>;
        })}</ul> : <span className="text-meta"> · No prerequisites</span>}
      </li>)}</ul>}
  </details>;
}
