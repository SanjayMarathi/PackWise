// Thin client for the PackWise REST API. Every error body has the shape
// {"status": "error", "error": {"code", "message", "details"}}.

export class ApiError extends Error {
  constructor(status, payload) {
    const error = (payload && payload.error) || {};
    super(error.message || `Request failed with HTTP ${status}`);
    this.status = status;
    this.code = error.code || "error";
    this.details = error.details ?? null;
  }

  /** Human-readable lines, e.g. "items[2].quantity: Ensure this value is ...". */
  get lines() {
    const out = [];
    const walk = (value, path) => {
      if (value === null || value === undefined) return;
      if (Array.isArray(value)) {
        value.forEach((v, i) => {
          if (v && typeof v === "object") walk(v, `${path || "item"}[${i + 1}]`);
          else out.push(path ? `${path}: ${v}` : String(v));
        });
      } else if (typeof value === "object") {
        for (const [key, v] of Object.entries(value)) walk(v, path ? `${path}.${key}` : key);
      } else {
        out.push(path ? `${path}: ${value}` : String(value));
      }
    };
    walk(this.details, "");
    return out.length ? out : [this.message];
  }

  /** {field: "message"} for top-level field errors, used to annotate form inputs. */
  get fieldErrors() {
    const result = {};
    if (this.details && typeof this.details === "object" && !Array.isArray(this.details)) {
      for (const [key, value] of Object.entries(this.details)) {
        result[key] = Array.isArray(value) ? value.filter((v) => typeof v === "string").join(" ") : String(value);
      }
    }
    return result;
  }
}

export async function api(path, { method = "GET", body, query } = {}) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  }
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response;
  try {
    response = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (networkError) {
    throw new ApiError(0, { error: { code: "network_error", message: "Cannot reach the server. Check your connection." } });
  }
  if (response.status === 204) return null;
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) throw new ApiError(response.status, data);
  return data;
}

/** Follow DRF pagination and return every result. */
export async function fetchAll(path, query = {}) {
  const results = [];
  for (let page = 1; ; page += 1) {
    const data = await api(path, { query: { ...query, page, page_size: 100 } });
    results.push(...data.results);
    if (!data.next) return results;
  }
}
