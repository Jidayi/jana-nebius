// The support upload page (OPS-24): sends the chosen report file with the ticket reference. Nothing else is sent.
"use strict";
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("upload");
  const result = document.getElementById("result");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const ticket = document.getElementById("ticket").value.trim().toUpperCase();
    const file = document.getElementById("file").files[0];
    if (!file) {
      result.textContent = "Choose the report file first.";
      return;
    }
    result.textContent = "Sending…";
    try {
      const reply = await fetch(`/v1/support/tickets/${encodeURIComponent(ticket)}/bundle`, {
        method: "PUT",
        headers: { "content-type": "application/octet-stream" },
        body: file,
        credentials: "omit",
      });
      const data = await reply.json().catch(() => ({}));
      if (reply.ok) {
        result.textContent = "Thank you. Support has your report.";
        form.reset();
      } else {
        result.textContent = (data.error && data.error.message) || "The report was not sent. Please try again.";
      }
    } catch {
      result.textContent = "The report was not sent. Check your connection and try again.";
    }
  });
});
