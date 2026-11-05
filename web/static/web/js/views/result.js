// Renders a recommendation (live POST result or stored GET result):
// summary banner, 3D view with loading sequence, box stats, ranked options,
// packing instructions and rejected boxes with their reasons.

import { fmt, h, icon, strategyLabel, strategySelect, withBusy } from "../dom.js";
import { PackingViewer } from "../viewer.js";

const FALLBACK_PALETTE = ["#ff6a1f", "#2f5bff", "#ffc72c", "#f23c3c", "#26262c", "#8fa8ff"];

/** Item colours from the active theme (CSS ``--item-palette``): the four accents, then ink and tints. */
export function palette() {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--item-palette");
  const tones = raw.split(",").map((t) => t.trim()).filter(Boolean);
  return tones.length ? tones : FALLBACK_PALETTE;
}

/** One stable tone per product across the recommendation and its alternatives. */
export function colorMap(payload) {
  const ids = new Set();
  for (const option of [payload.recommendation, ...(payload.alternatives || [])]) {
    for (const p of (option && option.placements) || []) ids.add(p.product_id);
  }
  const tones = palette();
  const sorted = [...ids].sort((a, b) => a - b);
  const map = new Map(sorted.map((id, i) => [id, tones[i % tones.length]]));
  return (id) => map.get(id) || tones[0];
}

export function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

const FEASIBILITY = {
  proven_infeasible: ["Cannot fit (proven)", "badge-danger"],
  heuristic_failure: ["No arrangement found", "badge-warning"],
  invalid_configuration: ["Invalid box data", ""],
};

export function renderResult(payload, { strategies = [], onRerun = null } = {}) {
  const root = h("div", { class: "stack", "data-testid": "result" });
  const rec = payload.recommendation;
  root.append(hero(payload, { strategies, onRerun }));

  if (!rec) {
    if (payload.rejected_boxes && payload.rejected_boxes.length) root.append(rejectedCard(payload.rejected_boxes));
    return root;
  }

  const colorFor = colorMap(payload);
  const options = [rec, ...(payload.alternatives || [])];
  const viewerSlot = h("div");
  const statsSlot = h("div");
  const instructionsSlot = h("div");
  const optionButtons = options.map((option, index) =>
    h(
      "button",
      { class: "option", type: "button", "data-testid": "option", onclick: () => select(index) },
      h("span", { class: "rank" }, option.rank),
      h(
        "span",
        null,
        h("div", { class: "t" }, option.box_name, " ", h("span", { class: "muted mono" }, option.box_code)),
        h(
          "div",
          { class: "s" },
          fmt.dims(option.box_dimensions.length, option.box_dimensions.width, option.box_dimensions.height),
          index === 0 ? " · recommended" : "",
        ),
      ),
      h("span", { class: "p num" }, fmt.inr(option.cost), h("small", null, `${fmt.pct(option.utilization)} full`)),
    ),
  );

  let viewer = null;
  function select(index) {
    if (viewer) viewer.dispose();
    const option = options[index];
    const view = viewerCard(option, index, colorFor);
    viewer = view.viewer;
    viewerSlot.replaceChildren(view.el);
    statsSlot.replaceChildren(statsCard(option));
    instructionsSlot.replaceChildren(instructionsCard(option, colorFor, view));
    optionButtons.forEach((button, i) => button.classList.toggle("active", i === index));
  }

  root.append(
    viewerSlot,
    h(
      "div",
      { class: "grid-2" },
      statsSlot,
      h(
        "section",
        { class: "card" },
        h(
          "div",
          { class: "card-head" },
          h("h2", null, "Feasible boxes"),
          h("span", { class: "muted" }, `ranked by ${strategyLabel(payload.strategy).toLowerCase()}`),
        ),
        h("div", { class: "card-body option-list", "data-testid": "options" }, optionButtons),
      ),
    ),
    instructionsSlot,
  );
  if (payload.rejected_boxes && payload.rejected_boxes.length) root.append(rejectedCard(payload.rejected_boxes));
  select(0);
  return root;
}

