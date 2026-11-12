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

  // Sidebar menu: opens from the three-line button; closes on the backdrop, the close button or Escape
  const sidebar = document.getElementById("sidebar"), toggle = document.getElementById("menu-toggle");
  if (sidebar && toggle) {
    const backdrop = document.getElementById("sidebar-backdrop");
    const setOpen = (open) => {
      sidebar.classList.toggle("open", open);
      backdrop.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) document.getElementById("menu-close").focus();
    };
    toggle.addEventListener("click", () => setOpen(!sidebar.classList.contains("open")));
    backdrop.addEventListener("click", () => setOpen(false));
    document.getElementById("menu-close").addEventListener("click", () => { setOpen(false); toggle.focus(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && sidebar.classList.contains("open")) setOpen(false); });
    const alertsMenu = document.getElementById("alerts-menu"), meta = document.querySelector('meta[name="csrf-token"]');
    if (alertsMenu && meta) alertsMenu.addEventListener("toggle", () => {
      if (!alertsMenu.open || alertsMenu.dataset.unseen === "0") return;
      fetch(alertsMenu.dataset.seenUrl, { method: "POST", headers: { "X-CSRF-Token": meta.content } }).then(() => {
        alertsMenu.dataset.unseen = "0";
        document.querySelectorAll(".hamburger .badge, #alerts-menu .badge").forEach((b) => b.remove());
      });
    });
  }

  // Dashboard banner: slides change every few seconds; pauses on hover, on keyboard focus and during the tutorial
  const banner = document.getElementById("banner");
  if (banner) {
    const track = banner.querySelector(".slides"), slides = Array.from(banner.querySelectorAll(".slide"));
    const dots = Array.from(banner.querySelectorAll(".banner-dot"));
    const wait = parseInt(banner.dataset.interval, 10) || 7000;
    let current = 0, timer = 0, paused = false;
    const go = (n) => {
      current = (n + slides.length) % slides.length;
      track.style.transform = `translateX(-${current * 100}%)`;
      slides.forEach((s, i) => { s.inert = i !== current; });
      dots.forEach((d, i) => d.classList.toggle("active", i === current));
    };
    const restart = () => {
      clearInterval(timer);
      timer = setInterval(() => { if (!paused && !document.querySelector(".tour-card")) go(current + 1); }, wait);
    };
    dots.forEach((d, i) => d.addEventListener("click", () => { go(i); restart(); }));
    banner.addEventListener("mouseenter", () => { paused = true; });
    banner.addEventListener("mouseleave", () => { paused = false; });
    banner.addEventListener("focusin", () => { paused = true; });
    banner.addEventListener("focusout", () => { paused = false; });
    go(0);
    restart();
  }
});

