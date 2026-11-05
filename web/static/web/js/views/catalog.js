// "Products" and "Boxes": list, search, add, edit, (de)activate and delete.
// One generic component, configured per resource.

import { ApiError, api } from "../api.js";
import { errorState, fmt, h, icon, pageHead, toast, toastError, withBusy } from "../dom.js";
import { pager } from "./orders.js";

const dimension = (name, label) => ({ name, label, type: "number", step: "0.01", min: "0.01", suffix: "cm" });

export const PRODUCTS = {
  key: "products",
  endpoint: "/api/products/",
  title: "Products",
  subtitle: "Items that can be ordered. Dimensions are the item's own outer size, and the engine may rotate it on any axis.",
  singular: "product",
  codeField: "sku",
  fields: [
    { name: "name", label: "Name", type: "text", wide: true, required: true },
    { name: "sku", label: "SKU", type: "text", required: true, hint: "Letters, digits, . _ - (stored upper-case)" },
    { name: "weight", label: "Weight", type: "number", step: "0.001", min: "0.001", suffix: "kg" },
    dimension("length", "Length"),
    dimension("width", "Width"),
    dimension("height", "Height"),
    { name: "is_active", label: "Active (can be ordered)", type: "checkbox", wide: true },
  ],
  defaults: { is_active: true },
  columns: [
    ["SKU", (p) => h("span", { class: "mono" }, p.sku)],
    ["Name", (p) => p.name],
    ["Size (L × W × H)", (p) => fmt.dims(p.length, p.width, p.height), "num nowrap"],
    ["Weight", (p) => fmt.kg(p.weight), "num right nowrap"],
    ["Volume", (p) => fmt.cm3(p.volume), "num right nowrap"],
  ],
};

export const BOXES = {
  key: "boxes",
  endpoint: "/api/boxes/",
  title: "Shipping boxes",
  subtitle: "Boxes the warehouse stocks. Inactive boxes are never recommended. Listed cheapest first.",
  singular: "box",
  codeField: "box_code",
  fields: [
    { name: "name", label: "Name", type: "text", wide: true, required: true },
    { name: "box_code", label: "Box code", type: "text", required: true, hint: "Letters, digits, . _ - (stored upper-case)" },
    { name: "cost", label: "Cost", type: "number", step: "0.01", min: "0", suffix: "INR" },
    dimension("internal_length", "Inner length"),
    dimension("internal_width", "Inner width"),
    dimension("internal_height", "Inner height"),
    { name: "max_weight", label: "Max load", type: "number", step: "0.001", min: "0.001", suffix: "kg" },
    { name: "is_active", label: "Active (in stock)", type: "checkbox", wide: true },
  ],
  defaults: { is_active: true },
  columns: [
    ["Code", (b) => h("span", { class: "mono" }, b.box_code)],
    ["Name", (b) => b.name],
    ["Inner size (L × W × H)", (b) => fmt.dims(b.internal_length, b.internal_width, b.internal_height), "num nowrap"],
    ["Max load", (b) => fmt.kg(b.max_weight), "num right nowrap"],
    ["Volume", (b) => fmt.cm3(b.internal_volume), "num right nowrap"],
    ["Cost", (b) => fmt.inr(b.cost), "num right nowrap"],
  ],
};

const pageStates = {};

export async function renderCatalog(root, config) {
  const pageState = (pageStates[config.key] ||= { page: 1, search: "", active: "" });
  const body = h("div", { class: "card" });

  const search = h("input", { class: "input", type: "search", placeholder: `Search ${config.title.toLowerCase()}`, "aria-label": "Search", value: pageState.search });
  let debounce = null;
  search.addEventListener("input", () => {
    window.clearTimeout(debounce);
    debounce = window.setTimeout(() => {
      pageState.search = search.value.trim();
      pageState.page = 1;
      load();
    }, 250);
  });
  const active = h(
    "select",
    { class: "select", style: { width: "auto" }, "aria-label": "Filter by state" },
    [["", "Active and inactive"], ["true", "Active only"], ["false", "Inactive only"]].map(([v, l]) => h("option", { value: v, selected: v === pageState.active }, l)),
  );
  active.addEventListener("change", () => {
    pageState.active = active.value;
    pageState.page = 1;
    load();
  });
  const add = h("button", { class: "btn btn-primary", type: "button", "data-testid": `add-${config.singular}` }, icon("plus", 14), `Add ${config.singular}`);
  add.addEventListener("click", () => openForm(config, null, load));

  root.append(pageHead(config.title, config.subtitle, h("div", { class: "search" }, icon("search"), search), active, add), body);

  async function load() {
    let data;
    try {
      data = await api(config.endpoint, { query: { page: pageState.page, page_size: 20, search: pageState.search, is_active: pageState.active } });
    } catch (error) {
      body.replaceChildren(errorState(error, load));
      return;
    }
    if (!data.results.length) {
      body.replaceChildren(h("div", { class: "empty", style: { minHeight: "240px" } }, h("h2", null, `No ${config.title.toLowerCase()} found`), h("p", null, pageState.search ? "Try a different search." : `Add the first ${config.singular}.`)));
      return;
    }
    body.replaceChildren(
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          { "data-testid": `${config.key}-table` },
          h(
            "thead",
            null,
            h("tr", null, config.columns.map(([label, , cls]) => h("th", { class: cls && cls.includes("right") ? "right" : null }, label)), h("th", null, "Active"), h("th", { class: "right" }, "Actions")),
          ),
          h("tbody", null, data.results.map((row) => tableRow(config, row, load))),
        ),
      ),
      pager(data, pageState, load),
    );
  }
  await load();
}