function hero(payload, { strategies, onRerun }) {
  const rec = payload.recommendation;
  const summary = payload.summary;
  const meta = [
    h("a", { href: `#/orders/${payload.order_id}` }, payload.order_number),
    payload.strategy ? strategyLabel(payload.strategy) : null,
    summary ? `${summary.boxes_evaluated} boxes checked in ${fmt.num(summary.execution_time_ms, 0)} ms` : null,
    payload.generated_at ? `computed ${fmt.date(payload.generated_at)}` : null,
  ].filter(Boolean);

  const rerun = onRerun && strategies.length
    ? (() => {
        const select = strategySelect(strategies, payload.strategy || strategies[0], { "aria-label": "Ranking strategy", style: { width: "auto" } });
        const button = h("button", { class: "btn btn-sm", type: "button" }, icon("refresh", 14), "Re-run");
        button.addEventListener("click", () => withBusy(button, "Packing…", () => onRerun(select.value)));
        return h("div", { class: "row" }, select, button);
      })()
    : null;

  const left = rec
    ? h(
        "div",
        null,
        h("div", { class: "eyebrow" }, "Recommended box"),
        h("div", { class: "title", "data-testid": "recommended-box" }, rec.box_name, " ", h("span", { class: "mono muted" }, rec.box_code)),
        h("div", { class: "sub" }, `${fmt.dims(rec.box_dimensions.length, rec.box_dimensions.width, rec.box_dimensions.height)} · ${fmt.pct(rec.utilization)} of the volume used · ${plural(rec.placements.length, "item")}`),
      )
    : h(
        "div",
        null,
        h("div", { class: "eyebrow" }, "No feasible box"),
        h("div", { class: "title", "data-testid": "recommended-box" }, "No active box can hold this order"),
        h(
          "div",
          { class: "sub" },
          payload.rejected_boxes
            ? `All ${payload.rejected_boxes.length} active boxes were rejected. The reasons are listed below.`
            : "Add a larger box or split the order, then run the recommendation again.",
        ),
      );

  return h(
    "section",
    { class: `hero${rec ? "" : " fail"}` },
    h("span", { class: "badge-circle", "aria-hidden": "true" }, icon(rec ? "package" : "close", 24)),
    h("div", { class: "stack", style: { gap: "8px" } }, left, h("div", { class: "row muted", style: { fontSize: "13px" } }, meta.map((m, i) => [i ? " · " : "", m])), rerun),
    rec ? h("div", { class: "price num" }, fmt.inr(rec.cost), h("small", null, "per box")) : null,
  );
}

function viewerCard(option, index, colorFor) {
  const host = h("div", { class: "viewer", "data-testid": "viewer" });
  const dims = option.box_dimensions;
  const counts = new Map();
  for (const p of option.placements) counts.set(p.product_id, { sku: p.sku, n: (counts.get(p.product_id)?.n || 0) + 1 });

  const overlay = h(
    "div",
    { class: "viewer-overlay" },
    h("span", { class: "chip" }, `${option.box_code} · ${fmt.dims(dims.length, dims.width, dims.height)}`),
    h(
      "span",
      { class: "chip axes" },
      [["x", "length →"], ["y", "width ↗"], ["z", "height ↑"]].map(([axis, label]) => h("span", null, h("i"), `${axis} ${label}`)),
    ),
  );
  host.append(overlay);
  const viewer = new PackingViewer(host);
  viewer.show(option, colorFor);

  const total = option.placements.length;
  const range = h("input", { type: "range", min: 0, max: total, step: 1, value: total, "aria-label": "Loading step" });
  const label = h("span", { class: "step-label", "data-testid": "step-label" });
  const playButton = h("button", { class: "btn btn-sm", type: "button", "aria-label": "Play loading sequence" }, icon("play", 14), "Play");
  let timer = null;

  function setStep(step) {
    range.value = String(step);
    viewer.setStep(step);
    if (step >= total) label.textContent = `${total === 1 ? "The item is" : `All ${total} items are`} placed. Drag to rotate, scroll to zoom.`;
    else if (step === 0) label.textContent = "Empty box: press Play to see the loading order.";
    else {
      const p = option.placements[step - 1];
      label.textContent = `Step ${step} of ${total}: ${p.sku} at x ${fmt.num(p.position.x)}, y ${fmt.num(p.position.y)}, z ${fmt.num(p.position.z)} cm`;
    }
  }
  function stop() {
    window.clearInterval(timer);
    timer = null;
    playButton.replaceChildren(icon("play", 14), "Play");
  }
  playButton.addEventListener("click", () => {
    if (timer) return stop();
    let step = Number(range.value) >= total ? 0 : Number(range.value);
    setStep(step);
    playButton.replaceChildren(icon("pause", 14), "Pause");
    timer = window.setInterval(() => {
      if (!range.isConnected) return stop();
      step += 1;
      setStep(step);
      if (step >= total) stop();
    }, 650);
  });
  range.addEventListener("input", () => {
    if (timer) stop();
    setStep(Number(range.value));
  });
  setStep(total);

  const el = h(
    "section",
    { class: "card viewer-card" },
    h(
      "div",
      { class: "card-head" },
      h("h2", null, "3D packing plan ", index === 0 ? h("span", { class: "badge badge-accent" }, "Recommended") : h("span", { class: "badge" }, `Alternative #${option.rank}`)),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => viewer.fit(), title: "Reset view" }, icon("reset", 14), "Reset view"),
    ),
    h("div", { class: "card-body viewer-body" }, host),
    h(
      "div",
      { class: "card-body legend", style: { paddingTop: "10px", paddingBottom: "10px", borderTop: "1px solid var(--border)" } },
      [...counts.entries()].map(([productId, { sku, n }]) => h("span", null, h("i", { style: { background: colorFor(productId) } }), `${sku} × ${n}`)),
    ),
    h("div", { class: "stepbar" }, playButton, range, label),
  );
  return { el, viewer, setStep };
}

