// The AI packing assistant: a chat panel that streams answers from /api/assistant/chat/.
//
// The server runs Claude with tools over the real services (catalogue lookups, the 3D
// packing engine, order creation). This file only renders. The reply arrives as NDJSON
// events: conversation, status, text, card, error, done.

import { ApiError, api } from "./api.js";
import { fmt, h, icon } from "./dom.js";

const STORAGE_KEY = "packwise.assistant.conversation";
const SUGGESTIONS = [
  "Pack 2 laptops and a wireless mouse",
  "Which box is cheapest for an electric kettle?",
  "Why can't a 27-inch monitor go in the Large box?",
  "Which boxes can carry more than 20 kg?",
];

function storage(action, value) {
  try {
    if (action === "get") return window.sessionStorage.getItem(STORAGE_KEY);
    if (action === "set") window.sessionStorage.setItem(STORAGE_KEY, value);
    if (action === "clear") window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode, blocked cookies); the chat still works for this page.
  }
  return null;
}

/** Plain text with "- " bullets, **bold** and `code`, rendered with DOM nodes (never innerHTML). */
export function renderRich(text) {
  // Line by line: consecutive "- " lines form a list, even right after a sentence
  // ("It fits:\n- a\n- b"); other lines form paragraphs; blank lines separate blocks.
  const fragment = document.createDocumentFragment();
  let paragraph = null;
  let list = null;
  for (const raw of text.trim().split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      paragraph = null;
      list = null;
      continue;
    }
    const bullet = line.match(/^\s*[-•]\s+(.*)$/) || line.match(/^\s*\*\s+(.*)$/);
    if (bullet) {
      paragraph = null;
      if (!list) fragment.append((list = h("ul")));
      list.append(h("li", null, inline(bullet[1])));
      continue;
    }
    list = null;
    if (paragraph) paragraph.append(h("br"));
    else fragment.append((paragraph = h("p")));
    paragraph.append(...inline(line));
  }
  return fragment;
}

function inline(text) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean).map((part) => {
    if (part.startsWith("**") && part.endsWith("**")) return h("strong", null, part.slice(2, -2));
    if (part.startsWith("`") && part.endsWith("`")) return h("code", null, part.slice(1, -1));
    return document.createTextNode(part);
  });
}

