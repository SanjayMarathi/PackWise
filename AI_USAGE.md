# AI Usage

This project was built with heavy AI assistance. This file records what the AI did, what changed along the way, the mistakes found, and how the result was verified. The full conversation is in the exported chat transcript attached to this repository.

> Sections marked **✍️ Author** are for my own review decisions and must be written by me, not by the AI.

---

## 1. AI tools used

| Tool | Used for |
|---|---|
| **Claude Code** (Anthropic), VS Code extension, model **Claude Opus 5.5** | Architecture proposal, all source code, tests, Docker/CI configuration, documentation drafts, running commands (tests, Docker, linting) in the local terminal |
| **Gemini API** (`gemini-3.6-flash`) or **Claude API** (`claude-opus-5-5`), at runtime | Not development tools. The app's own AI assistant calls one of them at runtime (see README, "The AI assistant") |

✍️ Author: _list any other tools used (e.g. for writing the prompt, ChatGPT/Copilot), or state "none"._

## 2. Prompts given

1. **Master prompt** (first message of the session). It contained:
   * the original hiring-assignment brief (AI-assisted box selection system; required deliverables);
   * a detailed specification titled *"MASTER PROMPT: Build, Test, Containerize and Deploy PackWise"*. It asked the AI to act as a senior backend/DevOps engineer and covered:
     * the stack: Django, DRF, PostgreSQL, pytest, drf-spectacular, Docker, GitHub Actions, Render "or another suitable public hosting provider";
     * the app layout (`inventory`, `orders`, `packing`, `config`) and the five models;
     * a 9-step 3D packing algorithm (validation, quantity expansion, orientations, filtering, sorting, Maximal Empty Spaces, Best Short Side Fit, AABB collision checks, results);
     * the recommendation ranking rules, the REST endpoints and test requirements;
     * Docker/CI/CD/deployment requirements and the documentation list.

   It contained explicit instructions not to fabricate test results, deployments, transcripts or personal learnings, to work phase by phase and verify each phase, and to ask before external account actions.
2. **Follow-up prompts / answers.** When the AI asked about the external accounts, I approved a public GitHub repository `SanjayMarathi/PackWise` and gave the Docker Hub username `sanjaymarathi`. Instead of Render, I asked for deployment on my Hugging Face account (Pro), which changed the deployment target.
3. **Web interface request.** After the API was deployed, I pointed out that the assignment needs a working web page that demonstrates the functions, not only an API and Swagger. The AI then built the browser interface in `web/`: an order builder, a 3D packing plan with a loading-sequence player, packing instructions, alternatives, rejection reasons, order history and product/box management. It also added Playwright browser tests.
4. **Theme and AI assistant request.** I shared two packaging reference images (kraft boxes with botanical prints; navy/blush/caramel packaging with organic shapes) and asked for that kind of theme. I also pointed out that an AI assistant chatbot was missing. The AI then built:
   * the kraft-and-ink theme;
   * the `assistant` app (Claude with tool use over the real services, streamed to a chat panel);
   * tests using the real SDK over a scripted transport.
5. **Free API key question.** I asked whether there are free API keys, then asked about the Gemini API. The AI looked up current offers, with sources:
   * Anthropic has no ongoing free tier;
   * Hugging Face PRO includes $2 a month of inference credit;
   * Gemini has a free tier through Google AI Studio.

   It then added Gemini as a second provider. I created a Gemini key and added it to the Space.
6. **Monochrome redesign request.** I shared a third reference screenshot (a modern landing page with faded window cards in the background) and asked for:
   * a strictly black-and-white / white-and-black theme ("not coffee coloured");
   * box pictures in the background instead of code;
   * a resizable assistant console;
   * a light/dark toggle.
   ✍️ Author: _add any later follow-up messages from the transcript._

The exact wording of every prompt is in the exported transcript.

## 3. What the AI produced

Everything in the repository was first drafted by the AI in this session:

* **Packing engine** (`packing/algorithms/`): pure Python, integer units, Maximal Empty Spaces, BSSF, multi-start orderings, optional support constraint, independent collision verification, and the proof vs. heuristic-failure distinction.
* **Django apps:** models with CHECK/UNIQUE/partial-unique constraints, services, strict serializers, views, the error envelope, JSON logging and the health check.
* **Tests:** 590+ tests, including seeded randomized property tests and a multi-threaded concurrency test.
* **Docker:** multi-stage non-root image, compose files, entrypoint.
* **CI and deployment:** GitHub Actions workflows (tests, deploy checklist, gated Docker publish with smoke test, Hugging Face deploy step) and the Hugging Face Space files. A Render blueprint was written first, then replaced when I chose Hugging Face.
* **Docs:** README, this file's factual sections, and TEST_OUTPUT.md (captured from real runs).