function tableRow(config, row, reload) {
  const toggle = h("input", { type: "checkbox", checked: row.is_active, "aria-label": `${row.name} is active` });
  toggle.addEventListener("change", async () => {
    try {
      await api(`${config.endpoint}${row.id}/`, { method: "PATCH", body: { is_active: toggle.checked } });
      toast(`${row.name} ${toggle.checked ? "activated" : "deactivated"}.`, { kind: "success" });
      reload();
    } catch (error) {
      toggle.checked = !toggle.checked;
      toastError(error, "Could not update");
    }
  });
  const edit = h("button", { class: "btn btn-ghost btn-sm", type: "button", title: "Edit", "aria-label": `Edit ${row.name}` }, icon("edit", 14));
  edit.addEventListener("click", () => openForm(config, row, reload));
  const remove = h("button", { class: "btn btn-ghost btn-sm btn-danger", type: "button", title: "Delete", "aria-label": `Delete ${row.name}` }, icon("trash", 14));
  remove.addEventListener("click", async () => {
    if (!window.confirm(`Delete ${config.singular} “${row.name}”? This cannot be undone.`)) return;
    try {
      await api(`${config.endpoint}${row.id}/`, { method: "DELETE" });
      toast(`${row.name} deleted.`, { kind: "success" });
      reload();
    } catch (error) {
      // 409: referenced by orders / stored recommendations. The API explains the alternative.
      toastError(error, error instanceof ApiError && error.status === 409 ? "Cannot delete: still in use" : "Could not delete");
    }
  });
  return h(
    "tr",
    { class: row.is_active ? null : "inactive", "data-code": row[config.codeField] },
    config.columns.map(([, render, cls]) => h("td", { class: cls || null }, render(row))),
    h("td", null, h("label", { class: "switch" }, toggle, h("span"))),
    h("td", { class: "actions" }, edit, remove),
  );
}

function openForm(config, row, onSaved) {
  const values = row || config.defaults;
  const inputs = {};
  const errors = {};
  const formError = h("div", { class: "form-error", hidden: true });

  const fields = config.fields.map((field) => {
    const id = `f-${config.key}-${field.name}`;
    errors[field.name] = h("div", { class: "error", hidden: true });
    if (field.type === "checkbox") {
      inputs[field.name] = h("input", { id, type: "checkbox", checked: Boolean(values[field.name]) });
      return h("div", { class: "field wide" }, h("label", { class: "check", for: id }, inputs[field.name], field.label), errors[field.name]);
    }
    inputs[field.name] = h("input", {
      id,
      name: field.name,
      class: "input",
      type: field.type,
      step: field.step,
      min: field.min,
      required: field.required || field.type === "number",
      value: values[field.name] ?? "",
      inputmode: field.type === "number" ? "decimal" : null,
    });
    return h(
      "div",
      { class: `field${field.wide ? " wide" : ""}`, "data-field": field.name },
      h("label", { for: id }, field.label, field.suffix ? h("span", { class: "muted" }, ` (${field.suffix})`) : null),
      inputs[field.name],
      field.hint ? h("div", { class: "hint" }, field.hint) : null,
      errors[field.name],
    );
  });

  const save = h("button", { class: "btn btn-primary", type: "submit" }, row ? "Save changes" : `Create ${config.singular}`);
  const cancel = h("button", { class: "btn", type: "button" }, "Cancel");
  const form = h(
    "form",
    { method: "dialog", novalidate: true },
    h("div", { class: "card-head" }, h("h2", null, row ? `Edit ${config.singular}` : `New ${config.singular}`), row ? h("span", { class: "mono muted" }, row[config.codeField]) : null),
    h("div", { class: "dialog-body" }, formError, fields),
    h("div", { class: "dialog-foot" }, cancel, save),
  );
  const dialog = h("dialog", { "data-testid": "catalog-form" }, form);
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  cancel.addEventListener("click", () => dialog.close());

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const body = {};
    for (const field of config.fields) {
      const input = inputs[field.name];
      body[field.name] = field.type === "checkbox" ? input.checked : input.value.trim();
    }
    for (const field of config.fields) {
      errors[field.name].hidden = true;
      errors[field.name].closest(".field")?.classList.remove("has-error");
    }
    formError.hidden = true;

    withBusy(save, "Saving…", async () => {
      try {
        const saved = await api(row ? `${config.endpoint}${row.id}/` : config.endpoint, { method: row ? "PATCH" : "POST", body });
        dialog.close();
        toast(`${saved.name} ${row ? "updated" : "created"}.`, { kind: "success" });
        onSaved();
      } catch (error) {
        if (!(error instanceof ApiError) || error.code !== "validation_error") {
          formError.textContent = error.message;
          formError.hidden = false;
          return;
        }
        const unmatched = [];
        for (const [name, message] of Object.entries(error.fieldErrors)) {
          if (errors[name]) {
            errors[name].textContent = message;
            errors[name].hidden = false;
            errors[name].closest(".field")?.classList.add("has-error");
          } else {
            unmatched.push(`${name}: ${message}`);
          }
        }
        if (unmatched.length) {
          formError.textContent = unmatched.join(" ");
          formError.hidden = false;
        }
      }
    });
  });
  dialog.showModal();
  inputs[config.fields[0].name].focus();
}
