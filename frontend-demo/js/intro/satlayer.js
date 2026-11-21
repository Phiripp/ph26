// Transparent three.js overlay that draws ONLY the satellite (Nico's model, ./sat3d.js), its imaging
// beam and a soft swath glow where the beam touches the ground. It knows nothing about the map:
// js/intro.js projects the satellite's geographic track with the live MapLibre camera each frame
// and hands this layer plain screen coordinates (CSS px, relative to the canvas).
//
//   const layer = await createSatLayer(canvas);
//   layer.render({ sat: {x, y}, ground: {x, y}, size, swath, beam, alpha, roll });
//   layer.dispose();
//
// three comes from the page importmap (three@0.160.0).
import * as THREE from 'three';
import { buildSatellite } from './sat3d.js';

const CYAN = new THREE.Color('#45d6ee');
const SAT_UNITS = 0.24; // the model spans ~0.24 units from wing tip to dish

/** Small studio environment so the foil and the solar cells catch light (from Nico's engine). */
function envMap(renderer) {
  const c = document.createElement('canvas');
  c.width = 256; c.height = 128;
  const ctx = c.getContext('2d');
  const g = ctx.createLinearGradient(0, 0, 0, 128);
  g.addColorStop(0, '#0a0d12'); g.addColorStop(0.45, '#1a2230'); g.addColorStop(0.62, '#3d6a9c'); g.addColorStop(1, '#8fb9de');
  ctx.fillStyle = g; ctx.fillRect(0, 0, 256, 128);
  const s = ctx.createRadialGradient(60, 38, 0, 60, 38, 22);
  s.addColorStop(0, '#fff'); s.addColorStop(0.3, '#fff3d6'); s.addColorStop(1, 'rgba(255,240,210,0)');
  ctx.fillStyle = s; ctx.fillRect(0, 0, 256, 128);
  const t = new THREE.CanvasTexture(c);
  t.mapping = THREE.EquirectangularReflectionMapping;
  t.colorSpace = THREE.SRGBColorSpace;
  const pm = new THREE.PMREMGenerator(renderer);
  const env = pm.fromEquirectangular(t).texture;
  pm.dispose();
  t.dispose();
  return env;
}

function radialTexture(stops) {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  stops.forEach(([o, col]) => g.addColorStop(o, col));
  ctx.fillStyle = g; ctx.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** Beam: a screen-space trapezoid (lens -> ground swath) with feathered sides and a fade to the ground. */
function makeBeam() {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(12), 3));
  geo.setAttribute('uv', new THREE.BufferAttribute(new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), 2));
  geo.setIndex([0, 2, 1, 1, 2, 3]);
  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
    uniforms: { c: { value: CYAN.clone() }, a: { value: 0 } },
    vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: [
      'uniform vec3 c; uniform float a; varying vec2 vUv;',
      'void main(){',
      '  float side = 1.0 - smoothstep(0.18, 0.5, abs(vUv.x - 0.5));',
      '  float core = 1.0 - smoothstep(0.0, 0.16, abs(vUv.x - 0.5));',
      '  float along = mix(0.95, 0.45, vUv.y) * smoothstep(0.0, 0.08, vUv.y);',
      '  float i = (side * 0.55 + core * 0.45) * along * a;',
      '  gl_FragColor = vec4(mix(c, vec3(1.0), core * 0.35) * i, i);',
      '}',
    ].join('\n'),
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = 1;
  return { mesh, geo, mat };
}

/**
 * @param {HTMLCanvasElement} canvas  full-stage canvas (CSS sizes it; pointer-events none)
 * @returns {{ render: (f: object) => void, dispose: () => void }}
 */