The AI also **decided** several things that were not in the prompt. Each is listed here so it can be reviewed:

| Decision | Rationale given |
|---|---|
| Convert cm/kg to **integers** (0.01 cm, 1 g) before geometry | Exact boundary comparisons; no float epsilon |
| Classify rejections as `proven_infeasible` vs `heuristic_failure` | The prompt asked to separate heuristic failure from mathematical proof |
| Try **3 sort orders** (multi-start) | Cheap; a test shows a case only the fallback solves |
| Free-space pruning checks only new fragments | Proof sketch in `free_space.py`; invariants tested exactly |
| `rank` + `strategy` columns on `BoxRecommendation` | Needed to persist and return the ranked alternatives |
| Reject unknown **and read-only** input fields | Mass-assignment protection; silent drops hide client bugs |
| `DELETE` → 409 when referenced (instead of soft delete) | `PROTECT` FKs preserve history; deactivation is explicit |
| `no_feasible_box` returns **200** | Successful computation with a business outcome, not a client error |
| Docker publish runs only **after Tests pass** (`workflow_run`) | Never publish an image from a failing commit |
| `HealthCheckMiddleware` before host validation | Container/platform probes use IP Host headers |
| API left unauthenticated | Simpler for reviewers; documented as a limitation |

✍️ Author: _for each decision above, state whether I accept it, and why (or what I changed)._

## 4. Output that was rejected or modified

These are changes made **during the session**, mostly when the AI caught its own errors through tests or review. All entries are real and can be found in the transcript.

