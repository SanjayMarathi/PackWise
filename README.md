# PackWise: Intelligent 3D Packaging & Box Optimization

PackWise is a Django REST API that recommends the **cheapest shipping box that can physically hold an order**. It doesn't just compare volumes. A pure-Python 3D bin-packing engine places every unit, with rotation, inside each candidate box. The placement is then checked by an independent collision checker before it is reported as feasible.

[![Tests](https://github.com/SanjayMarathi/PackWise/actions/workflows/tests.yml/badge.svg)](https://github.com/SanjayMarathi/PackWise/actions/workflows/tests.yml)
[![Docker](https://github.com/SanjayMarathi/PackWise/actions/workflows/docker.yml/badge.svg)](https://github.com/SanjayMarathi/PackWise/actions/workflows/docker.yml)

| | |
|---|---|
| **Live API** | https://sanjaymarathi-packwise.hf.space (Hugging Face Space: https://huggingface.co/spaces/sanjaymarathi/packwise) |
| **Swagger UI** | https://sanjaymarathi-packwise.hf.space/api/docs/ |
| **Health** | https://sanjaymarathi-packwise.hf.space/api/health/ |
| **Docker Hub** | https://hub.docker.com/r/sanjaymarathi/packwise (`latest` + commit-SHA tags) |
| **CI** | https://github.com/SanjayMarathi/PackWise/actions |

The live instance has the demo catalogue (6 boxes, 8 products) loaded. The quickest way to try it is Swagger: `POST /api/orders/` with `{"items": [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 1}]}`, then `POST /api/orders/{id}/recommend/`.

---

## Contents

1. [Problem statement](#1-problem-statement)
2. [Features](#2-features)
3. [Architecture](#3-architecture)
4. [Database design](#4-database-design)
5. [The packing algorithm](#5-the-packing-algorithm)
6. [Limitations and complexity](#6-limitations-and-complexity)
7. [Technology stack](#7-technology-stack)
8. [Local installation](#8-local-installation)
9. [Environment configuration](#9-environment-configuration)
10. [API documentation](#10-api-documentation)
11. [Sample requests and responses](#11-sample-requests-and-responses)
12. [Running the tests](#12-running-the-tests)
13. [Docker](#13-docker)
14. [Docker Hub image](#14-docker-hub-image)
15. [Deployment (Hugging Face Spaces)](#15-deployment-hugging-face-spaces)
16. [Future improvements](#16-future-improvements)
17. [Project documents](#17-project-documents)

---

## 1. Problem statement

When a customer orders several products, the warehouse must choose a box. A box is usable only if:

* every product unit fits inside it, possibly rotated, **without overlapping** any other unit or poking through a wall;
* the total weight does not exceed the box's rated load;
* the box is in stock (active).

Among usable boxes, the business wants the **cheapest**. Comparing total volumes is not enough. Two 6 cm cubes have far less volume than a 10 cm cube box, yet they cannot both fit inside it. PackWise answers the question geometrically.

**Units are fixed throughout the system.** Dimensions are in **centimetres (cm)**, weights in **kilograms (kg)** and cost in **Indian Rupees (INR)**. Volumes in responses are cm³.

## 2. Features

* **Real 3D packing.** The engine uses 3D *Maximal Empty Spaces* with a *Best Short Side Fit* heuristic. It tries all six axis-aligned orientations, applies deterministic tie-breaking, and can retry with three different item orderings.
* **Proof vs. heuristic.** Every rejected box is classified as `proven_infeasible` (weight, size or volume makes it mathematically impossible) or `heuristic_failure` (the heuristic found no arrangement, which does **not** prove none exists).
* **Exact arithmetic.** cm/kg decimals are converted to integers (0.01 cm and 1 g resolution) before any geometry runs, so a 40.00 cm item fits a 40.00 cm box and a 40.01 cm item does not. No floating-point epsilon is involved.
* **Self-verification.** Each packing is re-checked for bounds, overlaps, valid rotations and every unit placed exactly once, using an AABB sweep that is independent of the packer.
* **Configurable ranking.** Strategies are `lowest_cost` (default), `best_utilization` and `smallest_box`. Each can be set per request or server-wide.
* **Optional gravity-support rule.** `PACKWISE_MIN_SUPPORT_RATIO` sets how much of an item's base must rest on something.
* **Loading instructions.** Each placement includes a sequence number, coordinates, rotated extents and an orientation label such as `WLH`.
* **Concurrency-safe persistence.** Results are written under `SELECT … FOR UPDATE`, backed by unique and partial-unique constraints.
* **Production hygiene.** Requests are strictly validated (unknown and read-only fields are rejected). Errors share one envelope, internals never leak, and logs are JSON. Throttling is on, security headers are set, a DB-aware health check is available, and the service runs as a non-root Gunicorn container.
* **Tests and CI.** About 600 tests, ~99% branch coverage, randomized property tests, and CI on Python 3.12 and 3.14 against PostgreSQL 17.

## 3. Architecture

A **modular monolith** with a strict dependency direction:

* `inventory` depends on nothing.
* `orders` depends on `inventory`.
* `packing` depends on `orders` and `inventory`.

The packing **engine** (`packing/algorithms`) imports nothing from Django. It can be unit-tested in milliseconds, and it could be reused outside the web app.

```mermaid
flowchart LR
    client([Client / Swagger UI]) -->|JSON over HTTPS| mw

    subgraph django[Django + DRF process]
        mw[Middleware<br/>health probe · security · WhiteNoise] --> views
        views[Views<br/>inventory · orders · packing] --> serializers[Serializers<br/>strict validation]
        views --> services[Services<br/>order creation · validation · recommendation]
        services --> orm[(Django ORM)]
        services -->|integer units| engine
        subgraph engine[packing/algorithms - pure Python]
            direction TB
            orient[orientations] --> packer[greedy_packer]
            free[free_space<br/>maximal empty spaces] --> packer
            score[scoring<br/>BSSF + box ranking] --> packer
            packer --> collision[collision<br/>independent verification]
        end
    end
    orm --> pg[(PostgreSQL)]
```

```
config/        settings (base / development / production / test), urls, wsgi
common/        error envelope, strict serializer mixin, pagination, JSON logging, health check
inventory/     Product, ShippingBox: models, CRUD API, services, seed command
orders/        Order, OrderItem: creation service, API (create / list / retrieve / items)
packing/
  algorithms/  domain, geometry, orientations, free_space, collision, scoring, greedy_packer
  services/    units (cm/kg <-> int), validation_service, recommendation_service
  models.py    BoxRecommendation
  views.py     POST /recommend/, GET /recommendations/
tests/         cross-app integration, API, edge-case and configuration tests
```

### Recommendation request flow

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant V as RecommendView
    participant S as recommendation_service
    participant E as Packing engine
    participant DB as PostgreSQL
    C->>V: POST /api/orders/{id}/recommend/ {"strategy": ...}
    V->>DB: fetch order (404 if missing)
    V->>S: recommend_box_for_order(order, strategy)
    S->>DB: order items + products, active boxes (cheapest first)
    S->>S: validate order, convert cm/kg to integer units
    loop every active box
        S->>E: necessary_condition_violations(items, box)
        alt provably impossible
            E-->>S: weight / size / volume reasons
        else may fit
            S->>E: pack(items, box)
            E-->>S: FEASIBLE + placements, or HEURISTIC_FAILURE
        end
    end
    S->>S: rank feasible boxes by strategy
    S->>DB: BEGIN, SELECT order FOR UPDATE, replace recommendations, set status, COMMIT
    S-->>V: outcome
    V-->>C: 200 {recommendation, alternatives, rejected_boxes, summary}
```

## 4. Database design

```mermaid
erDiagram
    PRODUCT ||--o{ ORDER_ITEM : "ordered as (PROTECT)"
    ORDER ||--|{ ORDER_ITEM : "contains (CASCADE)"
    ORDER ||--o{ BOX_RECOMMENDATION : "ranked boxes (CASCADE)"
    SHIPPING_BOX ||--o{ BOX_RECOMMENDATION : "recommended as (PROTECT)"

    PRODUCT {
        bigint id PK
        varchar sku UK "stored upper-case"
        varchar name
        decimal length "cm, > 0"
        decimal width "cm, > 0"
        decimal height "cm, > 0"
        decimal weight "kg, > 0"
        bool is_active
        timestamptz created_at
        timestamptz updated_at
    }
    SHIPPING_BOX {
        bigint id PK
        varchar box_code UK
        varchar name
        decimal internal_length "cm, > 0"
        decimal internal_width "cm, > 0"
        decimal internal_height "cm, > 0"
        decimal max_weight "kg, > 0"
        decimal cost "INR, >= 0"
        bool is_active
    }
    ORDER {
        bigint id PK
        varchar order_number UK
        varchar status "pending | recommended | no_feasible_box"
        timestamptz created_at
        timestamptz updated_at
    }
    ORDER_ITEM {
        bigint id PK
        bigint order_id FK
        bigint product_id FK
        int quantity ">= 1"
    }
    BOX_RECOMMENDATION {
        bigint id PK
        bigint order_id FK
        bigint box_id FK
        smallint rank "1 = selected"
        varchar strategy
        decimal total_weight "kg"
        decimal box_cost "INR snapshot"
        decimal utilization_percentage "0-100"
        jsonb packing_details "placements + metadata"
        bool is_selected
        timestamptz created_at
    }
```

**Constraints enforced by PostgreSQL**, so they hold even if application code has a bug:

| Table | Constraint | Why |
|---|---|---|
| product | `CHECK length, width, height, weight > 0` | An item with no size or weight is meaningless to the packer |
| shipping_box | `CHECK internal dims > 0, max_weight > 0, cost >= 0` | Free boxes are allowed, negative costs are not |
| order | `CHECK status IN (…)` | Status can never drift outside the enum |
| order_item | `UNIQUE (order, product)`, `CHECK quantity >= 1` | One line per product; quantities are explicit |
| box_recommendation | `UNIQUE (order, box)`, `UNIQUE (order, rank)` | No duplicate boxes or ranks per order |
| box_recommendation | **partial** `UNIQUE (order) WHERE is_selected` | At most one selected box per order |
| index | `box_active_cost_idx (is_active, cost)` | Matches the engine's "active boxes, cheapest first" query |

`PROTECT` foreign keys keep history intact. A product that appears in an order, or a box that appears in a stored recommendation, cannot be deleted. The API answers **409** and suggests `PATCH {"is_active": false}` instead. `box_cost` is a snapshot, so changing a box's price later doesn't rewrite past recommendations.

## 5. The packing algorithm

Code: [`packing/algorithms/`](packing/algorithms/). The engine works in **integer units**: 1 length unit = 0.01 cm and 1 weight unit = 1 g. [`packing/services/units.py`](packing/services/units.py) converts the database's `DECIMAL(…, 2)` cm and `DECIMAL(…, 3)` kg values exactly, and refuses any value it would have to round.

### Step 1: Validate input
The domain dataclasses (`ItemLine`, `Item`, `Container`) reject non-integer, zero, negative and boolean values. The service layer adds the business rules: the order is non-empty, it has at most `PACKWISE_MAX_ITEMS_PER_ORDER` units, and its products are valid.

### Step 2: Expand quantities
`Laptop × 2, Mouse × 3` becomes five `Item`s with ids `1#1, 1#2, 2#1, 2#2, 2#3`. Each keeps its `product_id` and SKU.

### Step 3: Generate orientations
Up to six permutations of (L, W, H), in a fixed order: `LWH, LHW, WLH, WHL, HLW, HWL`. Duplicates are dropped when dimensions are equal, so a cube has 1 orientation and a square prism has 3. Results are cached per dimension triple.

### Step 4: Preliminary filtering (proofs)
A box is **provably** impossible, and the expensive packer never runs, if any of these hold:

* **Weight:** the total order weight exceeds `max_weight`.
* **Size:** any item fits no orientation. The test uses a lemma: sort both dimension triples, and the item fits in *some* rotation **iff** `sorted(item)[k] ≤ sorted(box)[k]` for every k. A test checks this against brute force over 4,096 combinations.
* **Volume:** the total item volume exceeds the box volume.

Passing all three does **not** prove a packing exists. It only means the box is worth trying.

### Step 5: Deterministic ordering
Items are sorted largest and hardest-to-place first:

1. `volume_desc`: volume, then longest edge, then second edge.
2. `longest_edge_desc` (fallback).
3. `base_area_desc` (fallback).

Ties are broken by `(product_id, item_id)`, so the same order always produces the same packing, whatever order the items arrive in. A test shuffles the input and checks this.

### Step 6: Free-space management (Maximal Empty Spaces)
The empty part of the box is a list of **maximal** empty cuboids. They may overlap each other, but none is contained in another. At first the whole box is one space. When an item is placed:

1. Each free space that **intersects** the item is removed and split into up to six slabs: the parts entirely to the left, right, front, back, below and above the item. Each slab keeps the parent's full extent on the other two axes, which is what keeps it maximal.
2. Degenerate slabs, exact duplicates, and slabs **contained** in any other space are discarded. Only the new fragments need checking. An untouched space can never be inside a fragment, because a fragment is a subset of a space that was already maximal.
3. Spaces too small for the smallest remaining item are dropped. This is safe because future spaces are always subsets of current ones.

Three invariants are checked **exactly** by placing random items and testing every unit cell on 40 seeded grids:

* no free space overlaps a placed item;
* free space and placed items together tile the box exactly;
* no space contains another.

### Step 7: Placement (Best Short Side Fit)
For the current item, every (free space × orientation) pair where the item fits is scored. The score is the leftover gap on each axis, sorted ascending as `(short, middle, long)`, and the smallest score wins lexicographically. This is the 3D generalization of 2D BSSF. Ties are broken by lowest `z`, then `y`, then `x`, then orientation index, which keeps loads low and makes the result independent of iteration order. The item is placed at the chosen space's minimum corner.

If `min_support_ratio > 0`, any candidate above the floor must have at least that share of its base resting on the top faces of items directly below it.

### Step 8: Collision verification
[`collision.py`](packing/algorithms/collision.py) independently checks:

* every item lies inside the box walls;
* every placed extent is a real rotation of the item;
* no two items overlap with positive volume (touching faces, edges and corners are allowed);
* every expected unit is placed exactly once.

Overlaps are found with a sweep along x, which avoids checking all n² pairs. Any violation raises `PackingIntegrityError` (a bug, never a user error). 300 seeded random orders are verified this way in the test suite.

### Step 9: Result
`PackingResult` carries: `status` (`feasible`, `proven_infeasible` or `heuristic_failure`), the placements (coordinates, rotated extents, orientation), unplaced items, used volume, box volume, total weight, utilization %, machine-readable reasons, the sort strategy that succeeded, the number of attempts and the execution time.

### Box ranking
Feasible boxes are ranked by a strategy from [`scoring.py`](packing/algorithms/scoring.py):

| Strategy | Sort key (ascending) |
|---|---|
| `lowest_cost` (default) | cost → **−utilization** → box volume → box id |
| `best_utilization` | −utilization → cost → volume → id |
| `smallest_box` | volume → cost → −utilization → id |

Utilization is compared as an exact `Fraction`, so ties are genuine ties. The default comes from `PACKWISE_RANKING_STRATEGY`. A request can override it with `{"strategy": "best_utilization"}`.

## 6. Limitations and complexity

**Complexity.** Let *n* be the number of units, *m* the number of free spaces (typically O(n), worst case higher) and *k* the number of spaces an item intersects.

* Each placement scores at most 6·m candidates, splits k spaces into ≤ 6k fragments, and prunes in O(k·m + k²).
* One pass is about O(n·m·(6 + k)), roughly O(n²) on typical inputs. There are at most 3 passes per box, and verification is a sweep that is near-linear in sparse layouts and O(n²) at worst.
* A request multiplies all of this by the number of active boxes.

**Measured** (pure engine, this repository, Python 3.14 on a laptop):

| Case | Units | Result | Time |
|---|---|---|---|
| Mixed sizes, roomy box | 50 | feasible, 1 attempt | 29 ms |
| Mixed sizes, roomy box | 200 | feasible, 1 attempt | 226 ms |
| Mixed sizes, tight box (all 3 orderings tried) | 200 | heuristic failure | 470 ms |
| Identical cubes, exact 100% fill | 200 | feasible | 11 ms |

`PACKWISE_MAX_ITEMS_PER_ORDER` (default 200) bounds the work per request, and the recommend endpoint has its own tighter throttle.

**Limitations (known and deliberate):**

* **Heuristic, not exact.** 3D bin packing is NP-hard. A `heuristic_failure` means "not found", not "impossible". This is visible in the API, and an instance where only the fallback ordering succeeds is part of the tests.
* Items are rigid, axis-aligned cuboids. There are no "this side up", fragility, stacking-load, centre-of-gravity or deformable-item (bags) rules.
* Placements are only tried at free-space minimum corners. Overhang is allowed unless `PACKWISE_MIN_SUPPORT_RATIO` is set, on the assumption that void fill is used.
* Orders are never split across several boxes. If no single box fits, the result is `no_feasible_box`.
* Recommendations use the products' **current** dimensions. Each stored recommendation keeps its own snapshot in `packing_details`.
* The API is **unauthenticated** for ease of review. It is protected only by validation and throttling, and throttle counters are per-process (local memory).

## 7. Technology stack

| Concern | Choice |
|---|---|
| Language | Python 3.12 (Docker/CI), also tested on 3.14 |
| Web | Django 5.2 LTS, Django REST Framework 3.18 |
| Database | PostgreSQL 17 via psycopg 3, `dj-database-url` |
| API docs | drf-spectacular (OpenAPI 3, Swagger UI, ReDoc) |
| Serving | Gunicorn, WhiteNoise (static files) |
| Tests | pytest, pytest-django, pytest-cov, DRF `APIClient` |
| Quality | ruff (lint + format), `manage.py check --deploy`, schema validation |
| DevOps | Docker (multi-stage, non-root), Docker Compose, GitHub Actions, Docker Hub, Hugging Face Spaces (Docker SDK) |

Versions are pinned in [`requirements.txt`](requirements.txt) and [`requirements-dev.txt`](requirements-dev.txt).

## 8. Local installation

Prerequisites: Python 3.12+, and Docker (for PostgreSQL) or a local PostgreSQL server.

```bash
git clone <repository-url> PackWise && cd PackWise
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# PostgreSQL on localhost:5432 (user/password/db: packwise)
docker run -d --name packwise-pg -p 5432:5432 \
  -e POSTGRES_USER=packwise -e POSTGRES_PASSWORD=packwise -e POSTGRES_DB=packwise \
  postgres:17-alpine

python manage.py migrate
python manage.py seed_demo_data      # 6 demo boxes + 8 demo products (idempotent)
python manage.py runserver           # http://127.0.0.1:8000/api/docs/
```

`manage.py` defaults to `config.settings.development` (DEBUG on, browsable API, default local database URL). Set `DATABASE_URL` to point anywhere else.

## 9. Environment configuration

All configuration comes from environment variables. See [`.env.example`](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.development` (manage.py), `…production` (WSGI/Docker) | Settings module |
| `DJANGO_SECRET_KEY` | dev-only key in development; **required** in production (≥ 40 chars) | Cryptographic signing |
| `DATABASE_URL` | `postgres://packwise:packwise@localhost:5432/packwise` (dev/test); **required** in production | Database |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,…` (dev); **required** in production unless `SPACE_HOST` is set | Host header allow-list |
| `SPACE_HOST` | set by Hugging Face Spaces | Added to `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` automatically |
| `DJANGO_SECURE_SSL_REDIRECT` | `true` (production) | Redirect HTTP→HTTPS in Django (turn off only if the edge already does it) |
| `DJANGO_SECURE_COOKIES` | `true` (production) | `Secure` flag on session/CSRF cookies |
| `DJANGO_FRAME_ANCESTORS` | empty (`X-Frame-Options: DENY`) | Origins allowed to embed the app (CSP `frame-ancestors`) |
| `DJANGO_SECURE_HSTS_SECONDS` | `3600` | HSTS max-age |
| `PACKWISE_RANKING_STRATEGY` | `lowest_cost` | Default ranking strategy |
| `PACKWISE_MAX_ITEMS_PER_ORDER` | `200` | Max units per order (bounds CPU per request) |
| `PACKWISE_MAX_LINES_PER_ORDER` | `50` | Max distinct products per order |
| `PACKWISE_MIN_SUPPORT_RATIO` | `0` | 0 = overhang allowed, 1 = full base support |
| `THROTTLE_ANON_RATE` / `THROTTLE_RECOMMEND_RATE` | `120/minute` / `30/minute` | Rate limits |
| `RUN_MIGRATIONS` | `false` | Container runs `migrate` before Gunicorn (for platforms without a pre-deploy hook) |
| `SEED_DEMO_DATA` | `false` | Container loads the demo catalogue after migrating |
| `WEB_CONCURRENCY`, `PORT`, `GUNICORN_TIMEOUT` | `2`, `8000`, `60` | Gunicorn |
| `LOG_FORMAT`, `LOG_LEVEL` | `text`/`json` (prod), `INFO` | Logging |

## 10. API documentation

Interactive documentation is at **`/api/docs/`** (Swagger UI), with **`/api/redoc/`** (ReDoc) and the raw schema at **`/api/schema/`**. The root URL `/` redirects to Swagger.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health/` | Liveness + database check (`200` or `503`) |
| `POST` | `/api/products/` | Create product |
| `GET` | `/api/products/?is_active=&search=&page=&page_size=` | List (paginated, filterable) |
| `GET` / `PATCH` / `DELETE` | `/api/products/{id}/` | Retrieve / partial update / delete (`409` if used in an order) |
| `POST` | `/api/boxes/` | Create shipping box |
| `GET` | `/api/boxes/?is_active=&search=` | List (cheapest first) |
| `GET` / `PATCH` / `DELETE` | `/api/boxes/{id}/` | Retrieve / update / delete (`409` if referenced) |
| `POST` | `/api/orders/` | Create order with items (`order_number` optional) |
| `GET` | `/api/orders/?status=` | List orders, newest first |
| `GET` | `/api/orders/{id}/` | Order with items, total units and weight |
| `GET` | `/api/orders/{id}/items/` | Order lines (paginated) |
| `POST` | `/api/orders/{id}/recommend/` | Run the engine, store and return ranked boxes |
| `GET` | `/api/orders/{id}/recommendations/` | Stored recommendation + alternatives |

**Conventions**

* Requests and responses are JSON. Decimals are rendered as JSON numbers.
* `PUT` is not offered; use `PATCH`. Orders are immutable once created.
* Unknown **and** read-only input fields are rejected with 400 instead of being ignored silently. This guards against mass assignment, e.g. `"status": "recommended"`.
* SKUs, box codes and order numbers are normalized to upper case, and uniqueness is case-insensitive.
* `no_feasible_box` is a **successful** computation, so it returns `200` with `"status": "no_feasible_box"`.

**Status codes:** `200`, `201`, `204`, `400` (validation, malformed JSON), `404`, `405`, `409` (in use / conflict), `415`, `422` (order cannot be processed, e.g. empty), `429` (throttled, with `Retry-After`), `500` (generic message, details logged), `503` (health: DB down).

**Error envelope** (every error):

```json
{"status": "error", "error": {"code": "validation_error", "message": "Request validation failed.",
  "details": {"length": ["Ensure this value is greater than or equal to 0.01."], "colour": ["Unknown field."]}}}
```

## 11. Sample requests and responses

These are real responses from the local Docker stack with the seeded demo catalogue. Long arrays are trimmed with `…`.

**Create a product**: `POST /api/products/`

```json
{"name": "Bluetooth Speaker", "sku": "spk-bt-01", "length": 18, "width": 8, "height": 8, "weight": 0.65}
```
```json
{
  "id": 9, "name": "Bluetooth Speaker", "sku": "SPK-BT-01",
  "length": 18.0, "width": 8.0, "height": 8.0, "weight": 0.65, "volume": 1152.0,
  "is_active": true, "created_at": "2026-11-05T06:01:46.347164Z", "updated_at": "2026-11-05T06:01:46.347731Z"
}
```

**Create a box**: `POST /api/boxes/`

```json
{"name": "Shoe Box", "box_code": "bx-shoe", "internal_length": 35, "internal_width": 22,
 "internal_height": 13, "max_weight": 5, "cost": 18}
```
```json
{
  "id": 7, "name": "Shoe Box", "box_code": "BX-SHOE",
  "internal_length": 35.0, "internal_width": 22.0, "internal_height": 13.0, "internal_volume": 10010.0,
  "max_weight": 5.0, "cost": 18.0, "is_active": true, "created_at": "…", "updated_at": "…"
}
```

**Create an order**: `POST /api/orders/` (2 × laptop 33×23×2 cm, 1 × mouse 12×7×4 cm)

```json
{"items": [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 1}]}
```
```json
{
  "id": 2, "order_number": "ORD-20261105-72046676", "status": "pending",
  "total_units": 3, "total_weight": 2.9,
  "items": [
    {"id": 3, "product_id": 1, "sku": "LAPTOP-14", "name": "14-inch Laptop", "quantity": 2,
     "unit_weight": 1.4, "dimensions": {"length": 33.0, "width": 23.0, "height": 2.0}},
    {"id": 4, "product_id": 2, "sku": "MOUSE-WL", "name": "Wireless Mouse", "quantity": 1,
     "unit_weight": 0.1, "dimensions": {"length": 12.0, "width": 7.0, "height": 4.0}}
  ],
  "created_at": "2026-11-05T06:01:47.020930Z", "updated_at": "2026-11-05T06:01:47.020947Z"
}
```

**Recommend a box**: `POST /api/orders/2/recommend/` with body `{}` (or `{"strategy": "best_utilization"}`)

```json
{
  "order_id": 2,
  "order_number": "ORD-20261105-72046676",
  "status": "success",
  "order_status": "recommended",
  "strategy": "lowest_cost",
  "generated_at": "2026-11-05T06:01:47.455381Z",
  "recommendation": {
    "recommendation_id": 5, "rank": 1,
    "box_id": 4, "box_code": "BX-M-FLAT", "box_name": "Medium Flat",
    "cost": 35.0, "total_weight": 2.9, "utilization": 16.86, "packing_feasible": true,
    "box_dimensions": {"length": 50.0, "width": 40.0, "height": 10.0},
    "box_volume_cm3": 20000.0, "used_volume_cm3": 3372.0,
    "sort_strategy": "volume_desc", "execution_time_ms": 0.137,
    "placements": [
      {"sequence": 1, "item_id": "1#1", "product_id": 1, "sku": "LAPTOP-14",
       "position": {"x": 0.0, "y": 0.0, "z": 0.0},
       "dimensions": {"length": 23.0, "width": 33.0, "height": 2.0}, "orientation": "WLH", "rotated": true},
      {"sequence": 2, "item_id": "1#2", "product_id": 1, "sku": "LAPTOP-14",
       "position": {"x": 23.0, "y": 0.0, "z": 0.0},
       "dimensions": {"length": 23.0, "width": 33.0, "height": 2.0}, "orientation": "WLH", "rotated": true},
      {"sequence": 3, "item_id": "2#1", "product_id": 2, "sku": "MOUSE-WL",
       "position": {"x": 46.0, "y": 0.0, "z": 0.0},
       "dimensions": {"length": 4.0, "width": 12.0, "height": 7.0}, "orientation": "HLW", "rotated": true}
    ]
  },
  "alternatives": [
    {"rank": 2, "box_code": "BX-M", "cost": 35.0, "utilization": 14.05, "…": "…"},
    {"rank": 3, "box_code": "BX-L", "cost": 55.0, "utilization": 3.51, "…": "…"},
    {"rank": 4, "box_code": "BX-XL", "cost": 90.0, "utilization": 1.41, "…": "…"}
  ],
  "rejected_boxes": [
    {"box_id": 1, "box_code": "BX-XS", "box_name": "Extra Small Mailer", "feasibility": "proven_infeasible",
     "reasons": ["Order weight 2.9 kg exceeds the box limit of 1.0 kg.",
                 "LAPTOP-14 (33.00×23.00×2.00 cm) cannot fit inside the box in any orientation.",
                 "Total item volume 3372.0 cm³ exceeds the box volume of 750.0 cm³."]},
    {"box_id": 7, "box_code": "BX-SHOE", "box_name": "Shoe Box", "feasibility": "proven_infeasible",
     "reasons": ["LAPTOP-14 (33.00×23.00×2.00 cm) cannot fit inside the box in any orientation."]},
    {"box_id": 2, "box_code": "BX-S", "box_name": "Small", "feasibility": "proven_infeasible",
     "reasons": ["LAPTOP-14 (33.00×23.00×2.00 cm) cannot fit inside the box in any orientation."]}
  ],
  "summary": {"total_units": 3, "total_weight": 2.9, "boxes_evaluated": 7, "feasible_boxes": 4,
              "execution_time_ms": 98.985}
}
```

How to read this:

* `BX-M-FLAT` and `BX-M` both cost ₹35. The same items fill more of the flat box (16.86% vs 14.05%), so it wins the tie.
* The laptops lie side by side, rotated 90° (`WLH`: the laptop's width runs along the box's length).
* The mouse stands on its side in the remaining 4 cm strip at x = 46–50.
* Boxes that cannot work are rejected **with proof**. The 22 cm-wide shoe box (₹18) is cheaper, but the 23 cm laptop cannot fit it in any rotation.
* `execution_time_ms` in `summary` covers the whole request pipeline. The per-box value inside a recommendation is the engine's own time.

**No box fits**: 6 boxed monitors (45 kg) give `200` with `"status": "no_feasible_box"`:

```json
{
  "order_id": 3, "status": "no_feasible_box", "order_status": "no_feasible_box",
  "recommendation": null, "alternatives": [],
  "rejected_boxes": [
    {"box_code": "BX-M", "feasibility": "proven_infeasible", "reasons": [
      "Order weight 45.0 kg exceeds the box limit of 15.0 kg.",
      "MONITOR-27 (70.00×45.00×15.00 cm) cannot fit inside the box in any orientation.",
      "Total item volume 283500.0 cm³ exceeds the box volume of 24000.0 cm³."]},
    "…"
  ]
}
```

**Stored result**: `GET /api/orders/2/recommendations/` returns the same `recommendation` and `alternatives`, plus `strategy` and `generated_at`. Before any run, `status` is `not_generated`.

## 12. Running the tests

```bash
# Needs PostgreSQL (see section 8). Tests use config.settings.test and create their own test database.
pytest                                   # ~600 tests, ~6 s
pytest --cov --cov-report=term-missing   # with branch coverage
pytest packing/tests -p no:django        # the pure engine alone, no database needed
ruff check . && ruff format --check .
```

| Suite | What it covers |
|---|---|
| `packing/tests/` | Geometry, orientations (incl. a brute-force lemma check), free-space splitting and exact MES invariants, collision detection, BSSF and box ranking, packer behaviour, 300 seeded random orders verified independently |
| `tests/test_packing.py` | Engine ↔ Django integration: exact unit conversion, 0.01 cm / 1 g boundaries, human-readable reasons |
| `tests/test_recommendations.py` | Business rules: cheapest box, equal-cost utilization tie-break, inactive boxes, weight limits, no feasible box, strategies, heuristic vs. proof, persistence, DB constraints, **multi-threaded concurrency** |
| `tests/test_api.py` | Every endpoint, validation errors, 404/405/409/415/422/429/500 envelopes, mass-assignment rejection, health probe, OpenAPI schema |
| `tests/test_edge_cases.py` | CHECK/UNIQUE/PROTECT constraints, snapshots, error-handler mapping, JSON logging |
| `tests/test_configuration.py` | Env helpers, production settings fail fast (missing/weak secret, missing hosts), seed command |

Real output is in [TEST_OUTPUT.md](TEST_OUTPUT.md), and CI runs on every push and pull request.

## 13. Docker

```bash
docker compose up --build          # API on http://localhost:8000/api/docs/ , PostgreSQL on localhost:5433
docker compose down -v             # stop and delete the database volume
```

* **Image:** multi-stage build (wheels built in a throwaway stage), `python:3.12-slim`, static files collected at build time, runs as the unprivileged user `app` (uid 1000, the uid Hugging Face Spaces uses) with root-owned, read-only code, Gunicorn on `$PORT`, plus a `HEALTHCHECK` on `/api/health/`.
* **Compose:** `db` (PostgreSQL 17 with a health check and a persistent `pgdata` volume), then `migrate` (a one-shot job that runs `migrate` and loads the demo data), then `web`. Web starts only after the database is healthy **and** migrations have completed, so replicas never race on schema changes.
* **Production-like run:** [`docker-compose.prod.yml`](docker-compose.prod.yml) uses production settings, JSON logs, a required secret and DB password, and can pull the published image:

```bash
cp .env.example .env               # set DJANGO_SECRET_KEY and POSTGRES_PASSWORD
docker compose -f docker-compose.prod.yml --env-file .env up -d
```

The entrypoint ([`docker/entrypoint.sh`](docker/entrypoint.sh)) accepts `web` (default), `migrate`, or any command, e.g. `docker compose run --rm web python manage.py createsuperuser`.

## 14. Docker Hub image

The **Docker** workflow publishes `<dockerhub-user>/packwise` with two tags, `latest` and the full commit SHA. It runs only **after the Tests workflow has passed** for a push to `main`. Before pushing, it boots the image against PostgreSQL and runs a real create-order → recommend request.

```bash
docker pull <dockerhub-user>/packwise:latest
docker run --rm -p 8000:8000 \
  -e DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')" \
  -e DATABASE_URL=postgres://user:pass@host:5432/packwise \
  -e DJANGO_ALLOWED_HOSTS=localhost -e DJANGO_SECURE_SSL_REDIRECT=false \
  -e RUN_MIGRATIONS=true -e SEED_DEMO_DATA=true \
  <dockerhub-user>/packwise:latest
```

Required repository secrets: `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (a Docker Hub access token, not your password).

Optional, to redeploy the Hugging Face Space automatically after each push:

* secret `HF_TOKEN`: a Hugging Face token with write access to the Space;
* repository variable `HF_SPACE_ID`, e.g. `sanjaymarathi/packwise`.

## 15. Deployment (Hugging Face Spaces)

The API runs as a **Docker Space** that executes the **published Docker Hub image**. Nothing is rebuilt from source on the platform. The data lives in an external managed **PostgreSQL** database.

```mermaid
flowchart LR
    gh[GitHub push to main] --> tests[Tests workflow]
    tests -->|passed| docker[Docker workflow<br/>build, smoke test, push]
    docker -->|latest + SHA tags| hub[(Docker Hub<br/>sanjaymarathi/packwise)]
    docker -->|deploy.py commits<br/>FROM image:SHA| space[Hugging Face Space<br/>Docker SDK]
    hub -->|pulled at build| space
    space -->|DATABASE_URL, TLS| db[(Managed PostgreSQL)]
    user([Reviewer]) -->|HTTPS| space
```

[`deploy/huggingface/`](deploy/huggingface/) holds everything the Space needs:

* `Dockerfile`: `FROM docker.io/sanjaymarathi/packwise:<tag>`, plus platform settings (port 7860, `RUN_MIGRATIONS=true`, demo seed, framing allowed only for `huggingface.co`);
* `README.md`: the Space card (`sdk: docker`, `app_port: 7860`);
* `deploy.py`: pins the image tag and commits both files to the Space, which makes Hugging Face rebuild and restart it.

**One-time setup**

1. Create the managed PostgreSQL database and copy its connection string (with `sslmode=require`). The live instance uses **Neon** (PostgreSQL 17, AWS us-east-1, direct connection without pooling).
2. Create the Space (`deploy.py --create`), or let CI create it.
3. In the Space settings → *Variables and secrets*, add the secrets:
   * `DJANGO_SECRET_KEY`: generate one with `python -c "import secrets; print(secrets.token_urlsafe(64))"`;
   * `DATABASE_URL`: the connection string from step 1.
4. Deploy:

```bash
pip install huggingface_hub
python deploy/huggingface/deploy.py --space sanjaymarathi/packwise \
    --image docker.io/sanjaymarathi/packwise:<commit-sha> --create
```

After that, every push to `main` that passes the tests is deployed automatically, as long as `HF_TOKEN` and `HF_SPACE_ID` are configured (see section 14).

**Production behaviour**

* `DEBUG=False`, and the app refuses to start without a strong `DJANGO_SECRET_KEY` and a `DATABASE_URL`.
* `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` come from `SPACE_HOST`, which Hugging Face sets (e.g. `sanjaymarathi-packwise.hf.space`).
* TLS is terminated at Hugging Face's edge, which redirects plain HTTP with a 301. Django trusts `X-Forwarded-Proto`, sends HSTS, keeps cookies `Secure`, and keeps its own HTTPS redirect on as a second layer.
* Migrations run at container start; Django migrations take locks, so restarts are safe.
* The Space page on huggingface.co embeds the app in an iframe. That one origin is allowed via CSP `frame-ancestors`; every other origin still gets the default deny.
* The health probe bypasses host validation, since platform probes connect by IP. See [`common/middleware.py`](common/middleware.py).

## 16. Future improvements

* **Multi-box shipments:** split an order across boxes, minimizing total cost.
* **Product handling rules:** keep upright, fragile on top, maximum stacking load, centre-of-gravity limits.
* **Stronger search:** extreme-point placement, local search or beam search over orderings; an exact CP-SAT model for small orders, to *prove* infeasibility where the heuristic fails.
* **Courier-aware cost:** dimensional weight and carrier rate cards, not just box cost.
* **Platform:** token/JWT authentication with roles; Redis for shared throttling and caching; background jobs for very large orders; OpenTelemetry tracing.
* **3D visualizer:** use the placement data (e.g. three.js) as a packing guide for warehouse staff.

## 17. Project documents

* [AI_USAGE.md](AI_USAGE.md): AI tools, prompts, what was kept or changed, mistakes found, verification.
* [TEST_OUTPUT.md](TEST_OUTPUT.md): real terminal output of the test suite and coverage.
* [LEARNINGS.md](LEARNINGS.md): **written by the author personally** (not AI-generated).
* Chat transcript: exported by the author from the original AI session (see AI_USAGE.md).

## License

[MIT](LICENSE)
