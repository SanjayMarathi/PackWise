// "Orders": order history, and one order's items plus its stored recommendation.

import { api } from "../api.js";
import { errorState, fmt, h, icon, pageHead, statusBadge, strategySelect, toast, toastError, withBusy } from "../dom.js";
import { renderResult } from "./result.js";

const STATUS_FILTERS = [
  ["", "All statuses"],
  ["recommended", "Box recommended"],
  ["no_feasible_box", "No box fits"],
  ["pending", "Pending"],
];

const listState = { page: 1, status: "" };

export async function renderOrders(root, ctx) {
  if (ctx.id) return renderOrderDetail(root, ctx);

  const body = h("div", { class: "card" });
  const filter = h(
    "select",
    { class: "select", style: { width: "auto" }, "aria-label": "Filter by status" },
    STATUS_FILTERS.map(([value, label]) => h("option", { value, selected: value === listState.status }, label)),
  );
  filter.addEventListener("change", () => {
    listState.status = filter.value;
    listState.page = 1;
    load();
  });
  root.append(
    pageHead("Orders", "Every order placed through PackWise, newest first. Open one to see its packing plan or recompute it.", filter, h("a", { class: "btn btn-primary", href: "#/pack" }, icon("plus", 14), "New order")),
    body,
  );

  async function load() {
    body.replaceChildren(h("div", { class: "card-body" }, h("div", { class: "skeleton" })));
    let data;
    try {
      data = await api("/api/orders/", { query: { page: listState.page, page_size: 20, status: listState.status } });
    } catch (error) {
      body.replaceChildren(errorState(error, load));
      return;
    }
    if (!data.results.length) {
      body.replaceChildren(h("div", { class: "empty" }, icon("package", 72), h("h2", null, "No orders yet"), h("p", null, "Orders appear here once you pack one."), h("a", { class: "btn btn-primary", href: "#/pack" }, "Pack an order")));
      return;
    }
    const rows = data.results.map((order) =>
      h(
        "tr",
        { class: "clickable", onclick: () => { window.location.hash = `#/orders/${order.id}`; } },
        h("td", null, h("a", { href: `#/orders/${order.id}`, class: "mono" }, order.order_number)),
        h("td", null, statusBadge(order.status)),
        h("td", null, order.items.map((item) => `${item.quantity} × ${item.sku}`).join(", ")),
        h("td", { class: "num right" }, order.total_units),
        h("td", { class: "num right nowrap" }, fmt.kg(order.total_weight)),
        h("td", { class: "nowrap muted" }, fmt.date(order.created_at)),
      ),
    );
    body.replaceChildren(
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          { "data-testid": "orders-table" },
          h("thead", null, h("tr", null, h("th", null, "Order"), h("th", null, "Status"), h("th", null, "Items"), h("th", { class: "right" }, "Units"), h("th", { class: "right" }, "Weight"), h("th", null, "Created"))),
          h("tbody", null, rows),
        ),
      ),
      pager(data, listState, load),
    );
  }
  await load();
}

export function pager(data, pageState, reload) {
  const pageSize = 20;
  const from = (pageState.page - 1) * pageSize + 1;
  const to = from + data.results.length - 1;
  const prev = h("button", { class: "btn btn-sm", type: "button", disabled: !data.previous }, "Previous");
  const next = h("button", { class: "btn btn-sm", type: "button", disabled: !data.next }, "Next");
  prev.addEventListener("click", () => { pageState.page -= 1; reload(); });
  next.addEventListener("click", () => { pageState.page += 1; reload(); });
  return h("div", { class: "pager" }, h("span", null, `Showing ${from}–${to} of ${data.count}`), h("div", { class: "row" }, prev, next));
}

async function renderOrderDetail(root, { id, strategies, defaultStrategy }) {
  const head = h("div");
  const itemsSlot = h("div");
  const recSlot = h("div", { class: "stack" });
  root.append(
    h("a", { href: "#/orders", class: "btn btn-ghost btn-sm", style: { marginBottom: "12px" } }, icon("back", 14), "All orders"),
    head,
    h("div", { class: "stack" }, itemsSlot, recSlot),
  );

  let order;
  let stored;
  try {
    [order, stored] = await Promise.all([api(`/api/orders/${id}/`), api(`/api/orders/${id}/recommendations/`)]);
  } catch (error) {
    head.replaceChildren(errorState(error, () => { root.replaceChildren(); renderOrderDetail(root, { id, strategies, defaultStrategy }); }));
    return;
  }

  head.replaceChildren(
    pageHead(order.order_number, `Created ${fmt.date(order.created_at)} · ${order.total_units} units · ${fmt.kg(order.total_weight)}`, statusBadge(order.status)),
  );
  itemsSlot.replaceChildren(
    h(
      "section",
      { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, "Items"), h("span", { class: "muted" }, `${order.items.length} lines`)),
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          null,
          h("thead", null, h("tr", null, h("th", null, "SKU"), h("th", null, "Product"), h("th", null, "Size (L × W × H)"), h("th", { class: "right" }, "Unit weight"), h("th", { class: "right" }, "Quantity"))),
          h(
            "tbody",
            null,
            order.items.map((item) =>
              h(
                "tr",
                null,
                h("td", { class: "mono" }, item.sku),
                h("td", null, item.name),
                h("td", { class: "num" }, fmt.dims(item.dimensions.length, item.dimensions.width, item.dimensions.height)),
                h("td", { class: "num right" }, fmt.kg(item.unit_weight)),
                h("td", { class: "num right" }, item.quantity),
              ),
            ),
          ),
        ),
      ),
    ),
  );

  async function rerun(strategyName) {
    try {
      const result = await api(`/api/orders/${id}/recommend/`, { method: "POST", body: { strategy: strategyName } });
      head.querySelector("[data-status]")?.replaceWith(statusBadge(result.order_status));
      recSlot.replaceChildren(renderResult(result, { strategies, onRerun: rerun }));
      toast(result.recommendation ? `Recomputed: ${result.recommendation.box_name}` : "Recomputed: no box fits", { kind: result.recommendation ? "success" : "error" });
    } catch (error) {
      toastError(error, "Could not run the recommendation");
    }
  }

  if (stored.status === "not_generated") {
    const select = strategySelect(strategies, defaultStrategy, { style: { width: "auto" }, "aria-label": "Ranking strategy" });
    const button = h("button", { class: "btn btn-primary", type: "button" }, icon("package", 16), "Recommend a box");
    button.addEventListener("click", () => withBusy(button, "Packing…", () => rerun(select.value)));
    recSlot.replaceChildren(
      h("section", { class: "card empty", style: { minHeight: "220px" } }, h("h2", null, "No recommendation yet"), h("p", null, "Run the packing engine for this order."), h("div", { class: "row" }, select, button)),
    );
    return;
  }
  recSlot.replaceChildren(renderResult(stored, { strategies, onRerun: rerun }));
  if (stored.recommendation) {
    recSlot.append(h("p", { class: "muted", style: { margin: 0 } }, "Showing the stored result. Re-run it to also see why the other boxes were rejected."));
  }
}