| # | What the AI first produced | What happened | Final state |
|---|---|---|---|
| 1 | Test asserting a 25×25×1 item **cannot** fit a 30×20×30 box | Test failed. The engine was right: the item fits standing on its edge | Test data corrected; correct negative case (30×20×20) added |
| 2 | Same wrong instance in the "no orientation fits" packer test | Failed with the same root cause | Corrected |
| 3 | Test claiming the volume limit was exceeded (50 + 729 = 779 < 1000) | Failed: arithmetic error in the test | Instance changed to a 10×10×10 item |
| 4 | Test reading `placement.item_id` | `AttributeError` (the field is `placement.item.item_id`) | Fixed |
| 5 | Multi-start test built on a **hand-made** instance, guarded by `pytest.skip` | It **did skip**, so it proved nothing | Rewritten with an instance found by a seeded search script; asserts `attempts == 2` |
| 6 | `Order.Status` referenced inside the nested `class Meta` | `NameError` on the first `manage.py check` (class bodies are not enclosing scopes) | Module-level `OrderStatus` enum |
| 7 | Service logged `product.pk` **after** `delete()` | Found in self-review: Django sets `pk` to `None` after delete | `pk` captured before deleting |
| 8 | Support-ratio service test reused the engine-test instance | Hand-tracing showed the fallback ordering solves it, so the test would fail for a legitimate reason | New instance from a seeded search |
| 9 | `BoxEvaluation.feasible` property | Coverage report showed it was never used | Removed |
| 10 | `assert best is not None` in production engine code | Lint (ruff S101): asserts are stripped under `python -O` | Explicit check + exception |
| 11 | Health check behind normal host validation | Design review before deploying: IP-based probes would get 400 and mark the container unhealthy | `HealthCheckMiddleware`; verified with `Host: 10.1.2.3` |
| 12 | Production check required `SECRET_KEY` ≥ 50 chars | Render's `generateValue` yields 44 chars, so the app would never have booted on Render | Threshold 40 + placeholder rejection; test with a 44-char key |
| 13 | Strict-fields mixin raised on unknown keys **before** field validation | Real API output showed only `colour` reported for a payload that also had `length: 0` | All errors now reported together; test added |
| 14 | README sample response partly filled **from memory of an earlier run** (`execution_time_ms` 19.3; a rejected box missing) | Caught by re-reading the captured JSON before committing | Replaced with real values (98.985 ms; `BX-SHOE` included) |
| 15 | `DisallowedHost` logged at ERROR with a traceback per bot request | Seen in the production-like container logs | Logger silenced (as the Django docs recommend) |
| 16 | `check --deploy` warning W021 (HSTS preload) | Preload requires `includeSubDomains`, impossible on a shared platform domain (`onrender.com`, later `hf.space`) | Silenced with a comment explaining why |
| 17 | Render deployment (`render.yaml`, deploy-hook CI step) | I chose Hugging Face Spaces instead | Replaced with `deploy/huggingface/` (Space Dockerfile pinned to the Docker Hub image, `deploy.py`, CI step); uid changed 10001 → 1000 (Spaces' uid); `SPACE_HOST` host detection; CSP `frame-ancestors` so the Space page can embed the app; secure-cookie flag decoupled from the SSL-redirect flag |
| 18 | `FrameAncestorsMiddleware` read `settings.FRAME_ANCESTORS` directly | Self-review: only production settings define it, so it would crash elsewhere | Falls back to an empty list |
| 19 | Image code owned by the runtime user (`COPY --chown`) | Hardening review: a compromised process could rewrite its own code | Code root-owned and read-only; verified `touch /app/x` → permission denied |
| 20 | The first delivery was API + Swagger only | I asked for a real web page | Built the `web` app (Django view + ES-module client + three.js viewer) and browser end-to-end tests |
| 21 | Import map pointed `{% static %}` at a **directory** (`three/addons/`) | Self-review: production's hashed manifest storage has no entry for directories, so every page load would have raised an error, while development looked fine | Exact file mapping; new test runs `collectstatic` with manifest storage and renders the page |
| 22 | 3D camera fitted to the bounding **sphere** | Screenshot review: a flat 50×40×10 box filled about a third of the view | Exact fit that projects the 8 box corners onto the camera axes |
| 23 | `.viewer-card .card-body { padding: 0 }` | Screenshot review: it also removed the legend's padding | Rule scoped to the canvas container |
| 24 | “fits all 1 items” / “All 1 items placed” | Seen in the phone-size screenshot | Singular and plural wording |
| 25 | E2E test used `locator(".toast")` | Test failed with Playwright strict mode: an earlier toast was still visible (the app was right) | Locator narrowed by text |
| 26 | Gunicorn 26 control socket under `$HOME` (= read-only `/app` after #19) | `Control server error: Permission denied` in container logs | `--no-control-socket` (the platform manages the process); verified the error is gone |
| 27 | Dockerfile `# syntax=docker/dockerfile:1.7` line | An extra registry pull with no feature in use (found when a local Docker Hub sign-in broke builds) | Removed |
| 28 | The first UI had no AI assistant and a generic look | I asked for the packaging theme and a chatbot | Theme rewrite; `assistant` app with five tools, NDJSON streaming, append-only history, guardrails |
| 29 | Chat client sent `Accept: application/x-ndjson`; DRF only had a JSON renderer | The **browser test** got a 406 ("Could not satisfy the request Accept header"). The API tests had passed, because the test client sends a default Accept | NDJSON renderer on the chat view; regression test with the browser's real header |
| 30 | `assistant/tests` missing from pytest `testpaths` | Test count stayed at 613: the 46 assistant tests were not collected by the default run (or by CI) | Added; the suite is now 660 |
| 31 | Chat text renderer only made a list when a whole paragraph was bullets | Browser test: "It fits:\n- a\n- b" rendered as plain text, a very common model format | Consecutive bullet lines become a list wherever they appear |
| 32 | Escape handler on the chat panel only | Browser test: offline mode has no input, so focus sat on `<body>` and Escape did nothing | Handler on the document; the close button gets focus when there's no input |
| 33 | Docs screenshot captured mid-scroll | Screenshot review: the recommended-box banner was cut off | Scroll to the top before capturing |
| 34 | Assistant was Claude-only, which is paid | I asked for a free option | Gemini provider (`google-genai`, `gemini-3.6-flash`): same tools and events, thought signatures replayed verbatim, auto provider selection, each conversation pinned to its provider |
| 35 | The kraft/coffee theme | I asked for strict black and white, a backdrop like my reference with boxes, and a resizable console | Monochrome redesign with a light/dark toggle, slab-serif display type, faded "window" backdrop of boxes, and a resizable and maximizable console |
| 36 | (Risk) Gemini's docs pages had moved to a new "Interactions API" and no longer documented `generateContent` function calling | Instead of guessing the SDK, the AI inspected the installed `google-genai` 2.34 and prototyped a streamed function call over a mock transport | Code uses only verified fields (`parameters_json_schema`, `FunctionResponse.id`, `thought_signature`) |
| 37 | Downloaded font licence saved as `OFL…` | Reading the file: Roboto Slab is **Apache 2.0** | Renamed `LICENSE-roboto-slab-Apache-2.0.txt`; README corrected |
| 38 | 3D axis markers still red/green/blue after the redesign | Self-review against "black and white" | Monochrome lines (the width axis dashed) |
| 39 | Backdrop "3D packer" card sat behind the page title | Screenshot review | Moved beside the product list |
| 40 | New browser tests were flaky or wrong | Runs failed intermittently: the console was measured mid-animation; the test assumed it could grow taller in a 720 px viewport; the theme colour was read mid-transition; `expect` kept its 5 s default | Wait for animations and the final colour, a viewport-aware resize test, a 15 s `expect` timeout; then repeated runs were green |

✍️ Author: _add anything I rejected, rewrote or asked the AI to change after reviewing the code myself._

## 5. Mistakes the AI made

From the table above, the AI's mistakes fell into these groups:

* **Wrong test expectations** (#1, #2, #3, #8): careless geometry or arithmetic in hand-written test data, all caught by running the tests or by hand-tracing.
* **Python/Django errors** (#4, #6, #7): an attribute path, class-scope rules, and model state after `delete()`.
* **Tests that could pass without proving anything** (#5): a test guarded by `skip`.
* **Deployment blind spots** (#11, #12): code that passed every local test but would have failed on the target platform.
* **Documentation accuracy** (#14): filling missing data from memory instead of from the real output.

## 6. How the final code was verified

Everything below was **run**, not assumed. The outputs are in the transcript and [TEST_OUTPUT.md](TEST_OUTPUT.md).

1. **Automated tests** against real PostgreSQL 17: the full suite passes, with branch coverage reported (see TEST_OUTPUT.md).
2. **Independent oracles** for the engine:
   * every packing is re-checked by a separate AABB collision checker;
   * 300 seeded random orders are validated against independently recomputed constraints;
   * the Maximal-Empty-Space invariants are checked cell by cell on 40 random grids;
   * the sorted-dimension rotation lemma is compared against brute force over 4,096 cases.
3. **Mutation test of the concurrency protection:** `select_for_update()` was removed temporarily. The concurrent-request test then **failed 3 out of 3 times** with `IntegrityError … recommendation_unique_box_per_order`. The lock was restored and the test passed again. This shows the test and the database constraint both do their job.
4. **Static checks:**
   * `ruff check` / `ruff format --check`;
   * `manage.py makemigrations --check`;
   * `manage.py spectacular --validate --fail-on-warn`;
   * `manage.py check --deploy --fail-level WARNING` against production settings.
5. **Container checks:**
   * `docker compose up --build`: migrations job, healthy web container, running as the non-root uid 1000 with read-only code;
   * a real HTTP flow (create order → recommend → fetch stored result);
   * the production-like compose stack: unknown Host gives 400, probe Host gives 200, security headers present, JSON 404s, JSON logs.
6. **CI:** GitHub Actions runs:
   * lint, migrations and schema validation;
   * tests with a coverage gate (≥ 90%) on Python 3.12 and 3.14;
   * the browser end-to-end tests;
   * the deploy checklist;
   * an image smoke test before publishing (API, plus the web page and its hashed 3D assets).
7. **Web interface:**
   * driven in a real headless Chrome with Playwright, in light, dark and phone layouts;
   * screenshots were inspected after each change, which is how mistakes #22–#24 were found;
   * no JavaScript errors, and no horizontal overflow at 390 px width;
   * six end-to-end tests cover the main journeys and fail on any JavaScript error.
8. **AI assistant without a live key:**
   * the agent loop was tested through the **real `anthropic` SDK** with a mock HTTP transport replaying scripted server-sent-event streams;
   * this exercises the real stream parsing, tool execution, database writes and the exact request bodies;
   * the tests assert, among other things, that each request's history extends the previous one byte-for-byte.

   A conversation with the real model on the live site needs `ANTHROPIC_API_KEY`; see the README.
9. **Deployment:** the public URL https://sanjaymarathi-packwise.hf.space was checked with real requests after CI deployed it:
   * `/api/health/` returned database `ok` and version = the deployed commit SHA;
   * the seeded catalogue was present;
   * create order → recommend returned `BX-M-FLAT` at ₹35, the same as locally, and the stored result matched;
   * an impossible order returned `no_feasible_box`;
   * error envelopes were correct, and Swagger and the schema returned 200;
   * plain HTTP got a 301 to HTTPS;
   * the CSP `frame-ancestors` header was present.

   The `Strict-Transport-Security` header on live responses showed that Hugging Face forwards `X-Forwarded-Proto: https`. Django's own HTTPS redirect, first disabled for the Space as a precaution against redirect loops, was then switched back on and re-verified.

✍️ Author: _describe what I verified personally (e.g. read the algorithm and traced an example by hand, ran the tests myself, tried the Swagger UI, reviewed each file)._
