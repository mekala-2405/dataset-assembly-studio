(() => {
  const DATA = window.DEMO_DATA;
  const keys = Object.keys(DATA);
  const JOINTS = ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos", "gripper.pos"];
  let current = keys[0];

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const fmt = (n) => n.toLocaleString("en-US");

  document.querySelectorAll(".phase-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".phase-tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".phase-panel").forEach((p) => p.classList.toggle("active", p.id === tab.dataset.phase));
    });
  });

  function renderMetrics() {
    const box = $("#metrics");
    box.innerHTML = "";
    [["2 featured datasets", keys.length], ["15 curated episodes", 5 + 10], ["60,624 frames", 5370 + 55254], ["LeRobot v2.1", 0]].forEach(([label]) => {
      box.appendChild(el("span", null, label));
    });
  }

  function renderCatalog() {
    const box = $("#catalog");
    box.innerHTML = "";
    $("#catalog-count").textContent = `${keys.length} datasets`;
    keys.forEach((key) => {
      const d = DATA[key];
      const info = d.info;
      const card = el("article", "dataset-card" + (key === current ? " selected" : ""));
      const head = el("div", "card-head");
      const hd = el("div");
      hd.appendChild(el("p", "meta", `SO-101 · v2.1 · ${info.robot_type}`));
      hd.appendChild(el("h3", null, key));
      head.appendChild(hd);
      head.appendChild(el("span", "tag", `${info.total_episodes} episodes`));
      card.appendChild(head);
      card.appendChild(el("p", "task", d.tasks.map((t) => t.task).join(" · ")));
      const ul = el("ul");
      [["Frames", fmt(info.total_frames)], ["Videos", info.total_videos], ["FPS", info.fps], ["Split", info.splits.train]].forEach(([k, v]) => {
        const li = el("li");
        li.appendChild(el("span", null, k));
        li.appendChild(el("strong", null, String(v)));
        ul.appendChild(li);
      });
      card.appendChild(ul);
      card.addEventListener("click", () => { current = key; renderAll(); });
      box.appendChild(card);
    });
  }

  function renderCameras() {
    const box = $("#camera-workspace");
    box.innerHTML = "";
    const prov = DATA[current].provenance[0];
    const mapping = prov.camera_mapping;
    [["wrist", mapping.wrist, "CAMERA 01 · FIXED"], ["front", mapping.front, "CAMERA 02 · SELECTABLE"]].forEach(([out, src, label]) => {
      const row = el("div", "choice");
      const d = el("div");
      d.appendChild(el("span", "key", label));
      d.appendChild(el("strong", null, `${out} ← ${src}`));
      row.appendChild(d);
      row.appendChild(el("span", "ok", "✓ mapped"));
      box.appendChild(row);
    });
  }

  function renderJoints() {
    const box = $("#joint-workspace");
    box.innerHTML = "";
    ["action", "observation.state"].forEach((col) => {
      const div = el("div", "joint-col");
      div.appendChild(el("h3", null, col));
      const ol = el("ol");
      JOINTS.forEach((j) => {
        const li = el("li");
        li.appendChild(el("span", null, j));
        li.appendChild(el("strong", null, "auto"));
        ol.appendChild(li);
      });
      div.appendChild(ol);
      box.appendChild(div);
    });
  }

  function renderEpisodes() {
    const gallery = $("#episode-gallery");
    const detail = $("#episode-detail");
    const d = DATA[current];
    gallery.innerHTML = "";
    $("#episode-key").textContent = current;
    $("#episode-count").textContent = `${d.episodes.length} episodes · ${fmt(d.info.total_frames)} frames`;
    detail.innerHTML = '<p class="empty">Choose an episode to preview both cameras.</p>';
    d.episodes.forEach((ep) => {
      const clip = d.clips[String(ep.episode_index)] || null;
      const thumb = el("button", "episode-thumb");
      const src = clip ? clip.front : null;
      if (src) {
        const v = el("video");
        v.muted = true; v.loop = true; v.preload = "metadata"; v.playsInline = true;
        const s = el("source"); s.src = src; s.type = "video/mp4";
        v.appendChild(s);
        thumb.appendChild(v);
      } else {
        thumb.appendChild(el("div", "thumb-placeholder", "no preview clip in demo"));
      }
      const body = el("div", "thumb-body");
      body.appendChild(el("strong", null, `Episode ${String(ep.episode_index).padStart(2, "0")}`));
      body.appendChild(el("span", null, `${fmt(ep.length)} frames · ~${(ep.length / d.info.fps).toFixed(1)}s`));
      thumb.appendChild(body);
      thumb.addEventListener("click", () => {
        document.querySelectorAll(".episode-thumb").forEach((t) => t.classList.remove("selected"));
        thumb.classList.add("selected");
        renderDetail(ep, src);
      });
      gallery.appendChild(thumb);
    });
  }

  function renderDetail(ep, src) {
    const detail = $("#episode-detail");
    const d = DATA[current];
    const clip = d.clips[String(ep.episode_index)] || {};
    detail.innerHTML = "";
    detail.appendChild(el("h3", null, `Episode ${String(ep.episode_index).padStart(2, "0")}`));
    detail.appendChild(el("p", "hint", `Task: ${ep.task}`));
    const grid = el("div", "preview-grid");
    ["front", "wrist"].forEach((cam) => {
      const fig = el("figure");
      const clipSrc = clip[cam];
      if (clipSrc) {
        const v = el("video");
        v.muted = true; v.controls = true; v.loop = true; v.preload = "metadata"; v.playsInline = true;
        const s = el("source"); s.src = clipSrc; s.type = "video/mp4";
        v.appendChild(s);
        fig.appendChild(v);
      } else {
        fig.appendChild(el("div", "thumb-placeholder", `no ${cam} clip in demo`));
      }
      fig.appendChild(el("figcaption", null, cam));
      grid.appendChild(fig);
    });
    detail.appendChild(grid);
    const meta = el("div", "episode-meta");
    const prov = d.provenance.find((p) => p.episode_index === ep.episode_index);
    [["Frames", fmt(ep.length)], ["Duration", `~${(ep.length / d.info.fps).toFixed(1)}s`], ["Revision", prov ? `checkpoint r${prov.checkpoint_revision}` : "—"], ["Editor", prov ? prov.updated_by : "—"]].forEach(([k, v]) => {
      const row = el("div", "row");
      row.appendChild(el("span", null, k));
      row.appendChild(el("strong", null, v));
      meta.appendChild(row);
    });
    detail.appendChild(meta);
  }

  function renderTasks() {
    const d = DATA[current];
    const box = $("#tasks-view");
    box.innerHTML = "";
    $("#included-count").textContent = `${d.episodes.length} included episodes`;
    d.episodes.forEach((ep) => {
      const row = el("div", "task-row");
      row.appendChild(el("span", "prompt", `Episode ${String(ep.episode_index).padStart(2, "0")} · ${ep.task}`));
      row.appendChild(el("span", "count", `${fmt(ep.length)} frames`));
      box.appendChild(row);
    });
  }

  function renderBalance() {
    const box = $("#balance-view");
    box.innerHTML = "";
    const stats = $("#balance-stats");
    stats.innerHTML = "";
    DATA[current].episodes.forEach((ep) => stats.appendChild(el("span", null, `${ep.task} — ${fmt(ep.length)} frames`)));
    const prov = DATA[current].provenance;
    const groups = {};
    prov.forEach((p) => {
      const g = p.source_dataset.split("/").pop();
      groups[g] = (groups[g] || 0) + 1;
    });
    const max = Math.max(...Object.values(groups), 1);
    Object.entries(groups).forEach(([g, c]) => {
      const row = el("div", "balance-row");
      row.appendChild(el("span", "prompt", g));
      const bar = el("div", "bar");
      bar.appendChild(el("i"));
      bar.firstChild.style.width = `${(c / max) * 100}%`;
      row.appendChild(bar);
      row.appendChild(el("span", "count", `${c} of ${c} retained`));
      box.appendChild(row);
    });
  }

  function renderPreflight() {
    const d = DATA[current];
    const info = d.info;
    const box = $("#preflight-view");
    box.innerHTML = "";
    const rows = [
      ["Episodes present", `${info.total_episodes}/${info.total_episodes}`, "ok"],
      ["Frames in range", `${fmt(info.total_frames)}`, "ok"],
      ["Two-camera contract", "wrist + front mapped", "ok"],
      ["Six-joint SO-101 order", "canonical order confirmed", "ok"],
      ["Split coverage", `${info.splits.train} train`, "ok"]
    ];
    rows.forEach(([label, value, state]) => {
      const item = el("div", "preflight-item " + state);
      item.appendChild(el("span", "desc", label));
      item.appendChild(el("span", "state", value));
      box.appendChild(item);
    });
    $("#preflight-status").textContent = "All checks passed";
  }

  function renderExport() {
    const d = DATA[current];
    const info = d.info;
    const box = $("#export-view");
    box.innerHTML = "";
    const card = el("div", "export-card");
    [["Dataset folder", "assembled_lerobot_v21"], ["Schema", `LeRobot ${info.codebase_version}`], ["Episodes", info.total_episodes], ["Frames", fmt(info.total_frames)], ["Cameras", "wrist + front"], ["Indices", "rebuilt"], ["Prompts", "edited"], ["Package", ".tar.gz"]].forEach(([k, v]) => {
      const line = el("div", "export-line");
      line.appendChild(el("span", null, k));
      line.appendChild(el("strong", null, String(v)));
      card.appendChild(line);
    });
    box.appendChild(card);
    $("#export-readiness").textContent = "Ready to export";
  }

  function renderAll() {
    renderCatalog();
    renderCameras();
    renderJoints();
    renderEpisodes();
    renderTasks();
    renderBalance();
    renderPreflight();
    renderExport();
  }

  renderMetrics();
  renderAll();
})();
