---
title: PackWise
emoji: 📦
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: 3D packing API that picks the cheapest shipping box
---

# PackWise: Intelligent 3D Packaging & Box Optimization

A Django REST API that recommends the cheapest shipping box that can **physically** hold an order. A pure-Python 3D bin-packing engine (Maximal Empty Spaces with Best Short Side Fit, all six rotations, independent collision verification) places every unit.

* **Web app:** the page itself. Pick products, press *Find the best box*, and explore the 3D packing plan.
* **AI assistant:** *Ask PackWise AI* (bottom right). Describe an order in plain words; Claude runs the real packing engine through tools and explains the result.
* **REST API / Swagger UI:** [`/api/docs/`](/api/docs/)
* **Health:** [`/api/health/`](/api/health/)
* **Source, tests, CI:** https://github.com/SanjayMarathi/PackWise

This Space runs the Docker image `sanjaymarathi/packwise`, built and tested by GitHub Actions. Data is stored in an external managed PostgreSQL database.
