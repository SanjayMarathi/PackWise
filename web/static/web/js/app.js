// Entry point: hash router, navigation state and the API health indicator.

import { api } from "./api.js";
import { mountAssistant } from "./assistant.js";
import { errorState } from "./dom.js";
import { BOXES, PRODUCTS, renderCatalog } from "./views/catalog.js";
import { renderOrders } from "./views/orders.js";
import { renderPack } from "./views/pack.js";

const config = {
  strategies: JSON.parse(document.getElementById("strategies").textContent),
  defaultStrategy: JSON.parse(document.getElementById("default-strategy").textContent),
};

const routes = {
  pack: (root, ctx) => renderPack(root, ctx),
  orders: (root, ctx) => renderOrders(root, ctx),
  products: (root) => renderCatalog(root, PRODUCTS),
  boxes: (root) => renderCatalog(root, BOXES),
};

async function route() {
  const [name, id] = window.location.hash.replace(/^#\/?/, "").split("/");
  const view = routes[name] ? name : "pack";
  for (const link of document.querySelectorAll(".tabs a")) {
    if (link.dataset.route === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  // Each view renders into its own container. If the user navigates away while
  // a request is in flight, the late result lands in a detached node and is dropped.
  const app = document.getElementById("app");
  const page = document.createElement("div");
  app.replaceChildren(page);
  window.scrollTo(0, 0);
  try {
    await routes[view](page, { ...config, id: id ? Number(id) : null });
  } catch (error) {
    console.error(error);
    page.replaceChildren(errorState(error, route));
  }
}

async function checkHealth() {
  const el = document.getElementById("health");
  const label = el.querySelector(".label");
  try {
    const health = await api("/api/health/");
    el.className = "health ok";
    label.textContent = health.database === "ok" ? "Online" : "Degraded";
  } catch (error) {
    el.className = "health down";
    label.textContent = error.status === 503 ? "Database unavailable" : "API unavailable";
  }
}

window.addEventListener("hashchange", route);
route();
mountAssistant(document.getElementById("assistant-root"));
checkHealth();
window.setInterval(checkHealth, 60_000);