document.addEventListener("DOMContentLoaded", () => {
  // Remarks: "View remark" opens a small box beside the link; closes on outside click or Escape
  let openPop = null;
  const closePop = () => {
    if (!openPop) return;
    openPop.pop.hidden = true;
    openPop.link.setAttribute("aria-expanded", "false");
    openPop = null;
  };
  const placePop = () => {
    if (!openPop) return;
    const { link, pop } = openPop, r = link.getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight) { closePop(); return; }
    const pw = pop.offsetWidth, ph = pop.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
    let left, top;
    if (r.right + 10 + pw <= vw - 8) {
      left = r.right + 10;
      top = Math.max(8, Math.min(r.top - 6, vh - ph - 8));
    } else {
      left = Math.max(8, Math.min(r.left, vw - pw - 8));
      top = r.bottom + 8 + ph <= vh - 8 ? r.bottom + 8 : Math.max(8, r.top - 8 - ph);
    }
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  };
  document.querySelectorAll(".remark-link").forEach((link) =>
    link.addEventListener("click", (e) => {
      e.stopPropagation();
      const pop = link.parentElement.querySelector(".remark-pop");
      if (openPop && openPop.link === link) { closePop(); return; }
      closePop();
      pop.hidden = false;
      link.setAttribute("aria-expanded", "true");
      openPop = { link, pop };
      placePop();
    }));
  document.addEventListener("click", (e) => { if (openPop && !openPop.pop.contains(e.target)) closePop(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePop(); });
  window.addEventListener("scroll", placePop, { passive: true });
  window.addEventListener("resize", placePop);

  // Remarks: a remark is required to reject, optional to approve
  document.querySelectorAll("[data-remark-required]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const box = btn.closest("form").querySelector(".remark-input");
      box.required = btn.dataset.remarkRequired === "1";
      box.setCustomValidity("");
    }));

  // Tutorial tour (dashboard only)
  const config = document.getElementById("tour-config");
  if (!config) return;
  const meta = document.querySelector('meta[name="csrf-token"]');
  let steps = [], index = 0, hole, card, blocker, frame = 0, active = false;

  const collect = () =>
    Array.from(document.querySelectorAll("[data-tour-title]"))
      .filter((el) => el.getClientRects().length)
      .sort((a, b) => Number(a.dataset.tourOrder) - Number(b.dataset.tourOrder));

  const markSeen = () => {
    if (!meta || !config.dataset.seenUrl) return;
    fetch(config.dataset.seenUrl, { method: "POST", headers: { "X-CSRF-Token": meta.content } }).catch(() => {});
  };

  const place = () => {
    if (!active) return;
    const el = steps[index], r = el.getBoundingClientRect(), pad = 8;
    hole.style.top = r.top - pad + "px";
    hole.style.left = r.left - pad + "px";
    hole.style.width = r.width + pad * 2 + "px";
    hole.style.height = r.height + pad * 2 + "px";
    hole.style.borderRadius = getComputedStyle(el).borderRadius === "0px" ? "28px" : getComputedStyle(el).borderRadius;
    const cw = card.offsetWidth, ch = card.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
    let top, left = Math.max(12, Math.min(r.left, vw - cw - 12));
    if (r.bottom + pad + 14 + ch <= vh) top = r.bottom + pad + 14;
    else if (r.top - pad - 14 - ch >= 0) top = r.top - pad - 14 - ch;
    else { top = vh - ch - 18; left = Math.max(12, (vw - cw) / 2); }
    card.style.top = top + "px";
    card.style.left = left + "px";
  };
  const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(place); };

  const show = () => {
    const el = steps[index], last = index === steps.length - 1;
    card.querySelector("h3").textContent = el.dataset.tourTitle;
    card.querySelector("p").textContent = el.dataset.tourText || "";
    card.querySelector(".tour-count").textContent = `${index + 1}/${steps.length}`;
    card.querySelector(".tour-next").textContent = last ? "Done" : "Next";
    el.scrollIntoView({ block: "center", inline: "center", behavior: "auto" });
    place();
    card.querySelector(".tour-next").focus({ preventScroll: true });
  };

  const end = () => {
    if (!active) return;
    active = false;
    cancelAnimationFrame(frame);
    [hole, card, blocker].forEach((n) => n && n.remove());
    window.removeEventListener("resize", schedule);
    window.removeEventListener("scroll", schedule);
    document.removeEventListener("keydown", onKey);
    markSeen();
  };
  const onKey = (e) => {
    if (e.key === "Escape") end();
    else if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); next(); }
  };
  const next = () => {
    if (index >= steps.length - 1) { end(); return; }
    index += 1;
    show();
  };

  const start = () => {
    steps = collect();
    if (!steps.length || active) return;
    active = true;
    index = 0;
    blocker = document.createElement("div");
    blocker.className = "tour-blocker";
    hole = document.createElement("div");
    hole.className = "tour-hole";
    card = document.createElement("div");
    card.className = "tour-card";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-live", "polite");
    card.innerHTML = '<h3></h3><p></p><div class="tour-foot"><span class="tour-count"></span>' +
      '<span class="tour-buttons"><button type="button" class="btn btn-small btn-on-dark tour-skip">Skip Tour</button>' +
      '<button type="button" class="btn btn-small tour-next">Next</button></span></div>';
    document.body.append(blocker, hole, card);
    card.querySelector(".tour-skip").addEventListener("click", end);
    card.querySelector(".tour-next").addEventListener("click", next);
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, { passive: true });
    document.addEventListener("keydown", onKey);
    show();
  };

  if (config.dataset.auto === "1") {
    if (new URLSearchParams(location.search).has("tour")) history.replaceState(null, "", location.pathname);
    start();
  }
});
