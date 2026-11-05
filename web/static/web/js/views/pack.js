// "Pack order": choose products and quantities, then let the engine pick the box.

import { api, fetchAll } from "../api.js";
import { fmt, h, icon, pageHead, strategySelect, toast, toastError, withBusy } from "../dom.js";
import { renderResult } from "./result.js";

// Kept across tab switches so the order and its result survive navigation.
const state = { products: null, cart: new Map(), filter: "", strategy: null, result: null };

export async function renderPack(root, { strategies, defaultStrategy }) {
  state.strategy = state.strategy || defaultStrategy;
  const resultArea = h("section", { class: "stack", "data-testid": "result-area" });
  const builderBody = h("div", { class: "card-body" }, h("div", { class: "skeleton" }), h("div", { class: "skeleton", style: { marginTop: "10px", width: "70%" } }));
  const summary = h("div", { class: "stack", style: { gap: "4px" } });
  const strategy = strategySelect(strategies, state.strategy, { id: "strategy", "aria-label": "Ranking strategy" });
  strategy.addEventListener("change", () => {
    state.strategy = strategy.value;
  });
  const submit = h("button", { class: "btn btn-primary btn-block", type: "button", "data-testid": "find-box" }, icon("package", 18), "Find the best box");
  submit.addEventListener("click", () => withBusy(submit, "Packing in 3D…", () => findBox(resultArea)));

  const builder = h(
    "aside",
    { class: "card sticky", "data-testid": "builder" },
    h(
      "div",
      { class: "card-head" },
      h("h2", null, "1. Choose products"),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => { state.cart.clear(); if (state.products) drawList(); } }, "Clear"),
    ),
    builderBody,
    h(
      "div",
      { class: "card-foot stack", style: { gap: "12px" } },
      summary,
      h("div", { class: "field" }, h("label", { for: "strategy" }, "2. Rank feasible boxes by"), strategy),
      submit,
    ),
  );

  root.append(
    pageHead("Pack an order", "Pick products and quantities. PackWise places every unit inside each active box in 3D and recommends the cheapest one that really fits."),
    h("div", { class: "pack-layout" }, builder, resultArea),
  );

  function drawSummary() {
    let units = 0;
    let weight = 0;
    let volume = 0;
    for (const [id, qty] of state.cart) {
      const p = state.products.find((x) => x.id === id);
      if (!p) continue;
      units += qty;
      weight += p.weight * qty;
      volume += p.volume * qty;
    }
    summary.replaceChildren(
      h("div", { class: "summary-line" }, h("span", null, "Units"), h("strong", { class: "num", "data-testid": "units" }, units)),
      h("div", { class: "summary-line" }, h("span", null, "Total weight"), h("strong", { class: "num" }, fmt.kg(weight))),
      h("div", { class: "summary-line" }, h("span", null, "Total item volume"), h("strong", { class: "num" }, fmt.cm3(volume))),
    );
    submit.disabled = units === 0;
  }

  function productRow(product) {
    const input = h("input", { type: "number", min: 0, step: 1, inputmode: "numeric", "aria-label": `Quantity of ${product.name}`, value: state.cart.get(product.id) || 0 });
    const minus = h("button", { type: "button", "aria-label": `Remove one ${product.name}` }, "−");
    const plus = h("button", { type: "button", "aria-label": `Add one ${product.name}` }, "+");
    const row = h(
      "div",
      { class: "product-row", "data-sku": product.sku },
      h(
        "div",
        { class: "info" },
        h("div", { class: "name", title: product.name }, product.name),
        h("div", { class: "meta" }, h("span", { class: "mono" }, product.sku), " · ", fmt.dims(product.length, product.width, product.height), " · ", fmt.kg(product.weight)),
      ),
      h("div", { class: "stepper" }, minus, input, plus),
    );
    const set = (qty) => {
      const value = Math.max(0, Math.min(999, Number.isFinite(qty) ? Math.floor(qty) : 0));
      if (value) state.cart.set(product.id, value);
      else state.cart.delete(product.id);
      input.value = value;
      minus.disabled = value === 0;
      row.classList.toggle("selected", value > 0);
      drawSummary();
    };
    minus.addEventListener("click", () => set((state.cart.get(product.id) || 0) - 1));
    plus.addEventListener("click", () => set((state.cart.get(product.id) || 0) + 1));
    input.addEventListener("change", () => set(Number(input.value)));
    set(state.cart.get(product.id) || 0);
    return row;
  }

  const list = h("div", { class: "product-list", "data-testid": "product-list" });
  const search = h("input", { class: "input", type: "search", placeholder: "Search name or SKU", "aria-label": "Search products", value: state.filter });
  search.addEventListener("input", () => {
    state.filter = search.value;
    drawList();
  });

  function drawList() {
    const term = state.filter.trim().toLowerCase();
    const shown = state.products.filter((p) => !term || p.name.toLowerCase().includes(term) || p.sku.toLowerCase().includes(term));
    list.replaceChildren(
      ...(shown.length ? shown.map(productRow) : [h("div", { class: "product-row muted" }, "No products match your search.")]),
    );
    drawSummary();
  }

  function drawResult() {
    if (!state.result) {
      resultArea.replaceChildren(
        h(
          "div",
          { class: "card empty" },
          icon("package", 110),
          icon("leaf", 160, "corner-leaf"),
          h("h2", null, "Your recommendation appears here"),
          h("p", null, "Add a few products on the left and press “Find the best box”. You will get the cheapest box that fits, an interactive 3D packing plan, step-by-step loading instructions, ranked alternatives and the reason each other box was rejected."),
          h("p", { class: "muted" }, "Prefer to ask in plain words? Open the packing assistant at the bottom right."),
        ),
      );
      return;
    }
    resultArea.replaceChildren(renderResult(state.result, { strategies, onRerun: rerun }));
  }

  async function findBox() {
    const items = [...state.cart].map(([product_id, quantity]) => ({ product_id, quantity }));
    try {
      const order = await api("/api/orders/", { method: "POST", body: { items } });
      state.result = await api(`/api/orders/${order.id}/recommend/`, { method: "POST", body: { strategy: state.strategy } });
      drawResult();
      announce(state.result);
    } catch (error) {
      toastError(error, "Could not pack this order");
    }
  }

  async function rerun(strategyName) {
    try {
      state.strategy = strategyName;
      strategy.value = strategyName;
      state.result = await api(`/api/orders/${state.result.order_id}/recommend/`, { method: "POST", body: { strategy: strategyName } });
      drawResult();
      announce(state.result);
    } catch (error) {
      toastError(error, "Could not re-run the recommendation");
    }
  }

  drawResult();
  try {
    state.products = await fetchAll("/api/products/", { is_active: "true" });
  } catch (error) {
    builderBody.replaceChildren(h("p", { class: "muted" }, "Could not load products."));
    toastError(error, "Could not load products");
    return;
  }
  if (!state.products.length) {
    builderBody.replaceChildren(h("p", null, "There are no active products yet. ", h("a", { href: "#/products" }, "Add a product"), " and a ", h("a", { href: "#/boxes" }, "shipping box"), " first."));
    drawSummary();
    return;
  }
  builderBody.replaceChildren(h("div", { class: "search" }, icon("search"), search), h("div", { style: { height: "12px" } }), list);
  drawList();
}

function announce(result) {
  if (result.recommendation) {
    const n = result.recommendation.placements.length;
    toast(`${result.recommendation.box_name} (${fmt.inr(result.recommendation.cost)}) fits ${n === 1 ? "the item" : `all ${n} items`}.`, { kind: "success", title: "Box found" });
  } else {
    toast("None of the active boxes can hold this order. See the reasons below.", { kind: "error", title: "No box fits" });
  }
}
