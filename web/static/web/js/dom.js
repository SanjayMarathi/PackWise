// DOM helpers. Text always goes through text nodes, never innerHTML, so product
// names and other user data can never inject markup. The only innerHTML use is
// for the constant SVG icons below.

import { ApiError } from "./api.js";

const PROPERTY_KEYS = new Set(["value", "checked", "disabled", "selected", "indeterminate"]);

export function h(tag, props = null, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key === "style") Object.assign(el.style, value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (PROPERTY_KEYS.has(key)) el[key] = value;
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  appendChildren(el, children);
  return el;
}

export function appendChildren(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false || child === true) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const ICONS = {
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  pause: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>',
  reset: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>',
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>',
  package: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><path d="M12 2 3 7v10l9 5 9-5V7z"/><path d="m3 7 9 5 9-5M12 12v10M7.5 4.5l9 5"/></svg>',
  sparkle: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M11 2.5l1.9 5.4 5.6 1.6-5.6 1.7L11 16.6 9.1 11.2 3.5 9.5l5.6-1.6z"/><path d="M18.5 14l.9 2.5 2.6.8-2.6.9-.9 2.5-.9-2.5-2.6-.9 2.6-.8z"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  expand: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>',
  collapse: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/></svg>',
};

export function icon(name, size = 16, className = null) {
  const template = document.createElement("template");
  template.innerHTML = ICONS[name];
  const svg = template.content.firstElementChild;
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("aria-hidden", "true");
  if (className) svg.setAttribute("class", className);
  return svg;
}

const numberFormats = new Map();
function numberFormat(maxDigits) {
  if (!numberFormats.has(maxDigits)) {
    numberFormats.set(maxDigits, new Intl.NumberFormat("en-IN", { maximumFractionDigits: maxDigits }));
  }
  return numberFormats.get(maxDigits);
}

export const fmt = {
  num: (v, maxDigits = 2) => numberFormat(maxDigits).format(Number(v)),
  inr: (v) => {
    const n = Number(v);
    const digits = Number.isInteger(n) ? 0 : 2;
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      minimumFractionDigits: digits,
      maximumFractionDigits: 2,
    }).format(n);
  },
  kg: (v) => `${fmt.num(v, 3)} kg`,
  dims: (l, w, hgt) => `${fmt.num(l)} × ${fmt.num(w)} × ${fmt.num(hgt)} cm`,
  cm3: (v) => `${fmt.num(v, 0)} cm³`,
  pct: (v) => `${fmt.num(v, 2)}%`,
  date: (iso) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—"),
};

export const STRATEGY_LABELS = {
  lowest_cost: "Lowest cost",
  best_utilization: "Best utilization",
  smallest_box: "Smallest box",
};

export function strategyLabel(name) {
  return STRATEGY_LABELS[name] || name;
}

const STATUS = {
  pending: ["Pending", ""],
  recommended: ["Box recommended", "badge-success"],
  no_feasible_box: ["No box fits", "badge-danger"],
};

export function statusBadge(status) {
  const [label, cls] = STATUS[status] || [status, ""];
  return h("span", { class: `badge ${cls}`, "data-status": status }, label);
}

export function strategySelect(strategies, selected, attrs = {}) {
  return h(
    "select",
    { class: "select", ...attrs },
    strategies.map((s) => h("option", { value: s, selected: s === selected }, strategyLabel(s))),
  );
}

export function toast(message, { kind = "info", title = null, timeout = 5000 } = {}) {
  const host = document.getElementById("toasts");
  const el = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, title ? h("strong", null, title) : null, message);
  host.append(el);
  window.setTimeout(() => el.remove(), timeout);
  return el;
}

export function toastError(error, title = "Something went wrong") {
  const lines = error instanceof ApiError ? error.lines : [String((error && error.message) || error)];
  return toast(h("div", null, lines.map((line) => h("div", null, line))), { kind: "error", title, timeout: 9000 });
}

export function spinner() {
  return h("span", { class: "spinner", "aria-hidden": "true" });
}

/** Swap a button into a busy state while ``task`` runs. */
export async function withBusy(button, busyLabel, task) {
  const original = [...button.childNodes];
  button.disabled = true;
  button.replaceChildren(spinner(), busyLabel);
  try {
    return await task();
  } finally {
    button.disabled = false;
    button.replaceChildren(...original);
  }
}

/** ``title`` is a string, or ``[eyebrow, title]`` for a small spaced-out label above it. */
export function pageHead(title, subtitle, ...actions) {
  const [eyebrow, heading] = Array.isArray(title) ? title : [null, title];
  return h(
    "div",
    { class: "page-head" },
    h(
      "div",
      null,
      eyebrow ? h("span", { class: "eyebrow-label" }, eyebrow) : null,
      h("h1", null, heading),
      subtitle ? h("p", null, subtitle) : null,
    ),
    actions.length ? h("div", { class: "toolbar" }, actions) : null,
  );
}

export function errorState(error, retry) {
  const lines = error instanceof ApiError ? error.lines : [String((error && error.message) || error)];
  return h(
    "div",
    { class: "card empty" },
    h("h2", null, "Could not load this page"),
    h("p", null, lines.join(" ")),
    retry ? h("button", { class: "btn", type: "button", onclick: retry }, icon("refresh"), "Try again") : null,
  );
}
