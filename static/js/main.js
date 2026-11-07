document.addEventListener("DOMContentLoaded", () => {
  // Start Now: smooth scroll to the guide
  document.querySelectorAll("[data-scroll]").forEach((a) =>
    a.addEventListener("click", (e) => {
      const target = document.querySelector(a.getAttribute("href"));
      if (target) { e.preventDefault(); target.scrollIntoView({ behavior: "smooth" }); }
    }));

  // Show times in the viewer's local time zone
  document.querySelectorAll("time.local-time").forEach((t) => {
    const d = new Date(t.getAttribute("datetime"));
    if (!isNaN(d)) t.textContent = d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  });

  // Check Content: text / PDF toggle
  const modeInput = document.getElementById("input_type");
  document.querySelectorAll(".toggle-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      const mode = btn.dataset.mode;
      modeInput.value = mode;
      document.querySelectorAll(".toggle-btn").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".panel").forEach((p) => {
        const on = p.dataset.panel === mode;
        p.hidden = !on;
        p.querySelectorAll("input, textarea").forEach((el) => (el.disabled = !on));   // only the visible input is submitted
      });
    }));

  // Live character counter
  const text = document.getElementById("text"), counter = document.getElementById("counter");
  if (text && counter) {
    const update = () => (counter.textContent = text.value.length.toLocaleString());
    text.addEventListener("input", update); update();
  }

  // Disable the check button while the server works (OCR and the LLM can take a few seconds)
  const form = document.getElementById("check-form"), btn = document.getElementById("check-btn");
  if (form && btn) form.addEventListener("submit", () => { btn.disabled = true; btn.textContent = "Checking..."; });

  // Copy button
  document.querySelectorAll("[data-copy]").forEach((b) =>
    b.addEventListener("click", async () => {
      const el = document.querySelector(b.dataset.copy);
      try { await navigator.clipboard.writeText(el.value); b.textContent = "Copied"; }
      catch { el.select(); document.execCommand("copy"); b.textContent = "Copied"; }
      setTimeout(() => (b.textContent = "Copy"), 1500);
    }));

  // Guidelines: the "Replace with" box only applies to "Must not use" rules
  const kind = document.getElementById("kind"), replace = document.getElementById("rule-replacement");
  if (kind && replace) {
    const toggle = () => { replace.hidden = kind.value !== "must_not_use"; };
    kind.addEventListener("change", toggle); toggle();
  }

  // Guidelines: colors
  const colors = document.getElementById("colors"), addColor = document.getElementById("add-color");
  if (colors) {
    const max = parseInt(colors.dataset.max, 10) || 5;
    const sync = () => {
      const rows = colors.querySelectorAll(".color-row");
      addColor.disabled = rows.length >= max;
      rows.forEach((r) => (r.querySelector(".remove-color").hidden = rows.length === 1));
    };
    colors.addEventListener("input", (e) => {
      const row = e.target.closest(".color-row"); if (!row) return;
      const pick = row.querySelector(".swatch"), hex = row.querySelector(".hex");
      if (e.target === pick) hex.value = pick.value.toUpperCase();
      else if (/^#?[0-9a-fA-F]{6}$/.test(hex.value.trim())) pick.value = "#" + hex.value.trim().replace("#", "");
    });
    colors.addEventListener("click", (e) => {
      if (e.target.classList.contains("remove-color")) { e.target.closest(".color-row").remove(); sync(); }
    });
    addColor.addEventListener("click", () => {
      const rows = colors.querySelectorAll(".color-row");
      if (rows.length >= max) return;
      const clone = rows[0].cloneNode(true);
      clone.querySelector(".hex").value = ""; clone.querySelector(".swatch").value = "#0033a0";
      colors.appendChild(clone); sync();
    });
    sync();
  }

  // Guidelines: logo preview
  const logo = document.getElementById("logo"), preview = document.getElementById("logo-preview");
  if (logo && preview) logo.addEventListener("change", () => {
    const f = logo.files[0];
    if (f) { preview.src = URL.createObjectURL(f); preview.hidden = false; }
  });
});