export function createSatLayer(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, premultipliedAlpha: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  scene.environment = envMap(renderer);
  // Orthographic camera in CSS pixels: x right, y up (we pass -y), origin top-left.
  const camera = new THREE.OrthographicCamera(0, 1, 0, -1, -2000, 2000);
  camera.position.z = 1000;

  const sun = new THREE.DirectionalLight('#fff6e8', 3.0);
  sun.position.set(-0.6, 0.8, 1);
  scene.add(sun, new THREE.AmbientLight('#9fb7d6', 0.25));

  // ground glow (swath footprint) — under the beam
  const footTex = radialTexture([[0, 'rgba(220,250,255,1)'], [0.25, 'rgba(120,225,245,.75)'], [0.6, 'rgba(69,214,238,.22)'], [1, 'rgba(69,214,238,0)']]);
  const footMat = new THREE.MeshBasicMaterial({ map: footTex, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false });
  const foot = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), footMat);
  foot.renderOrder = 0;
  scene.add(foot);

  const beam = makeBeam();
  scene.add(beam.mesh);

  // satellite: imager on -Y (points down the screen, toward its ground track), wing on -X
  const sat = new THREE.Group();
  const model = buildSatellite(THREE, 'pbr');
  sat.add(model);
  const glintTex = radialTexture([[0, 'rgba(255,250,235,1)'], [0.15, 'rgba(255,240,210,.55)'], [1, 'rgba(255,230,200,0)']]);
  const glint = new THREE.Sprite(new THREE.SpriteMaterial({ map: glintTex, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false, transparent: true }));
  glint.scale.setScalar(0.05);
  glint.position.set(-0.12, 0.01, 0.01);
  sat.add(glint);
  sat.renderOrder = 2;
  scene.add(sat);
  // all satellite materials fade together
  const satMats = [];
  sat.traverse((o) => { if (o.material) { o.material.transparent = true; satMats.push(o.material); } });

  let W = 0, H = 0;
  const resize = () => {
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    if (w === W && h === H) return;
    W = w; H = h;
    renderer.setSize(w, h, false);
    camera.left = 0; camera.right = w; camera.top = 0; camera.bottom = -h;
    camera.updateProjectionMatrix();
  };

  /**
   * @param {object} f
   * @param {{x:number,y:number}} f.sat     satellite centre (CSS px)
   * @param {{x:number,y:number}} f.ground  ground point under the beam (CSS px)
   * @param {number} f.size    satellite span in px
   * @param {number} f.swath   swath footprint width in px
   * @param {number} f.beam    beam/footprint opacity 0..1
   * @param {number} f.alpha   satellite opacity 0..1
   * @param {number} [f.roll]  small yaw/roll animation (radians)
   */
  function render(f) {
    resize();
    const s = f.size / SAT_UNITS;
    sat.position.set(f.sat.x, -f.sat.y, 0);
    sat.scale.setScalar(s);
    // 3/4 view from above-front: the bus and the wing read as solids, the imager faces the ground track
    const ang = Math.atan2(f.ground.x - f.sat.x, f.sat.y - f.ground.y || 1); // beam direction on screen
    sat.rotation.set(-0.55, 0.5 + (f.roll || 0), -ang, 'XYZ');
    satMats.forEach((m) => { m.opacity = f.alpha; });
    sat.visible = f.alpha > 0.003;

    // beam from just under the lens to the ground
    const lens = new THREE.Vector3(0.004, -0.032, 0.004).applyEuler(sat.rotation).multiplyScalar(s);
    const lx = f.sat.x + lens.x, ly = f.sat.y - lens.y;
    const gx = f.ground.x, gy = f.ground.y;
    const dx = gx - lx, dy = gy - ly;
    const len = Math.hypot(dx, dy) || 1;
    const nx = -dy / len, ny = dx / len; // perpendicular
    const top = Math.max(2, f.size * 0.035), bot = Math.max(top * 2, f.swath * 0.5);
    const p = beam.geo.attributes.position.array;
    p.set([
      lx + nx * top, -(ly + ny * top), 0,
      lx - nx * top, -(ly - ny * top), 0,
      gx + nx * bot, -(gy + ny * bot), 0,
      gx - nx * bot, -(gy - ny * bot), 0,
    ]);
    beam.geo.attributes.position.needsUpdate = true;
    beam.mat.uniforms.a.value = 0.55 * f.beam;
    beam.mesh.visible = f.beam > 0.003;

    foot.position.set(gx, -gy, 0);
    foot.scale.set(f.swath * 1.5, f.swath * 0.7, 1);
    foot.rotation.z = -Math.atan2(dx, dy);
    footMat.opacity = 0.75 * f.beam;
    foot.visible = f.beam > 0.003;

    renderer.render(scene, camera);
  }

  function dispose() {
    scene.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      const m = o.material;
      if (m) {
        [m.map, m.bumpMap].forEach((t) => t && t.dispose());
        m.dispose();
      }
    });
    if (scene.environment) scene.environment.dispose();
    renderer.dispose();
    try { renderer.forceContextLoss(); } catch (_) { /* already lost */ }
  }

  resize();
  return { render, dispose };
}
