// PRV-29: shipping source/capability audit. This does not attest compiled/signed platform permissions.
import ts from "typescript";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
const roots = ["apps/desktop/src", "apps/desktop/src-tauri", "services/agent-core/agent_core", "packages/client-core/src", "packages/ui/src"];
const extensions = new Set([".py", ".rs", ".ts", ".tsx", ".js", ".mjs", ".toml", ".json", ".plist", ".entitlements", ".xml"]);
function inspect(source, file) {
 const found = new Set(), aliases = new Map(), constants = new Map();
 const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
 const constant = (node) => {
  if (!node) return null;
  if (ts.isStringLiteralLike(node)) return node.text;
  if (ts.isIdentifier(node)) return constants.get(node.text) ?? null;
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
   const a = constant(node.left), b = constant(node.right); return a === null || b === null ? null : a + b;
  }
  return null;
 };
 const name = (node, depth = 0) => {
  if (!node || depth > 12) return "";
  if (ts.isIdentifier(node)) { const alias = aliases.get(node.text); return alias ? name(alias, depth + 1) : node.text; }
  if (ts.isPropertyAccessExpression(node)) return `${name(node.expression, depth + 1)}.${node.name.text}`;
  if (ts.isElementAccessExpression(node)) return `${name(node.expression, depth + 1)}.${constant(node.argumentExpression) ?? "?"}`;
  if (ts.isParenthesizedExpression(node)) return name(node.expression, depth + 1);
  return "";
 };
 const collect = (node) => {
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
   aliases.set(node.name.text, node.initializer); const value = constant(node.initializer); if (value !== null) constants.set(node.name.text, value);
  }
  if (ts.isVariableDeclaration(node) && ts.isObjectBindingPattern(node.name) && node.initializer) {
   for (const binding of node.name.elements) if (ts.isIdentifier(binding.name)) {
    const property = binding.propertyName ?? binding.name;
    if (ts.isIdentifier(property) || ts.isStringLiteral(property)) aliases.set(binding.name.text, ts.factory.createElementAccessExpression(node.initializer, ts.factory.createStringLiteral(property.text)));
   }
  }
  ts.forEachChild(node, collect);
 };
 collect(tree);
 const check = (node) => {
  if (ts.isCallExpression(node) || ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) {
   const called = name(ts.isCallExpression(node) ? node.expression : node);
   if (/(?:^|\.)(?:getDisplayMedia|capturePage|captureScreen|captureWindow)$/.test(called) || /desktopCapturer\.(?:getSources|capture)/.test(called)) found.add("screen/window capture API");
   if (/(?:^|\.)clipboard\.(?:read|readText)$/.test(called)) found.add("programmatic clipboard read");
  }
  ts.forEachChild(node, check);
 };
 check(tree);
 const patterns = [
  ["native screen/window capture API", /\b(?:CGDisplayCreateImage|CGDisplayCreateImageForRect|ScreenCaptureKit|CGWindowListCreateImage|CGDisplayStreamCreate|SCStream|SCScreenshotManager|GraphicsCaptureItem|Direct3D11CaptureFramePool|PrintWindow|BitBlt)\b|(?:Windows|windows)(?:::|\.)Graphics(?:::|\.)Capture/],
  ["screen capture library", /\b(?:from|import)\s+(?:PIL\.ImageGrab|pyautogui|mss|pyscreenshot)\b|\bImageGrab\s*\.\s*grab\b|^\s*(?:screenshots|xcap|scrap)\s*=/m],
  ["capture/clipboard shell command", /["'](?:screencapture|pbpaste|wl-paste|xclip)["']|\bGet-Clipboard\b|["'](?:capture_screen|capture_window|screen_capture)["']/],
  ["screen or accessibility entitlement", /<key>[^<]*(?:screen[._-]?(?:capture|recording)|accessibility)[^<]*<\/key>/i],
  ["screen capture permission or legacy constraint", /Name\s*=\s*["']graphicsCapture["']|(?:mozMediaSource|mediaSource)\s*:\s*["'](?:screen|window|application)["']/i],
  ["clipboard read capability", /["'][^"']*(?:clipboard[^"']*(?:allow-read|read-text)|allow-(?:screen|window)-capture)[^"']*["']/i],
 ];
 for (const [reason, pattern] of patterns) if (pattern.test(source)) found.add(reason);
 return [...found].sort();
}
async function files(root) {
 const out = [];
 for (const entry of await readdir(root, { withFileTypes: true })) {
  if (["target", "dist", "node_modules", "__pycache__", "generated", "contracts", "tests"].includes(entry.name)) continue;
  const file = path.join(root, entry.name);
  if (entry.isDirectory()) out.push(...await files(file)); else if (extensions.has(path.extname(file))) out.push(file);
 }
 return out;
}
let rows;
if (process.argv.includes("--probe")) {
 let input = ""; for await (const chunk of process.stdin) input += chunk;
 rows = JSON.parse(input).map(({ path: file, source }) => ({ path: file, findings: inspect(source, file) }));
} else {
 rows = [];
 for (const root of roots) for (const file of await files(root)) rows.push({ path: file, findings: inspect(await readFile(file, "utf8"), file) });
}
const failures = rows.filter((r) => r.findings.length > 0);
process.stdout.write(JSON.stringify({ files: rows.length, roots, failures }));
if (failures.length > 0 && !process.argv.includes("--probe")) process.exitCode = 1;
