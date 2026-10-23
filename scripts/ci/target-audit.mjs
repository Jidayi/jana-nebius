// Browser-side measurement of actual control targets, including clickable labels and pseudo-element extensions.
export function targetAudit(root) {
  const small = []; let checked = 0;
  const elements = root.querySelectorAll("button, input, select, textarea, a[href], [role=button], [role=radio], [role=textbox], [data-part][tabindex]:not(dd), [data-step-id][tabindex]");
  for (const element of elements) {
    const css = globalThis.getComputedStyle(element), box = element.getBoundingClientRect();
    if (element.disabled || element.closest("[inert]") || !box.width || !box.height || css.visibility === "hidden" || css.display === "none") continue;
    checked++;
    let width = box.width, height = box.height;
    const part = element.getAttribute("data-part");
    const overlay = part && element.ownerSVGElement ? [...element.ownerSVGElement.querySelectorAll("[data-part-overlay-for]")].find((node) => node.getAttribute("data-part-overlay-for") === part) : null;
    if (overlay) { const rect = overlay.getBoundingClientRect(); width = Math.max(width, rect.width); height = Math.max(height, rect.height); }
    const label = element.labels?.[0] ?? element.closest("label");
    if (label) { const rect = label.getBoundingClientRect(); width = Math.max(width, rect.width); height = Math.max(height, rect.height); }
    if (element instanceof globalThis.HTMLElement) for (const pseudo of ["::before", "::after"]) {
      const style = globalThis.getComputedStyle(element, pseudo);
      if (["none", "normal"].includes(style.content) || style.position !== "absolute" || style.pointerEvents === "none") continue;
      const top = Number.parseFloat(style.top), bottom = Number.parseFloat(style.bottom), left = Number.parseFloat(style.left), right = Number.parseFloat(style.right);
      const w = Number.parseFloat(style.width), h = Number.parseFloat(style.height);
      if (Number.isFinite(w)) width = Math.max(width, w);
      if (Number.isFinite(h)) height = Math.max(height, h);
      if (Number.isFinite(left) && Number.isFinite(right)) width = Math.max(width, box.width - left - right);
      if (Number.isFinite(top) && Number.isFinite(bottom)) height = Math.max(height, box.height - top - bottom);
    }
    if (width < 43.9 || height < 43.9) small.push({ tag: element.tagName, text: element.getAttribute("aria-label") ?? element.textContent?.trim().slice(0, 100), width, height, class: element.getAttribute("class"), part: element.getAttribute("data-part") });
  }
  return { checked, small };
}
