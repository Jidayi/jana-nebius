import { createRoot } from "react-dom/client";
import { LaunchScreen } from "@jana/ui/launch";
import "./studio.css";
const root = document.getElementById("root");
if (!root) throw new Error("Studio root is missing.");
const view = createRoot(root);
view.render(<LaunchScreen product="studio" failed={false} onRetry={() => window.location.reload()} />);
void import("./App.js").then(({ App }) => view.render(<App />))
  .catch(() => view.render(<LaunchScreen failed product="studio" onRetry={() => window.location.reload()} />));
