// qa-dashboard runtime
// MANIFEST is injected by the generator into a preceding <script>.
(function () {
  "use strict";

  // ============================================================
  //  Utils
  // ============================================================
  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return Array.from(document.querySelectorAll(sel)); }
  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      if (k === "class") e.className = attrs[k];
      else if (k === "style") e.style.cssText = attrs[k];
      else if (k === "html") e.innerHTML = attrs[k];
      else if (k.startsWith("on") && typeof attrs[k] === "function") e.addEventListener(k.slice(2), attrs[k]);
      else if (k === "tabindex") e.setAttribute("tabindex", attrs[k]);
      else e.setAttribute(k, attrs[k]);
    }
    if (children) {
      for (const c of [].concat(children)) {
        if (c == null) continue;
        e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
      }
    }
    return e;
  }
  function escapeHtml(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
  }
  function fmtMs(ms) {
    if (ms == null) return "—";
    if (ms >= 60000) {
      const m = Math.floor(ms / 60000), s = Math.round((ms % 60000) / 1000);
      return `${m}m ${s}s`;
    }
    if (ms >= 1000) return (ms / 1000).toFixed(2) + " s";
    return ms + " ms";
  }
  function fmtIso(s) {
    if (!s) return "—";
    try {
      const d = new Date(s);
      return d.toLocaleString();
    } catch (_) { return s; }
  }
  function statusBadgeClass(s) {
    return {pass: "pass", fail: "fail", skip: "skip", error: "error", xfailed: "warn", xpassed: "info", in_progress: "info"}[s] || "info";
  }
  function statusSymbol(s) {
    return {pass: "✓", fail: "✕", skip: "○", error: "!", xfailed: "?", xpassed: "?"}[s] || "•";
  }
  function statusOrder(s) {
    return {fail: 0, error: 1, skip: 2, xfailed: 3, xpassed: 4, pass: 5, in_progress: 6}[s] ?? 9;
  }
  function statusClassNet(code) {
    if (code >= 500) return "err";
    if (code >= 400) return "warn";
    return "ok";
  }
  function jsonHighlight(obj) {
    if (obj == null) return '<span style="color: var(--text-3);">(empty)</span>';
    if (typeof obj === "string") return escapeHtml(obj);
    const s = JSON.stringify(obj, null, 2);
    return escapeHtml(s)
      .replace(/&quot;([^&]+)&quot;:/g, '<span class="json-key">&quot;$1&quot;</span>:')
      .replace(/: &quot;([^&]*)&quot;/g, ': <span class="json-str">&quot;$1&quot;</span>')
      .replace(/: (-?\d+\.?\d*)/g, ': <span class="json-num">$1</span>')
      .replace(/: (true|false|null)/g, ': <span class="json-bool">$1</span>');
  }

  // ============================================================
  //  Routing
  // ============================================================
  function parseHash() {
    const h = (window.location.hash || "").replace(/^#/, "");
    if (!h) return {view: "suite"};
    const parts = h.split("/");
    return {view: "test", testId: parts[0], tab: parts[1] || "steps", focus: parts[2] || null};
  }
  function setHash(testId, tab, focus) {
    let h = "";
    if (testId) {
      h = "#" + testId;
      if (tab) {
        h += "/" + tab;
        if (focus) h += "/" + focus;
      }
    }
    if (window.location.hash !== h) {
      history.pushState(null, "", h || window.location.pathname);
      applyRoute();
    }
  }

  // ============================================================
  //  Header & metrics
  // ============================================================
  function renderHeader(route) {
    const header = $("#header");
    const m = MANIFEST;
    const status = m.status || "in_progress";
    const left = el("div", {});
    const badgeText = status === "in_progress" ? "● Running" : (status === "pass" ? "✓ Passed" : status === "fail" ? "✕ Failed" : "! Error");
    const meta = el("div", {class: "header-meta"});
    const env = m.environment || {};
    const src = m.source || {};
    const cfg = m.config || {};
    meta.innerHTML = `${fmtIso(m.started_at)} · duration ${fmtMs(m.duration_ms)} ` +
      (src.branch ? `· branch <code>${escapeHtml(src.branch)}</code> ` : "") +
      (src.commit ? `· commit <code>${escapeHtml(src.commit)}</code> ` : "") +
      `· ${escapeHtml(env.platform || "")}`;

    if (route.view === "test") {
      const back = el("button", {class: "back-link", onclick: () => setHash(null)}, "← All tests");
      left.appendChild(back);
    }
    left.appendChild(el("div", {style: "display: flex; align-items: center; gap: 10px;"}, [
      el("span", {class: "badge " + statusBadgeClass(status)}, badgeText),
      el("span", {style: "font-size: 13px; color: var(--text-2);"}, `${m.run_id} · ${m.summary?.total ?? 0} tests`),
    ]));
    let titleNode;
    if (route.view === "test") {
      titleNode = el("h1", {id: "test-title"}, "Loading…");
    } else {
      titleNode = el("h1", {}, m.source?.repo || m.run_id);
    }
    left.appendChild(titleNode);
    left.appendChild(meta);

    const dlMenu = makeDownloadMenu();
    const right = el("div", {class: "header-actions"}, [
      dlMenu,
      el("button", {class: "btn", onclick: () => window.print()}, "⎙ Print"),
    ]);
    header.className = "header";
    header.replaceChildren(left, right);
  }

  function makeDownloadMenu() {
    const wrap = el("div", {class: "dl-wrap"});
    const btn = el("button", {class: "btn", "aria-haspopup": "menu"}, "⇩ Download ▾");
    const menu = el("div", {class: "dl-menu", role: "menu", hidden: ""});
    const items = [
      {label: "Save as PDF…",   fn: () => window.print()},
      {label: "Test summary (CSV)", fn: downloadCsv},
      {label: "Full report (JSON)", fn: downloadJson},
      {label: "Failed tests only (CSV)", fn: () => downloadCsv(true)},
    ];
    items.forEach(it => {
      const m = el("button", {class: "dl-item", role: "menuitem",
                              onclick: () => { menu.hidden = true; it.fn(); }}, it.label);
      menu.appendChild(m);
    });
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
    });
    document.addEventListener("click", () => { menu.hidden = true; });
    wrap.appendChild(btn);
    wrap.appendChild(menu);
    return wrap;
  }

  function _runId() { return (MANIFEST.run_id || "qa-dashboard-run"); }

  function _downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 0);
  }

  function _csvEscape(v) {
    if (v == null) return "";
    const s = String(v);
    if (/[",\n\r]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }

  function downloadCsv(failedOnly) {
    const cols = ["test_id", "nodeid", "name", "file", "status",
                  "started_at", "duration_ms", "step_count", "flow_count",
                  "screenshot_count", "tags", "error_summary"];
    const tests = (MANIFEST.tests || []).filter(t =>
      !failedOnly || t.status === "fail" || t.status === "error");
    const rows = [cols.join(",")];
    tests.forEach(t => {
      rows.push(cols.map(c => {
        let v = t[c];
        if (Array.isArray(v)) v = v.join("; ");
        return _csvEscape(v);
      }).join(","));
    });
    // UTF-8 BOM so Excel auto-detects encoding
    const blob = new Blob(["﻿" + rows.join("\n")], {type: "text/csv;charset=utf-8"});
    const fname = `${_runId()}${failedOnly ? "-failed" : ""}.csv`;
    _downloadBlob(blob, fname);
  }

  async function downloadJson() {
    // Best-effort: fetch all per-test JSONs and bundle them with the manifest.
    const bundle = {manifest: MANIFEST, tests: []};
    for (const t of MANIFEST.tests || []) {
      try {
        const resp = await fetch(`${TESTS_DIR}/${t.test_id}.json`);
        if (resp.ok) bundle.tests.push(await resp.json());
      } catch (_) { /* skip on file:// CORS */ }
    }
    const blob = new Blob([JSON.stringify(bundle, null, 2)],
                          {type: "application/json"});
    _downloadBlob(blob, `${_runId()}.json`);
  }

  function renderMetrics() {
    const s = MANIFEST.summary || {};
    const cards = [
      {label: "Total", value: s.total ?? 0, sub: "tests"},
      {label: "Passed", value: s.passed ?? 0, sub: ((s.pass_rate || 0) * 100).toFixed(1) + "% pass rate", cls: "pass"},
      {label: "Failed", value: s.failed ?? 0, sub: "click to filter", cls: "fail", click: () => {
        $("#suite-status").value = "fail";
        renderSuite();
        setHash(null);
      }},
      {label: "Skipped", value: s.skipped ?? 0, sub: "", cls: "warn"},
      {label: "Duration", value: fmtMs(MANIFEST.duration_ms), sub: "total run", isString: true},
      {label: "Errors", value: s.error ?? 0, sub: "setup/teardown", cls: (s.error ?? 0) > 0 ? "fail" : ""},
    ];
    const node = $("#metrics");
    node.replaceChildren(...cards.map(c => {
      const m = el("div", {class: "metric" + (c.click ? " clickable" : ""), onclick: c.click});
      m.appendChild(el("div", {class: "metric-label"}, c.label));
      const v = el("div", {class: "metric-value " + (c.cls || "")},
                   c.isString ? c.value : String(c.value));
      m.appendChild(v);
      if (c.sub) m.appendChild(el("div", {class: "metric-sub"}, c.sub));
      return m;
    }));
  }

  // ============================================================
  //  Suite view
  // ============================================================
  function renderSuite() {
    const view = $("#view");
    const tests = (MANIFEST.tests || []).slice();
    const filter = ($("#suite-filter")?.value || "").toLowerCase().trim();
    const statusFilter = $("#suite-status")?.value || "";
    const sortBy = $("#suite-sort")?.value || "status";

    let filtered = tests.filter(t => {
      if (statusFilter && t.status !== statusFilter) return false;
      if (filter) {
        const hay = (t.name + " " + (t.nodeid || "") + " " + (t.tags || []).join(" ")).toLowerCase();
        if (!hay.includes(filter)) return false;
      }
      return true;
    });

    if (sortBy === "status") {
      filtered.sort((a, b) => statusOrder(a.status) - statusOrder(b.status) || (a.started_at || "").localeCompare(b.started_at || ""));
    } else if (sortBy === "name") {
      filtered.sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortBy === "duration") {
      filtered.sort((a, b) => (b.duration_ms || 0) - (a.duration_ms || 0));
    } else if (sortBy === "order") {
      filtered.sort((a, b) => (a.started_at || "").localeCompare(b.started_at || ""));
    }

    // Build the toolbar once and reuse
    if (!$("#suite-filter")) {
      const banner = MANIFEST.status === "in_progress"
        ? el("div", {class: "banner"}, `Run in progress — last update ${fmtIso(MANIFEST.started_at)}`)
        : null;
      const toolbar = el("div", {class: "suite-toolbar"}, [
        el("input", {id: "suite-filter", type: "text", placeholder: "Filter tests…", oninput: renderSuite, "aria-label": "Filter tests"}),
        el("select", {id: "suite-status", onchange: renderSuite, "aria-label": "Status filter"}, [
          el("option", {value: ""}, "All"),
          el("option", {value: "fail"}, "Failed"),
          el("option", {value: "pass"}, "Passed"),
          el("option", {value: "skip"}, "Skipped"),
          el("option", {value: "error"}, "Errors"),
        ]),
        el("select", {id: "suite-sort", onchange: renderSuite, "aria-label": "Sort"}, [
          el("option", {value: "status"}, "Status (failed first)"),
          el("option", {value: "order"}, "Execution order"),
          el("option", {value: "name"}, "Name"),
          el("option", {value: "duration"}, "Duration (slowest)"),
        ]),
        el("span", {id: "suite-info", class: "suite-toolbar-info"}, ""),
      ]);
      const table = el("div", {class: "suite-table"}, [
        el("div", {class: "suite-head"}, [
          el("div", {}, "Status"), el("div", {}, "Test"), el("div", {style: "text-align: right;"}, "Duration"),
          el("div", {style: "text-align: right;"}, "Steps"), el("div", {style: "text-align: right;"}, "API"),
          el("div", {style: "text-align: right;"}, "Screenshots"),
        ]),
        el("div", {id: "suite-body"}),
      ]);
      const children = banner ? [banner, toolbar, table] : [toolbar, table];
      view.replaceChildren(...children);
      return renderSuite();  // re-enter now that controls exist
    }

    $("#suite-info").textContent = `${filtered.length} of ${tests.length}`;
    const body = $("#suite-body");
    if (!filtered.length) {
      body.replaceChildren(el("div", {class: "empty"},
        tests.length === 0 ? "No tests were collected by pytest." : "No tests match the current filter."));
      return;
    }

    body.replaceChildren(...filtered.map(t => {
      const row = el("div", {
        class: "suite-row " + t.status,
        tabindex: "0",
        role: "button",
        "aria-label": `${t.status} ${t.name}`,
        onclick: () => setHash(t.test_id),
        onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setHash(t.test_id); } },
      });
      row.appendChild(el("div", {}, el("span", {class: "badge " + statusBadgeClass(t.status)}, statusSymbol(t.status) + " " + t.status)));
      const nameCell = el("div", {class: "name-cell"});
      nameCell.appendChild(el("div", {class: "name"}, t.name));
      nameCell.appendChild(el("div", {class: "file"}, t.file || t.nodeid));
      if (t.error_summary) {
        nameCell.appendChild(el("div", {class: "err"}, t.error_summary));
      }
      row.appendChild(nameCell);
      row.appendChild(el("div", {class: "dur"}, fmtMs(t.duration_ms)));
      row.appendChild(el("div", {class: "num"}, String(t.step_count ?? 0)));
      row.appendChild(el("div", {class: "num"}, String(t.flow_count ?? 0)));
      row.appendChild(el("div", {class: "num"}, String(t.screenshot_count ?? 0)));
      return row;
    }));
  }

  // ============================================================
  //  Test view
  // ============================================================
  const testCache = {};
  async function loadTest(testId) {
    if (testCache[testId]) return testCache[testId];
    try {
      const resp = await fetch(`${TESTS_DIR}/${testId}.json`);
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const rec = await resp.json();
      testCache[testId] = rec;
      return rec;
    } catch (e) {
      return {__error: e.message || String(e)};
    }
  }

  async function renderTestView(route) {
    const view = $("#view");
    view.replaceChildren(el("div", {class: "empty"}, "Loading test…"));
    const rec = await loadTest(route.testId);
    if (rec.__error) {
      view.replaceChildren(el("div", {class: "empty"},
        `Could not load test ${route.testId}: ${rec.__error}. ` +
        `If you opened this report directly from disk (file://), serving via a local HTTP server may be required for some browsers.`));
      return;
    }
    if (rec.schema_version !== 1) {
      view.replaceChildren(el("div", {class: "empty"},
        `This test record uses schema_version ${rec.schema_version}; this viewer supports 1. Regenerate via \`qa-dashboard <run-dir>\`.`));
      return;
    }

    const titleEl = $("#test-title");
    if (titleEl) {
      let title = rec.name;
      if (rec.parameters) {
        const ps = Object.entries(rec.parameters).map(([k, v]) => `${k}=${v}`).join(", ");
        title += ` [${ps}]`;
      }
      titleEl.textContent = title;
    }

    // Build the tab bar
    const tabs = [
      ["steps", "Test steps", rec.steps.length],
      ["network", "Network", rec.flows.length],
      ["timeline", "Timeline", null],
      ["screens", "Screenshots", rec.screenshots.length],
      ["logs", "Console logs", rec.console.length],
      ["env", "Environment", null],
    ];
    const tabBar = el("div", {class: "tabs", role: "tablist"});
    tabs.forEach(([id, label, count]) => {
      const t = el("button", {
        class: "tab" + (id === route.tab ? " active" : ""),
        role: "tab",
        "aria-selected": id === route.tab ? "true" : "false",
        "aria-controls": "panel-" + id,
        onclick: () => setHash(rec.test_id, id),
      }, label);
      if (count !== null) t.appendChild(el("span", {class: "tab-count"}, String(count)));
      tabBar.appendChild(t);
    });
    // Keyboard arrow nav
    tabBar.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        const buttons = Array.from(tabBar.querySelectorAll(".tab"));
        const idx = buttons.indexOf(document.activeElement);
        if (idx < 0) return;
        const next = (idx + (e.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
        buttons[next].focus(); buttons[next].click();
        e.preventDefault();
      }
    });

    const summary = renderTestSummary(rec);
    const panel = el("div", {id: "panel-" + route.tab, role: "tabpanel"});
    view.replaceChildren(summary, tabBar, panel);

    // Render the active tab
    if (route.tab === "steps") renderStepsTab(panel, rec, route.focus);
    else if (route.tab === "network") renderNetworkTab(panel, rec, route.focus);
    else if (route.tab === "timeline") renderTimelineTab(panel, rec);
    else if (route.tab === "screens") renderScreensTab(panel, rec);
    else if (route.tab === "logs") renderLogsTab(panel, rec);
    else if (route.tab === "env") renderEnvTab(panel, rec);
    else renderStepsTab(panel, rec);
  }

  function renderTestSummary(rec) {
    const wrap = el("div", {style: "margin-bottom: 18px;"});
    const meta = el("div", {style: "display:flex;gap:12px;flex-wrap:wrap;align-items:center;font-size:13px;color:var(--text-2);"});
    meta.appendChild(el("span", {class: "badge " + statusBadgeClass(rec.status)}, statusSymbol(rec.status) + " " + rec.status));
    meta.appendChild(el("span", {}, rec.nodeid));
    meta.appendChild(el("span", {}, "· " + fmtMs(rec.duration_ms)));
    if (rec.tags && rec.tags.length) {
      meta.appendChild(el("span", {}, "· " + rec.tags.map(t => "@" + t).join(" ")));
    }
    wrap.appendChild(meta);
    if (rec.outcome && rec.outcome.longrepr && (rec.status === "fail" || rec.status === "error")) {
      wrap.appendChild(el("div", {style: "margin-top:14px;"}, el("div", {class: "section-h"}, "Failure")));
      wrap.appendChild(el("pre", {class: "error-block"}, rec.outcome.longrepr));
    }
    return wrap;
  }

  // ---- Steps tab ---------------------------------------------
  function renderStepsTab(panel, rec, focus) {
    if (!rec.steps.length) {
      panel.replaceChildren(el("div", {class: "empty"}, "No steps recorded for this test."));
      return;
    }
    const list = el("div", {class: "step-list"}, [
      el("div", {class: "step-list-header"}, [el("span", {}, "Steps"),
        el("input", {class: "step-filter", id: "step-filter", placeholder: "Filter…", oninput: () => renderStepListBody(list, rec, current)})]),
      el("div", {id: "step-list-body"}),
    ]);
    const detail = el("div", {class: "detail", id: "step-detail"});
    panel.replaceChildren(el("div", {class: "master-detail"}, [list, detail]));
    let initialId = parseInt(focus, 10);
    if (!Number.isFinite(initialId)) {
      const firstFail = rec.steps.find(s => s.status === "fail");
      initialId = firstFail ? firstFail.id : rec.steps[0].id;
    }
    let current = initialId;
    renderStepListBody(list, rec, current);
    renderStepDetail(detail, rec, current);

    function onSelect(id) {
      current = id;
      renderStepListBody(list, rec, current);
      renderStepDetail(detail, rec, current);
      setHash(rec.test_id, "steps", String(id));
    }
    list.addEventListener("click", (e) => {
      const row = e.target.closest(".step");
      if (row && row.dataset.step) onSelect(parseInt(row.dataset.step, 10));
    });
    list.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        const row = e.target.closest(".step");
        if (row) { e.preventDefault(); onSelect(parseInt(row.dataset.step, 10)); }
      }
    });
  }

  function renderStepListBody(list, rec, currentId) {
    const q = (list.querySelector(".step-filter")?.value || "").toLowerCase().trim();
    const body = list.querySelector("#step-list-body");
    const items = rec.steps.filter(s => !q || s.name.toLowerCase().includes(q));
    if (!items.length) {
      body.replaceChildren(el("div", {class: "empty"}, "No steps match."));
      return;
    }
    body.replaceChildren(...items.map(s => {
      const sym = statusSymbol(s.status);
      const meta = s.status === "skip"
        ? `skipped${s.skip_reason ? " — " + s.skip_reason : ""}`
        : `${fmtMs(s.duration_ms)} · ${(s.flow_ids || []).length} API · ${(s.screenshot_ids || []).length} shot${(s.screenshot_ids || []).length !== 1 ? "s" : ""}`;
      const row = el("div", {
        class: "step" + (s.id === currentId ? " active" : ""),
        "data-step": String(s.id),
        tabindex: "0",
      });
      row.appendChild(el("span", {class: "step-pill " + s.status}, sym));
      row.appendChild(el("div", {class: "step-body"}, [
        el("div", {class: "step-name"}, `${s.id}. ${s.name}`),
        el("div", {class: "step-meta " + (s.status === "fail" ? "fail" : "")}, meta),
      ]));
      return row;
    }));
  }

  function renderStepDetail(detail, rec, stepId) {
    const s = rec.steps.find(x => x.id === stepId);
    if (!s) {
      detail.replaceChildren(el("div", {class: "empty"}, "Step not found."));
      return;
    }
    const kids = [];
    kids.push(el("div", {style: "display:flex;align-items:center;gap:10px;margin-bottom:4px;"}, [
      el("span", {class: "badge " + statusBadgeClass(s.status)}, statusSymbol(s.status) + " " + s.status),
      el("span", {style: "font-size:12px;color:var(--text-2);"}, `Step ${s.id} of ${rec.steps.length}`),
    ]));
    kids.push(el("h2", {}, s.name));
    kids.push(el("div", {class: "detail-meta"},
      `${fmtIso(s.started_at)} · ${fmtMs(s.duration_ms)} · ${(s.flow_ids || []).length} API calls`));

    if (s.error) {
      kids.push(el("div", {class: "section-h", style: "color:var(--fail);"}, "Error"));
      kids.push(el("pre", {class: "error-block"},
        `${s.error.type}: ${s.error.message}` + (s.error.traceback ? "\n\n" + s.error.traceback : "")));
    }
    if (s.skip_reason) {
      kids.push(el("div", {class: "section-h"}, "Skip reason"));
      kids.push(el("div", {}, s.skip_reason));
    }
    if (s.substeps && s.substeps.length) {
      kids.push(el("div", {class: "section-h"}, "Sub-steps"));
      s.substeps.forEach(ss => {
        kids.push(el("div", {class: "substep"}, [
          el("span", {class: "substep-dot " + ss.status}),
          el("span", {}, ss.name),
          el("span", {class: "substep-time"}, fmtMs(ss.duration_ms)),
        ]));
      });
    }
    if (s.screenshot_ids && s.screenshot_ids.length) {
      kids.push(el("div", {class: "section-h"}, "Screenshots"));
      const strip = el("div", {class: "screenshot-strip"});
      s.screenshot_ids.forEach(sid => {
        const sh = rec.screenshots.find(x => x.id === sid);
        if (!sh) return;
        strip.appendChild(makeShot(sh, rec, s.status));
      });
      kids.push(strip);
    }
    if (s.flow_ids && s.flow_ids.length) {
      kids.push(el("div", {class: "section-h"}, `Network during this step (${s.flow_ids.length})`));
      const flows = s.flow_ids.map(fid => rec.flows.find(f => f.id === fid)).filter(Boolean);
      flows.slice(0, 8).forEach(f => {
        const row = el("div", {
          style: "display:grid;grid-template-columns:50px 1fr 50px 70px;gap:10px;padding:7px 0;border-bottom:1px solid var(--border);font-size:12px;align-items:center;cursor:pointer;",
          onclick: () => setHash(rec.test_id, "network", "flow_" + f.id),
        });
        row.appendChild(el("span", {class: "method " + f.method}, f.method));
        row.appendChild(el("span", {class: "net-url"}, [
          el("span", {class: "net-host"}, f.host || ""), document.createTextNode(f.path || f.url || ""),
        ]));
        row.appendChild(el("span", {class: "status " + statusClassNet(f.status_code)}, String(f.status_code)));
        row.appendChild(el("span", {class: "net-dur"}, fmtMs(f.duration_ms)));
        kids.push(row);
      });
      if (flows.length > 8) {
        kids.push(el("div", {style: "font-size:12px;color:var(--text-3);margin-top:8px;"},
          `+ ${flows.length - 8} more — see Network tab`));
      }
    }
    detail.replaceChildren(...kids);
  }

  function makeShot(sh, rec, stepStatus) {
    const wrap = el("div", {
      class: "shot" + (stepStatus === "fail" ? " fail" : ""),
      tabindex: "0",
      role: "button",
      "aria-label": `Open screenshot ${sh.id}`,
      onclick: () => openLightbox(rec, sh.id),
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openLightbox(rec, sh.id); } },
    });
    const img = el("img", {src: sh.asset_path, alt: sh.label || sh.id, loading: "lazy"});
    img.addEventListener("error", () => {
      img.replaceWith(el("div", {style: "width:60px;height:100px;background:var(--surface);border-radius:var(--r-sm);display:flex;align-items:center;justify-content:center;color:var(--text-3);"}, "missing"));
    });
    wrap.appendChild(img);
    wrap.appendChild(el("div", {class: "shot-cap"}, sh.label || sh.id.split("_").slice(-3).join("_")));
    return wrap;
  }

  // ---- Network tab -------------------------------------------
  function renderNetworkTab(panel, rec, focus) {
    if (!rec.flows.length) {
      panel.replaceChildren(el("div", {class: "empty"}, "No network activity captured for this test."));
      return;
    }
    const expanded = new Set();
    if (focus && focus.startsWith("flow_")) {
      expanded.add(parseInt(focus.slice(5), 10));
    }

    const toolbar = el("div", {class: "net-toolbar"}, [
      el("input", {type: "text", id: "net-filter", placeholder: "Filter by URL, host, or body…", oninput: redraw, "aria-label": "Filter"}),
      el("select", {id: "net-method", onchange: redraw, "aria-label": "Method"},
         ["", "GET", "POST", "PUT", "PATCH", "DELETE"].map(m => el("option", {value: m}, m || "All methods"))),
      el("select", {id: "net-status", onchange: redraw, "aria-label": "Status"}, [
        el("option", {value: ""}, "All statuses"),
        el("option", {value: "2"}, "2xx"), el("option", {value: "3"}, "3xx"),
        el("option", {value: "4"}, "4xx"), el("option", {value: "5"}, "5xx"),
      ]),
      el("select", {id: "net-step", onchange: redraw, "aria-label": "Step"},
         [el("option", {value: ""}, "All steps")].concat(
           rec.steps.map(s => el("option", {value: String(s.id)}, `Step ${s.id}: ${s.name}`)))),
      el("span", {id: "net-info", class: "net-toolbar-info"}),
    ]);
    const table = el("div", {class: "net-table"}, [
      el("div", {class: "net-head"}, [
        el("div", {}, "Method"), el("div", {}, "URL"), el("div", {}, "Status"),
        el("div", {style: "text-align: right;"}, "Time"), el("div", {}, "Step"), el("div", {}, "Waterfall"),
      ]),
      el("div", {id: "net-body"}),
    ]);
    panel.replaceChildren(toolbar, table);
    redraw();

    function redraw() {
      const q = ($("#net-filter").value || "").toLowerCase().trim();
      const m = $("#net-method").value;
      const sFilter = $("#net-status").value;
      const stepFilter = $("#net-step").value;
      const filtered = rec.flows.filter(f => {
        if (m && f.method !== m) return false;
        if (sFilter && String(f.status_code)[0] !== sFilter) return false;
        if (stepFilter && String(f.step_id) !== stepFilter) return false;
        if (q) {
          const hay = (f.host + " " + f.url + " " + JSON.stringify(f.request?.body || "") + " " + JSON.stringify(f.response?.body || "")).toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      });
      $("#net-info").textContent = `${filtered.length} of ${rec.flows.length}`;
      const body = $("#net-body");
      if (!filtered.length) {
        body.replaceChildren(el("div", {class: "empty"}, "No flows match the filter."));
        return;
      }
      const maxDur = Math.max(...rec.flows.map(f => f.duration_ms || 0), 1);
      const minTs = Math.min(...rec.flows.map(f => Date.parse(f.timestamp) || 0));
      const maxTs = Math.max(...rec.flows.map(f => (Date.parse(f.timestamp) || 0) + (f.duration_ms || 0)));
      const span = Math.max(maxTs - minTs, 1);
      body.replaceChildren(...filtered.map(f => makeFlowRow(f, rec, expanded, maxDur, minTs, span, redraw)));
    }
  }

  function makeFlowRow(f, rec, expanded, maxDur, minTs, span, redraw) {
    const row = el("div", {
      class: "net-row" + (expanded.has(f.id) ? " expanded" : ""),
      tabindex: "0",
      onclick: () => { if (expanded.has(f.id)) expanded.delete(f.id); else expanded.add(f.id); redraw(); },
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); row.click(); } },
    });
    row.appendChild(el("span", {class: "method " + f.method}, f.method));
    row.appendChild(el("span", {class: "net-url"}, [
      el("span", {class: "net-host"}, f.host || ""),
      document.createTextNode(f.path || f.url || ""),
    ]));
    row.appendChild(el("span", {class: "status " + statusClassNet(f.status_code)}, String(f.status_code)));
    row.appendChild(el("span", {class: "net-dur"}, fmtMs(f.duration_ms)));
    row.appendChild(el("span", {class: "net-step"}, f.step_id ? "#" + f.step_id : "—"));
    const ts = Date.parse(f.timestamp) || minTs;
    const leftPct = ((ts - minTs) / span) * 100;
    const widthPct = Math.max(0.5, ((f.duration_ms || 0) / span) * 100);
    const bar = el("div", {class: "waterfall"});
    bar.appendChild(el("div", {
      class: "waterfall-bar",
      style: `left:${leftPct.toFixed(1)}%;width:${widthPct.toFixed(1)}%;background:${
        f.status_code >= 500 ? "var(--fail)" : f.status_code >= 400 ? "var(--warn)" : "#378ADD"};`,
    }));
    row.appendChild(bar);

    if (expanded.has(f.id)) {
      const exp = el("div", {class: "net-expand"});
      const inner = el("div", {class: "net-expand-inner"});
      // request
      const reqWrap = el("div", {});
      reqWrap.appendChild(el("div", {class: "section-h", style: "margin-top:0;"}, "Request"));
      reqWrap.appendChild(el("div", {class: "kv"},
        [el("span", {class: "k"}, f.method + " "), el("span", {class: "v"}, f.host + (f.path || ""))]));
      for (const [k, v] of Object.entries(f.request?.headers || {})) {
        const kv = el("div", {class: "kv"});
        kv.innerHTML = `<span class="k">${escapeHtml(k)}:</span> <span class="v">${escapeHtml(String(v))}</span>`;
        reqWrap.appendChild(kv);
      }
      const reqBody = el("div", {class: "body-block"});
      reqBody.innerHTML = renderBody(f.request);
      reqWrap.appendChild(reqBody);

      // response
      const respWrap = el("div", {});
      const respH = el("div", {class: "section-h", style: "margin-top:0;"});
      respH.innerHTML = `Response · <span class="status ${statusClassNet(f.status_code)}">${f.status_code}</span> · ${fmtMs(f.duration_ms)}`;
      respWrap.appendChild(respH);
      for (const [k, v] of Object.entries(f.response?.headers || {})) {
        const kv = el("div", {class: "kv"});
        kv.innerHTML = `<span class="k">${escapeHtml(k)}:</span> <span class="v">${escapeHtml(String(v))}</span>`;
        respWrap.appendChild(kv);
      }
      const respBody = el("div", {class: "body-block"});
      respBody.innerHTML = renderBody(f.response);
      respWrap.appendChild(respBody);
      inner.appendChild(reqWrap); inner.appendChild(respWrap);
      exp.appendChild(inner);
      row.appendChild(exp);
    }
    return row;
  }

  function renderBody(side) {
    if (!side) return jsonHighlight(null);
    switch (side.body_encoding) {
      case "json": return jsonHighlight(side.body);
      case "text": return escapeHtml(side.body || "");
      case "empty": return jsonHighlight(null);
      case "omitted": return `<span style="color:var(--text-3);">(body omitted — ${side.body_size_bytes} bytes)</span>`;
      case "base64": return `<span style="color:var(--text-3);">(${side.body_size_bytes} bytes binary, base64)</span>`;
      default: return escapeHtml(String(side.body || ""));
    }
  }

  // ---- Timeline tab -----------------------------------------
  function renderTimelineTab(panel, rec) {
    if (!rec.steps.length && !rec.flows.length) {
      panel.replaceChildren(el("div", {class: "empty"}, "No timeline data."));
      return;
    }
    const startMs = Date.parse(rec.started_at);
    const endMs = Date.parse(rec.ended_at);
    const span = Math.max(endMs - startMs, 1);
    const W = 1300;
    const xOf = (iso, durMs) => {
      const t = Date.parse(iso);
      const x = ((t - startMs) / span) * W;
      const w = Math.max(2, ((durMs || 0) / span) * W);
      return {x: isFinite(x) ? x : 0, w};
    };
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W + 20} 280`);
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "280");

    // Axis baseline
    const axis = document.createElementNS(svgNS, "line");
    axis.setAttribute("x1", 0); axis.setAttribute("y1", 252);
    axis.setAttribute("x2", W); axis.setAttribute("y2", 252);
    axis.setAttribute("stroke", "var(--border-strong)"); axis.setAttribute("stroke-width", "1");
    svg.appendChild(axis);

    function label(x, y, text, color) {
      const t = document.createElementNS(svgNS, "text");
      t.setAttribute("x", x); t.setAttribute("y", y); t.setAttribute("font-size", "10");
      t.setAttribute("fill", color || "var(--text-3)"); t.setAttribute("font-family", "var(--font-mono)");
      t.textContent = text;
      return t;
    }
    // Ticks: 0%, 25%, 50%, 75%, 100%
    [0, 0.25, 0.5, 0.75, 1].forEach(p => {
      svg.appendChild(label(W * p, 268, fmtMs(Math.round(span * p))));
    });
    // Section labels
    svg.appendChild(label(0, 22, "Test steps", "var(--text-2)"));
    svg.appendChild(label(0, 90, "API calls", "var(--text-2)"));
    svg.appendChild(label(0, 160, "Screenshots", "var(--text-2)"));

    // Step rects
    rec.steps.forEach(s => {
      const {x, w} = xOf(s.started_at, s.duration_ms);
      const fill = s.status === "fail" ? "#c43c3b" : s.status === "skip" ? "#b07215" : "#1d9e75";
      const r = document.createElementNS(svgNS, "rect");
      r.setAttribute("x", x); r.setAttribute("y", 32);
      r.setAttribute("width", w); r.setAttribute("height", 22);
      r.setAttribute("rx", "2"); r.setAttribute("fill", fill);
      r.setAttribute("class", "tl-step");
      r.addEventListener("mouseenter", (e) => showTip(e, `${s.id}. ${s.name} — ${s.status} · ${fmtMs(s.duration_ms)}`));
      r.addEventListener("mousemove", moveTip);
      r.addEventListener("mouseleave", hideTip);
      r.addEventListener("click", () => setHash(rec.test_id, "steps", String(s.id)));
      svg.appendChild(r);
    });

    // Flow rects
    rec.flows.forEach(f => {
      const {x, w} = xOf(f.timestamp, f.duration_ms);
      const fill = f.status_code >= 500 ? "#c43c3b" : f.status_code >= 400 ? "#b07215" : "#378ADD";
      const r = document.createElementNS(svgNS, "rect");
      r.setAttribute("x", x); r.setAttribute("y", 100);
      r.setAttribute("width", Math.max(2, w)); r.setAttribute("height", 22);
      r.setAttribute("rx", "1"); r.setAttribute("fill", fill);
      r.setAttribute("class", "tl-flow");
      r.addEventListener("mouseenter", (e) => showTip(e, `${f.method} ${f.host}${f.path} — ${f.status_code} · ${fmtMs(f.duration_ms)}`));
      r.addEventListener("mousemove", moveTip);
      r.addEventListener("mouseleave", hideTip);
      r.addEventListener("click", () => setHash(rec.test_id, "network", "flow_" + f.id));
      svg.appendChild(r);
    });

    // Screenshot dots
    rec.screenshots.forEach(sh => {
      const t = Date.parse(sh.captured_at);
      const x = ((t - startMs) / span) * W;
      if (!isFinite(x)) return;
      const c = document.createElementNS(svgNS, "circle");
      c.setAttribute("cx", x); c.setAttribute("cy", 180); c.setAttribute("r", "5");
      c.setAttribute("fill", "#7f77dd"); c.setAttribute("class", "tl-shot");
      c.addEventListener("mouseenter", (e) => showTip(e, sh.label || sh.id));
      c.addEventListener("mousemove", moveTip);
      c.addEventListener("mouseleave", hideTip);
      c.addEventListener("click", () => openLightbox(rec, sh.id));
      svg.appendChild(c);
    });

    const card = el("div", {class: "timeline-card"});
    card.appendChild(el("div", {class: "card-title"}, "Stacked timeline · steps · API calls · screenshots"));
    card.appendChild(svg);
    card.appendChild(el("div", {class: "timeline-legend"}, [
      legendDot("#1d9e75", "Passed step"),
      legendDot("#c43c3b", "Failed step"),
      legendDot("#b07215", "Skipped step / 4xx API"),
      legendDot("#378ADD", "2xx API"),
      legendDot("#7f77dd", "Screenshot"),
    ]));
    panel.replaceChildren(card);
  }
  function legendDot(color, text) {
    return el("span", {}, [el("span", {class: "dot", style: `background:${color};`}), document.createTextNode(text)]);
  }

  // ---- Screens tab ------------------------------------------
  function renderScreensTab(panel, rec) {
    if (!rec.screenshots.length) {
      panel.replaceChildren(el("div", {class: "empty"}, "No screenshots for this test."));
      return;
    }
    const grid = el("div", {class: "shots-grid"});
    rec.screenshots.forEach(sh => {
      const step = rec.steps.find(s => s.id === sh.step_id);
      grid.appendChild(makeShot(sh, rec, step ? step.status : "pass"));
    });
    panel.replaceChildren(grid);
  }

  // ---- Logs tab ---------------------------------------------
  function renderLogsTab(panel, rec) {
    if (!rec.console.length) {
      panel.replaceChildren(el("div", {class: "empty"}, "No console logs captured."));
      return;
    }
    const levels = ["DEBUG", "INFO", "WARN", "ERROR"];
    const states = {DEBUG: false, INFO: true, WARN: true, ERROR: true};
    const filter = el("div", {class: "console-filter"});
    levels.forEach(lvl => {
      const pill = el("button", {
        class: "pill" + (states[lvl] ? " on" : ""),
        type: "button",
        onclick: () => { states[lvl] = !states[lvl]; pill.classList.toggle("on", states[lvl]); apply(); },
      }, lvl);
      filter.appendChild(pill);
    });
    const cons = el("div", {class: "console"});
    cons.dataset.showDebug = states.DEBUG;
    cons.dataset.showInfo = states.INFO;
    cons.dataset.showWarn = states.WARN;
    cons.dataset.showError = states.ERROR;
    rec.console.forEach(l => {
      const line = el("div", {class: "console-line", "data-level": l.level});
      line.appendChild(el("span", {class: "ts"}, l.ts));
      line.appendChild(el("span", {class: "lvl " + l.level}, l.level));
      line.appendChild(el("span", {}, l.message));
      cons.appendChild(line);
    });
    function apply() {
      cons.dataset.showDebug = states.DEBUG;
      cons.dataset.showInfo = states.INFO;
      cons.dataset.showWarn = states.WARN;
      cons.dataset.showError = states.ERROR;
    }
    panel.replaceChildren(filter, cons);
  }

  // ---- Env tab ----------------------------------------------
  function renderEnvTab(panel, rec) {
    const env = MANIFEST.environment || {};
    const src = MANIFEST.source || {};
    function card(title, rows) {
      const c = el("div", {class: "env-card"}, el("div", {class: "env-h"}, title));
      rows.forEach(([k, v]) => {
        if (v == null || v === "") return;
        c.appendChild(el("div", {class: "env-row"}, [
          el("span", {class: "k"}, k), el("span", {class: "v"}, String(v)),
        ]));
      });
      return c;
    }
    const cards = [];
    if (rec.device) cards.push(card("Device", Object.entries(rec.device)));
    if (rec.app) cards.push(card("Application", Object.entries(rec.app)));
    cards.push(card("Test harness", [
      ["Runner", "pytest " + (env.pytest || "?")],
      ["Python", env.python],
      ["Platform", env.platform],
      ["mitmproxy", env.mitmproxy],
      ["qa-dashboard", env.qa_dashboard],
    ]));
    cards.push(card("Source", [
      ["Repository", src.repo],
      ["Branch", src.branch],
      ["Commit", src.commit],
      ["Commit message", src.commit_message],
      ["Triggered by", src.trigger],
    ]));
    panel.replaceChildren(el("div", {class: "env-grid"}, cards));
  }

  // ============================================================
  //  Lightbox
  // ============================================================
  let _lbOrder = [];
  let _lbIdx = 0;
  function openLightbox(rec, shotId) {
    _lbOrder = rec.screenshots.slice();
    _lbIdx = _lbOrder.findIndex(s => s.id === shotId);
    if (_lbIdx < 0) _lbIdx = 0;
    showLightbox();
    document.addEventListener("keydown", lbKey);
  }
  function lbKey(e) {
    if (e.key === "Escape") closeLightbox();
    else if (e.key === "ArrowRight") { _lbIdx = (_lbIdx + 1) % _lbOrder.length; showLightbox(); }
    else if (e.key === "ArrowLeft") { _lbIdx = (_lbIdx - 1 + _lbOrder.length) % _lbOrder.length; showLightbox(); }
  }
  function showLightbox() {
    const sh = _lbOrder[_lbIdx];
    const lb = $("#lightbox");
    lb.hidden = false;
    const content = el("div", {class: "lb-content"}, [
      el("img", {src: sh.asset_path, alt: sh.label || sh.id}),
      el("div", {class: "lb-cap"}, `${sh.label || sh.id} · ${_lbIdx + 1}/${_lbOrder.length}`),
    ]);
    lb.replaceChildren(
      el("button", {class: "lb-close", "aria-label": "Close", onclick: closeLightbox}, "✕"),
      el("button", {class: "lb-prev", "aria-label": "Previous", onclick: () => { _lbIdx = (_lbIdx - 1 + _lbOrder.length) % _lbOrder.length; showLightbox(); }}, "‹"),
      el("button", {class: "lb-next", "aria-label": "Next", onclick: () => { _lbIdx = (_lbIdx + 1) % _lbOrder.length; showLightbox(); }}, "›"),
      content,
    );
    lb.onclick = (e) => { if (e.target === lb) closeLightbox(); };
  }
  function closeLightbox() {
    const lb = $("#lightbox");
    lb.hidden = true;
    lb.replaceChildren();
    document.removeEventListener("keydown", lbKey);
  }

  // ============================================================
  //  Tooltip
  // ============================================================
  function showTip(e, text) {
    const tt = $("#tooltip");
    tt.textContent = text; tt.hidden = false;
    moveTip(e);
  }
  function moveTip(e) {
    const tt = $("#tooltip");
    if (tt.hidden) return;
    tt.style.left = (e.clientX + 12) + "px";
    tt.style.top = (e.clientY + 12) + "px";
  }
  function hideTip() { $("#tooltip").hidden = true; }

  // ============================================================
  //  Routing
  // ============================================================
  function applyRoute() {
    const route = parseHash();
    renderHeader(route);
    renderMetrics();
    if (route.view === "suite") renderSuite();
    else renderTestView(route);
  }
  window.addEventListener("hashchange", applyRoute);
  window.addEventListener("popstate", applyRoute);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyRoute);
  } else {
    applyRoute();
  }
})();
