// Interactive 3D view of a packing result (three.js).
//
// The engine's frame: origin = back-left-bottom inner corner of the box,
// x along the length (to the right), y along the width (to the front), z up.
// three.js is y-up, so engine (x, y, z) maps to three (x, z, y). The box is
// centred on the origin so the camera can orbit around it.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

function cssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function webglAvailable() {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

export class PackingViewer {
  constructor(host) {
    this.host = host;
    this.meshes = [];
    this.disposed = false;
    this.wasConnected = false;
    if (!webglAvailable()) {
      this.failed = true;
      host.append(Object.assign(document.createElement("div"), {
        className: "viewer-fallback",
        textContent: "3D preview needs WebGL, which this browser has disabled. The packing instructions below are complete.",
      }));
      return;
    }

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.domElement.setAttribute("aria-label", "3D view of the packed box. Drag to rotate, scroll to zoom.");
    this.renderer.domElement.setAttribute("role", "img");
    host.append(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(35, 1.6, 0.1, 10000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x9aa3b5, 2.4));
    const sun = new THREE.DirectionalLight(0xffffff, 1.8);
    sun.position.set(0.8, 2, 1.4);
    this.scene.add(sun);

    this.content = new THREE.Group();
    this.scene.add(this.content);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(host);
    this.resize();
    this.renderer.setAnimationLoop(() => this.frame());
  }

  frame() {
    if (this.host.isConnected) {
      this.wasConnected = true;
    } else {
      if (this.wasConnected) this.dispose(); // the view was removed from the page
      return;
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  resize() {
    if (this.failed || this.disposed) return;
    const width = this.host.clientWidth || 640;
    const height = this.host.clientHeight || 400;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    if (this.dims) this.fit();
  }

  /** Draw one box option: its shell, axes and every placed item. */
  show(option, colorFor) {
    if (this.failed) return;
    this.clearContent();
    const { length: L, width: W, height: H } = option.box_dimensions;
    this.dims = { L, W, H };
    const edgeColor = new THREE.Color(cssVar("--viewer-edge", "#5b6475"));

    const shellGeometry = new THREE.BoxGeometry(L, H, W);
    this.content.add(new THREE.LineSegments(new THREE.EdgesGeometry(shellGeometry), new THREE.LineBasicMaterial({ color: edgeColor })));
    shellGeometry.dispose();

    // An open kraft carton: cardboard floor, plus the two walls facing away from the camera
    // (back and left). The front and right walls are drawn as edges only, so nothing hides the items.
    const wallColor = new THREE.Color(cssVar("--viewer-wall", "#000000"));
    const wallOpacity = Number.parseFloat(cssVar("--viewer-wall-opacity", "0.06")) || 0.06;
    const panel = (width, height, opacity) =>
      new THREE.Mesh(
        new THREE.PlaneGeometry(width, height),
        new THREE.MeshBasicMaterial({ color: wallColor, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false }),
      );
    const floor = panel(L, W, wallOpacity * 2.2);
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -H / 2 - 0.01;
    const back = panel(L, H, wallOpacity * 1.2);
    back.position.z = -W / 2 - 0.01;
    const left = panel(W, H, wallOpacity);
    left.rotation.y = Math.PI / 2;
    left.position.x = -L / 2 - 0.01;
    this.content.add(floor, back, left);

    // Axis markers at the engine origin (back-left-bottom corner).
    const origin = new THREE.Vector3(-L / 2, -H / 2, -W / 2);
    const axisLength = Math.max(L, W, H) * 0.16;
    // Monochrome axis markers: x and z solid, y (width) dashed, as in the legend chip.
    this.content.add(
      axis(origin, new THREE.Vector3(axisLength, 0, 0), edgeColor),
      axis(origin, new THREE.Vector3(0, 0, axisLength), edgeColor, axisLength / 12),
      axis(origin, new THREE.Vector3(0, axisLength, 0), edgeColor),
    );

    // Items share a few accent colours, so a crisp outline (ink in light mode, chalk in dark) keeps them apart.
    const itemEdge = new THREE.Color(cssVar("--viewer-item-edge", "#000000"));
    this.meshes = option.placements.map((placement) => {
      const d = placement.dimensions;
      const p = placement.position;
      // A hair-thin gap so adjacent items read as separate objects.
      const gap = Math.min(0.15, Math.min(d.length, d.width, d.height) * 0.02);
      const geometry = new THREE.BoxGeometry(
        Math.max(d.length - gap, 0.01),
        Math.max(d.height - gap, 0.01),
        Math.max(d.width - gap, 0.01),
      );
      const color = new THREE.Color(colorFor(placement.product_id));
      const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0.05 }));
      mesh.position.set(p.x + d.length / 2 - L / 2, p.z + d.height / 2 - H / 2, p.y + d.width / 2 - W / 2);
      const outline = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry),
        new THREE.LineBasicMaterial({ color: itemEdge, transparent: true, opacity: 0.7 }),
      );
      mesh.add(outline);
      this.content.add(mesh);
      return mesh;
    });
    this.fit();
    this.setStep(this.meshes.length);
  }

  /** Show only the first ``count`` items (loading sequence); highlight the latest. */
  setStep(count) {
    this.step = count;
    this.meshes.forEach((mesh, index) => {
      mesh.visible = index < count;
    });
    this.highlight(count > 0 && count < this.meshes.length ? count - 1 : -1);
  }

  highlight(index) {
    this.meshes.forEach((mesh, i) => {
      mesh.material.emissive.set(i === index ? 0x3a3a3a : 0x000000);
    });
  }

  /** Frame the whole box tightly, viewed from the front-right, slightly above.
   *
   * A bounding sphere wastes most of the frame for flat boxes, so instead each
   * of the 8 corners is projected onto the camera's right/up axes. The camera is
   * then pulled back just far enough for every corner to fit both frustum angles. */
  fit() {
    if (!this.dims) return;
    const { L, W, H } = this.dims;
    const tanV = Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2);
    const tanH = tanV * this.camera.aspect;
    const direction = new THREE.Vector3(0.95, 0.8, 1.35).normalize(); // target -> camera
    const right = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), direction).normalize();
    const up = new THREE.Vector3().crossVectors(direction, right).normalize();
    const margin = 1.12;
    let distance = 0;
    for (const x of [-L / 2, L / 2]) {
      for (const y of [-H / 2, H / 2]) {
        for (const z of [-W / 2, W / 2]) {
          const corner = new THREE.Vector3(x, y, z);
          const depth = corner.dot(direction); // how far the corner sits towards the camera
          distance = Math.max(
            distance,
            (Math.abs(corner.dot(right)) * margin) / tanH + depth,
            (Math.abs(corner.dot(up)) * margin) / tanV + depth,
          );
        }
      }
    }
    this.camera.position.copy(direction.multiplyScalar(distance));
    this.camera.near = distance / 100;
    this.camera.far = distance * 20;
    this.camera.updateProjectionMatrix();
    this.controls.target.set(0, 0, 0);
    this.controls.update();
  }

  clearContent() {
    for (const child of [...this.content.children]) {
      child.traverse((node) => {
        node.geometry?.dispose();
        node.material?.dispose();
      });
      this.content.remove(child);
    }
    this.meshes = [];
  }

  dispose() {
    if (this.disposed || this.failed) return;
    this.disposed = true;
    this.renderer.setAnimationLoop(null);
    this.resizeObserver.disconnect();
    this.clearContent();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss(); // browsers allow only a handful of live WebGL contexts
  }
}

function axis(origin, vector, color, dash = 0) {
  const geometry = new THREE.BufferGeometry().setFromPoints([origin, origin.clone().add(vector)]);
  const material = dash
    ? new THREE.LineDashedMaterial({ color, dashSize: dash, gapSize: dash * 0.7 })
    : new THREE.LineBasicMaterial({ color });
  const line = new THREE.Line(geometry, material);
  if (dash) line.computeLineDistances(); // required for dashed lines
  return line;
}
