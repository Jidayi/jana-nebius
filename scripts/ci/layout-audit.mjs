// Browser-side LOC-17 checks. Scrolling content and explicit ellipsis remain reachable by their defined controls.
export function layoutAudit(root) {
  const clipped = [], overlaps = [];
  const hidden = (el) => el.closest('.sr-only, [aria-hidden="true"], [inert]') || globalThis.getComputedStyle(el).visibility === "hidden";
  const walker = globalThis.document.createTreeWalker(root, globalThis.NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode, parent = node.parentElement;
    if (!parent || !node.textContent?.trim() || hidden(parent) || parent.closest("svg, .katex, script, style")) continue;
    const range = globalThis.document.createRange(); range.selectNodeContents(node);
    let scrollX = false, scrollY = false, ellipsis = false;
    for (let el = parent; el && root.contains(el); el = el.parentElement) {
      const css = globalThis.getComputedStyle(el), box = el.getBoundingClientRect();
      ellipsis ||= css.textOverflow === "ellipsis" || css.webkitLineClamp !== "none" && Number(css.webkitLineClamp) > 0;
      if (ellipsis) break;
      for (const rect of range.getClientRects()) {
        const cutX = !scrollX && ["hidden", "clip"].includes(css.overflowX) && (rect.left < box.left - 2 || rect.right > box.right + 2);
        const cutY = !scrollY && ["hidden", "clip"].includes(css.overflowY) && (rect.top < box.top - 2 || rect.bottom > box.bottom + 2);
        if (cutX || cutY) { clipped.push({ text: node.textContent.slice(0, 100), axis: cutX ? "x" : "y" }); break; }
      }
      scrollX ||= ["auto", "scroll"].includes(css.overflowX);
      scrollY ||= ["auto", "scroll"].includes(css.overflowY);
    }
    range.detach();
  }
  const controls = [];
  for (const el of root.querySelectorAll('button, input:not([type="hidden"]), select, textarea, a[href], [role="button"], [role="radio"], [role="textbox"]')) {
    if (hidden(el) || el.namespaceURI !== root.namespaceURI) continue;
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height) continue;
    let left = box.left, right = box.right, top = box.top, bottom = box.bottom;
    for (let ancestor = el.parentElement; ancestor && root.contains(ancestor); ancestor = ancestor.parentElement) {
      const css = globalThis.getComputedStyle(ancestor), bounds = ancestor.getBoundingClientRect();
      if (css.overflowX !== "visible") { left = Math.max(left, bounds.left); right = Math.min(right, bounds.right); }
      if (css.overflowY !== "visible") { top = Math.max(top, bounds.top); bottom = Math.min(bottom, bounds.bottom); }
    }
    if (right <= left || bottom <= top) continue;
    const layer = el.closest('[role="dialog"], [role="menu"]');
    const name = el.getAttribute("aria-label") ?? el.textContent?.trim().slice(0, 80) ?? el.tagName;
    for (const other of controls) {
      if (layer !== other.layer || el.contains(other.el) || other.el.contains(el)) continue;
      if (Math.min(right, other.right) - Math.max(left, other.left) > 2 && Math.min(bottom, other.bottom) - Math.max(top, other.top) > 2)
        overlaps.push({ first: other.name, second: name });
    }
    controls.push({ el, layer, name, left, right, top, bottom });
  }
  const css = globalThis.getComputedStyle(root), scale = Number(css.getPropertyValue("--text-scale"));
  const body = root.querySelector(".text-body"), maths = root.querySelector(".board-math");
  const bodyFont = body ? parseFloat(globalThis.getComputedStyle(body).fontSize) : null;
  const mathsFont = maths ? parseFloat(globalThis.getComputedStyle(maths).fontSize) : null;
  const scaleApplied = (bodyFont === null || Math.abs(bodyFont - parseFloat(css.getPropertyValue("--text-body")) * scale) < .1) && (mathsFont === null || Math.abs(mathsFont - parseFloat(css.getPropertyValue("--math-board")) * scale) < .1);
  return { clipped, overlaps, small: [], horizontal_overflow: root.scrollWidth > root.clientWidth + 2, scale, body_font: bodyFont, maths_font: mathsFont, scale_applied: scaleApplied };
}