export function mountAssistant(root) {
  const state = { enabled: null, model: null, conversationId: storage("get"), busy: false, loaded: false };

  const fab = h(
    "button",
    { class: "assistant-fab", type: "button", "aria-expanded": "false", "aria-controls": "assistant-panel", "data-testid": "assistant-open" },
    h("span", { class: "fab-icon" }, icon("sparkle", 18)),
    h("span", { class: "fab-label" }, "Ask PackWise AI"),
  );
  const log = h("div", { class: "chat-log", "data-testid": "chat-log", "aria-live": "polite" });
  const textarea = h("textarea", { rows: 1, placeholder: "Ask about boxes, orders or products…", "aria-label": "Message the assistant", maxlength: 2000 });
  const sendButton = h("button", { class: "btn btn-primary", type: "submit", "aria-label": "Send", "data-testid": "chat-send" }, icon("send", 18));
  const form = h("form", { class: "chat-input" }, textarea, sendButton);
  const subtitle = h("div", { class: "subtitle" }, "connecting…");
  const live = h("span", { class: "live off" }, "Offline");
  const maximize = h("button", { class: "btn btn-ghost btn-sm maximize-btn", type: "button", "aria-label": "Maximize console", "aria-pressed": "false" }, icon("expand", 15));
  const newChat = h("button", { class: "btn btn-ghost btn-sm", type: "button", title: "Start a new chat" }, icon("refresh", 14), "New");
  const close = h("button", { class: "btn btn-ghost btn-sm", type: "button", "aria-label": "Close assistant" }, icon("close", 16));
  const handles = ["corner", "left", "top"].map((edge) => h("span", { class: `resize-handle ${edge}`, "data-edge": edge, "aria-hidden": "true" }));
  const panel = h(
    "section",
    { class: "assistant-panel", id: "assistant-panel", role: "dialog", "aria-label": "PackWise assistant", hidden: true, "data-testid": "assistant-panel" },
    handles,
    h(
      "div",
      { class: "chat-head" },
      h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
      h("div", null, h("div", { class: "title" }, "PackWise assistant"), subtitle),
      h("span", { class: "spacer" }),
      live,
      maximize,
      newChat,
      close,
    ),
    log,
    form,
    h("div", { class: "chat-foot" }, "AI can make mistakes. Box choices and fits come from the packing engine."),
  );
  root.append(fab, panel);

  // ---- resizable console: drag the top-left corner, left edge or top edge; size is remembered
  const SIZE_KEY = "packwise.assistant.size";
  const clampSize = (width, height) => [
    Math.round(Math.min(Math.max(width, 340), window.innerWidth - 48)),
    Math.round(Math.min(Math.max(height, 380), window.innerHeight - 100)),
  ];
  try {
    const saved = JSON.parse(window.localStorage.getItem(SIZE_KEY) || "null");
    if (saved && saved.width && saved.height) {
      const [width, height] = clampSize(saved.width, saved.height);
      Object.assign(panel.style, { width: `${width}px`, height: `${height}px` });
    }
  } catch {
    // Storage unavailable or bad data: keep the default size.
  }
  for (const handle of handles) {
    handle.addEventListener("pointerdown", (start) => {
      if (panel.classList.contains("maximized")) return;
      start.preventDefault();
      handle.setPointerCapture(start.pointerId);
      const edge = handle.dataset.edge;
      const rect = panel.getBoundingClientRect();
      panel.classList.add("resizing");
      const move = (event) => {
        const width = edge === "top" ? rect.width : rect.width + (start.clientX - event.clientX);
        const height = edge === "left" ? rect.height : rect.height + (start.clientY - event.clientY);
        const [w, hgt] = clampSize(width, height);
        Object.assign(panel.style, { width: `${w}px`, height: `${hgt}px` });
      };
      const stop = () => {
        panel.classList.remove("resizing");
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", stop);
        handle.removeEventListener("pointercancel", stop);
        try {
          const r = panel.getBoundingClientRect();
          window.localStorage.setItem(SIZE_KEY, JSON.stringify({ width: r.width, height: r.height }));
        } catch {
          // Size just isn't remembered.
        }
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", stop);
      handle.addEventListener("pointercancel", stop);
    });
  }
  maximize.addEventListener("click", () => {
    const on = panel.classList.toggle("maximized");
    maximize.setAttribute("aria-pressed", String(on));
    maximize.setAttribute("aria-label", on ? "Restore console size" : "Maximize console");
    maximize.replaceChildren(icon(on ? "collapse" : "expand", 15));
    scrollDown();
  });

  const scrollDown = () => {
    log.scrollTop = log.scrollHeight;
  };

  function setOpen(open) {
    panel.hidden = !open;
    fab.setAttribute("aria-expanded", String(open));
    if (open) {
      prepare().then(() => (form.hidden ? close : textarea).focus());
    } else {
      fab.focus();
    }
  }
  fab.addEventListener("click", () => setOpen(true));
  close.addEventListener("click", () => setOpen(false));
  // On the document, not the panel: focus may sit on <body> (e.g. offline mode has no input).
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden && !document.querySelector("dialog[open]")) setOpen(false);
  });
  newChat.addEventListener("click", () => {
    state.conversationId = null;
    storage("clear");
    showWelcome();
    textarea.focus();
  });

  function showWelcome() {
    log.replaceChildren(
      h(
        "div",
        { class: "chat-suggestions" },
        h("div", { class: "hello" }, "Hi! What are we packing?"),
        h("p", null, "Describe an order in plain words and I'll run the 3D packer, compare boxes and explain the result."),
        SUGGESTIONS.map((text) => h("button", { class: "chip-btn", type: "button", onclick: () => send(text) }, text)),
      ),
    );
  }

  function showOffline() {
    form.hidden = true;
    subtitle.textContent = "not configured";
    live.className = "live off";
    live.textContent = "Offline";
    log.replaceChildren(
      h(
        "div",
        { class: "chat-offline", "data-testid": "chat-offline" },
        icon("sparkle", 32),
        h("strong", null, "The AI assistant is switched off on this server."),
        h("span", null, "An administrator can turn it on by setting the ", h("code", null, "GEMINI_API_KEY"), " (free tier) or ", h("code", null, "ANTHROPIC_API_KEY"), " secret."),
        h("span", { class: "muted" }, "Everything else in PackWise works without it."),
      ),
    );
  }

  async function prepare() {
    if (state.loaded) return;
    state.loaded = true;
    try {
      const status = await api("/api/assistant/status/");
      state.enabled = status.enabled;
      state.model = status.model;
    } catch {
      state.enabled = false;
    }
    if (!state.enabled) return showOffline();
    subtitle.textContent = `${state.model} · live packing engine`;
    live.className = "live";
    live.textContent = "Live";
    if (!state.conversationId) return showWelcome();
    try {
      const conversation = await api(`/api/assistant/conversations/${state.conversationId}/`);
      log.replaceChildren();
      if (!conversation.transcript.length) return showWelcome();
      for (const entry of conversation.transcript) {
        if (entry.role === "user") addUser(entry.text);
        else {
          const turn = addTurn();
          turn.setText(entry.text);
          (entry.cards || []).forEach(turn.addCard);
          turn.finish();
        }
      }
      scrollDown();
    } catch {
      state.conversationId = null;
      storage("clear");
      showWelcome();
    }
  }

  function addUser(text) {
    log.querySelector(".chat-suggestions")?.remove();
    log.append(h("div", { class: "msg user" }, text));
    scrollDown();
  }

  /** One assistant reply: a text bubble, result cards below it, and a live status line. */
  function addTurn() {
    const bubble = h("div", { class: "msg bot", "data-testid": "chat-answer" }, h("span", { class: "typing", "aria-label": "Thinking" }, h("i"), h("i"), h("i")));
    const cards = h("div", { class: "stack", style: { gap: "8px", alignSelf: "stretch" } });
    const status = h("div", { class: "msg-status", hidden: true });
    log.append(bubble, cards, status);
    let text = "";
    return {
      setText(value) {
        text = value;
        bubble.replaceChildren(text.trim() ? renderRich(text) : "");
        scrollDown();
      },
      appendText(delta) {
        this.setText(text + delta);
      },
      setStatus(label) {
        status.hidden = !label;
        status.replaceChildren(h("span", { class: "spinner" }), label || "");
        scrollDown();
      },
      addCard(card) {
        cards.append(resultCard(card));
        scrollDown();
      },
      error(message) {
        log.append(h("div", { class: "msg bot error", role: "alert" }, message));
        scrollDown();
      },
      finish() {
        status.hidden = true;
        if (!text.trim()) bubble.remove();
      },
    };
  }

  function resultCard(card) {
    const open = () => {
      window.location.hash = `#/orders/${card.order_id}`;
      if (window.matchMedia("(max-width: 720px)").matches) setOpen(false);
    };
    if (!card.box_name) {
      return h(
        "div",
        { class: "chat-card fail", "data-testid": "chat-card" },
        h("span", { class: "card-icon" }, icon("package", 24)),
        h("div", null, h("div", { class: "k" }, "No box fits"), h("div", { class: "v" }, card.order_number), h("div", { class: "s" }, "See the reasons for each box")),
        h("button", { class: "btn btn-sm", type: "button", onclick: open }, "View"),
      );
    }
    return h(
      "div",
      { class: "chat-card", "data-testid": "chat-card" },
      h("span", { class: "card-icon" }, icon("package", 24)),
      h(
        "div",
        null,
        h("div", { class: "k" }, "Recommended box"),
        h("div", { class: "v" }, `${card.box_name} · ${fmt.inr(card.cost)}`),
        h("div", { class: "s" }, `${fmt.pct(card.utilization)} full · ${card.items} item${card.items === 1 ? "" : "s"} · ${card.order_number}`),
      ),
      h("button", { class: "btn btn-primary btn-sm", type: "button", onclick: open }, "Open 3D plan"),
    );
  }

  async function send(raw) {
    const text = raw.trim();
    if (!text || state.busy) return;
    state.busy = true;
    sendButton.disabled = true;
    textarea.value = "";
    autosize();
    addUser(text);
    const turn = addTurn();
    try {
      const response = await fetch("/api/assistant/chat/", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/x-ndjson, application/json" },
        body: JSON.stringify(state.conversationId ? { message: text, conversation_id: state.conversationId } : { message: text }),
      });
      if (!response.ok) {
        let data = null;
        try {
          data = await response.json();
        } catch {
          data = null;
        }
        throw new ApiError(response.status, data);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const handle = (event) => {
        if (event.type === "conversation") {
          state.conversationId = event.id;
          storage("set", event.id);
        } else if (event.type === "status") turn.setStatus(event.text);
        else if (event.type === "text") {
          turn.setStatus(null);
          turn.appendText(event.text);
        } else if (event.type === "card") turn.addCard(event.card);
        else if (event.type === "error") turn.error(event.message);
      };
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let newline;
        while ((newline = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, newline).trim();
          buffer = buffer.slice(newline + 1);
          if (line) handle(JSON.parse(line));
        }
      }
      if (buffer.trim()) handle(JSON.parse(buffer));
    } catch (error) {
      turn.error(error instanceof ApiError ? error.message : "Could not reach the assistant. Please try again.");
    } finally {
      turn.finish();
      state.busy = false;
      sendButton.disabled = false;
      textarea.focus();
    }
  }

  function autosize() {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 140)}px`;
  }
  textarea.addEventListener("input", autosize);
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send(textarea.value);
    }
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send(textarea.value);
  });
}