function meter(label, value, max, display, warnAbove = 0.9) {
  const ratio = max > 0 ? Math.min(value / max, 1) : 0;
  return h(
    "div",
    { class: "meter" },
    h("div", { class: "meter-top" }, h("span", null, label), h("strong", { class: "num" }, display)),
    h(
      "div",
      { class: "meter-track", role: "progressbar", "aria-label": label, "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": Math.round(ratio * 100) },
      h("div", { class: `meter-fill${ratio > warnAbove ? " warn" : ""}`, style: { width: `${(ratio * 100).toFixed(1)}%` } }),
    ),
  );
}

function statsCard(option) {
  const d = option.box_dimensions;
  const stat = (k, v) => h("div", { class: "stat" }, h("span", { class: "k" }, k), h("span", { class: "v num" }, v));
  return h(
    "section",
    { class: "card", "data-testid": "stats" },
    h("div", { class: "card-head" }, h("h2", null, option.box_name), h("span", { class: "mono muted" }, option.box_code)),
    h(
      "div",
      { class: "card-body stack" },
      meter("Space used", option.utilization, 100, fmt.pct(option.utilization), 1.01),
      option.max_weight
        ? meter("Weight vs. box limit", option.total_weight, option.max_weight, `${fmt.kg(option.total_weight)} / ${fmt.kg(option.max_weight)}`)
        : null,
      h(
        "div",
        { class: "grid-2", style: { gap: "12px" } },
        stat("Inner size (L × W × H)", fmt.dims(d.length, d.width, d.height)),
        stat("Box cost", fmt.inr(option.cost)),
        stat("Box volume", fmt.cm3(option.box_volume_cm3)),
        stat("Items volume", fmt.cm3(option.used_volume_cm3)),
        stat("Placement order", option.sort_strategy ? option.sort_strategy.replaceAll("_", " ") : "—"),
        stat("Engine time", `${fmt.num(option.execution_time_ms, 2)} ms`),
      ),
    ),
  );
}

function instructionsCard(option, colorFor, view) {
  const rows = option.placements.map((p, index) =>
    h(
      "tr",
      {
        class: "clickable",
        title: "Show the box up to this step",
        onmouseenter: () => view.viewer.highlight(index),
        onmouseleave: () => view.viewer.highlight(-1),
        onclick: () => view.setStep(index + 1),
      },
      h("td", { class: "num" }, p.sequence),
      h("td", null, h("span", { class: "swatch", style: { background: colorFor(p.product_id) } }), h("span", { class: "mono" }, p.sku)),
      h("td", { class: "num nowrap" }, `${fmt.num(p.position.x)}, ${fmt.num(p.position.y)}, ${fmt.num(p.position.z)}`),
      h("td", { class: "num nowrap" }, `${fmt.num(p.dimensions.length)} × ${fmt.num(p.dimensions.width)} × ${fmt.num(p.dimensions.height)}`),
      h("td", null, h("span", { class: "mono" }, p.orientation), " ", p.rotated ? h("span", { class: "badge badge-accent" }, "rotated") : h("span", { class: "muted" }, "as is")),
    ),
  );
  return h(
    "section",
    { class: "card" },
    h(
      "div",
      { class: "card-head" },
      h("h2", null, "Packing instructions"),
      h("span", { class: "muted" }, "Origin: back-left-bottom inner corner · cm"),
    ),
    h(
      "div",
      { class: "table-wrap" },
      h(
        "table",
        { "data-testid": "instructions" },
        h("thead", null, h("tr", null, h("th", null, "#"), h("th", null, "Item"), h("th", null, "Position x, y, z"), h("th", null, "Size along x × y × z"), h("th", null, "Orientation"))),
        h("tbody", null, rows),
      ),
    ),
  );
}

function rejectedCard(rejected) {
  return h(
    "section",
    { class: "card" },
    h(
      "div",
      { class: "card-head" },
      h("h2", null, `Boxes that cannot be used (${rejected.length})`),
      h("span", { class: "muted" }, "“Proven” means mathematically impossible, not just a heuristic miss"),
    ),
    h(
      "div",
      { class: "card-body rejects", "data-testid": "rejected" },
      rejected.map((box) => {
        const [label, cls] = FEASIBILITY[box.feasibility] || [box.feasibility, ""];
        return h(
          "div",
          { class: "reject" },
          h(
            "div",
            { class: "reject-head" },
            h("span", null, h("strong", null, box.box_name), " ", h("span", { class: "mono muted" }, box.box_code)),
            h("span", { class: `badge ${cls}` }, label),
          ),
          h("ul", null, box.reasons.map((reason) => h("li", null, reason))),
        );
      }),
    ),
  );
}
