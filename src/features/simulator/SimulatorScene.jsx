import React, { useEffect, useId, useRef, useState } from 'react';
import { Box, Button, Stack, Text, VisuallyHidden } from '@chakra-ui/react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';
import { mergeVertices } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { reactionAtTime, inputEventsAtTime } from './sceneModel';
import { smoothFlySurface } from './flySurface';
import { loadSceneAsset } from './sceneAsset';
import { createLocalWindow } from './sceneWindow';
import useConnectomeData from './useConnectomeData';
import { createConnectomeLayer } from './connectomeLayer';

// A visual mesh is anatomical context; the local solver has its own explicit um frame.
const toScene = (point, center) => new THREE.Vector3(point.x_um / 1000, point.y_um / 1000, point.z_um / 1000).add(center);

export default function SimulatorScene({ opacity, neurons, placement, onPlacement, placing,
  preview, timeMs, selectedContact = 'electrode', onRegion, resetCamera,
  modelGeometry, sceneContext, onAnchor, focusLocal, invalidPlacement, modelVisualization, localWindow = false,
  cameraLink, synchronizeCamera = false, runId, pickingStimulus = false, onStimulusRegion,
  sceneLabel }) {
  const canvasLabel = sceneLabel || (preview?.connectome
    ? 'Трёхмерная сцена мухи и полного коннектома'
    : 'Трёхмерная сцена мухи и локальной модели');
  const host = useRef(null);
  const navigationHelp = useId();
  const state = useRef({});
  const current = useRef({});
  const connectome = useConnectomeData(runId, preview?.connectome);
  current.current = { opacity, neurons, placement, onPlacement, placing, preview, timeMs, selectedContact, onRegion,
    modelGeometry, sceneContext, onAnchor, invalidPlacement, modelVisualization, localWindow,
    connectomeData: connectome.data, pickingStimulus, onStimulusRegion };
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [graphicsAttempt, setGraphicsAttempt] = useState(0);
  const [hover, setHover] = useState(null);
  const assetId = sceneContext?.mesh_asset_id;
  useEffect(() => { if (!placing) setHover(null); }, [placing]);

  useEffect(() => {
    let disposed = false, frame, dirty = true, renderedFrames = 0, lastView = [];
    setLoaded(false); setError('');
    const container = host.current;
    const abort = new AbortController();
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setError('WebGL недоступен. Запись, параметры и экспорт остаются доступны.');
      return undefined;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setClearColor(0x060914);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1;
    renderer.domElement.setAttribute('aria-label', canvasLabel);
    renderer.domElement.setAttribute('aria-describedby', navigationHelp);
    renderer.domElement.setAttribute('tabindex', '0');
    renderer.domElement.dataset.connectomeNodes = '0';
    renderer.domElement.dataset.connectomeEdges = '0';
    renderer.domElement.dataset.connectomeActiveNodes = '0';
    renderer.domElement.dataset.connectomeDeliveredSpikes = '0';
    container.appendChild(renderer.domElement);
    const aperture = createLocalWindow(container);
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xe2e9ff, 0x182033, 1.3));
    const light = new THREE.DirectionalLight(0xffffff, 2.2); light.position.set(2, -3, 7); scene.add(light);
    const rim = new THREE.DirectionalLight(0x779aff, .9); rim.position.set(-3, 3, 3); scene.add(rim);
    const camera = new THREE.PerspectiveCamera(38, 1, 0.005, 100);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.listenToKeyEvents(renderer.domElement);
    controls.enableDamping = !synchronizeCamera; controls.dampingFactor = 0.08;
    const body = new THREE.Group(); scene.add(body);
    const ghosts = new THREE.Group(); scene.add(ghosts);
    const activity = new THREE.Group(); scene.add(activity);
    const inputs = new THREE.Group(); scene.add(inputs);
    const electrodes = new THREE.Group(); scene.add(electrodes);
    const center = new THREE.Vector3(0, 0, 0);
    const cameraOwner = {};
    let cameraReady = false, receivingCamera = false, unlinkCamera;
    const publishCamera = () => {
      dirty = true;
      if (!cameraReady || receivingCamera) return;
      cameraLink?.publish({ position: camera.position.clone().sub(center).toArray(), target: controls.target.clone().sub(center).toArray() }, cameraOwner);
    };
    const receiveCamera = pose => {
      receivingCamera = true;
      camera.position.fromArray(pose.position).add(center);
      controls.target.fromArray(pose.target).add(center);
      controls.update(); receivingCamera = false;
    };
    controls.addEventListener('change', publishCamera);
    const legRigs = new Map();
    const contactMeshes = {};
    ['electrode', 'reference'].forEach((key, i) => {
      const group = new THREE.Group(); group.name = key;
      const color = i ? 0xd9dee8 : 0x4b7bff;
      const contact = new THREE.Mesh(new THREE.SphereGeometry(0.015, 16, 12), new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.25 }));
      contact.userData.originalColor = color;
      group.add(contact);
      const canvas = document.createElement('canvas'); canvas.width = 128; canvas.height = 64;
      const labelContext = canvas.getContext('2d');
      labelContext.font = 'bold 32px sans-serif'; labelContext.fillStyle = i ? '#D9DEE8' : '#91AFFF';
      labelContext.fillText(i ? 'REF' : 'E1', 8, 42);
      const texture = new THREE.CanvasTexture(canvas);
      const label = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthTest: false }));
      label.scale.set(.18, .09, 1); label.position.set(.07, 0, .55); group.add(label);
      const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.003, 0.5, 12), new THREE.MeshStandardMaterial({ color: 0xaebbd0, metalness: 0.6, roughness: 0.3 }));
      shaft.rotation.x = Math.PI / 2; shaft.position.z = 0.26; group.add(shaft);
      electrodes.add(group); contactMeshes[key] = group;
    });
    const transform = new TransformControls(camera, renderer.domElement);
    const transformChanged = () => { dirty = true; };
    transform.addEventListener('change', transformChanged);
    transform.setSize(0.65); scene.add(transform.getHelper());
    transform.addEventListener('dragging-changed', event => { controls.enabled = !event.value; });
    let dragging = false;
    transform.addEventListener('mouseDown', () => { dragging = true; });
    transform.addEventListener('mouseUp', () => {
      dragging = false;
      const active = current.current.selectedContact;
      const position = contactMeshes[active].position.clone().sub(center).multiplyScalar(1000);
      current.current.onPlacement(active, { x_um: position.x, y_um: position.y, z_um: position.z });
    });
    const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
    let press = null, lastHover = 0;
    const pick = event => {
      const box = renderer.domElement.getBoundingClientRect();
      pointer.set((event.clientX - box.left) / box.width * 2 - 1, -(event.clientY - box.top) / box.height * 2 + 1);
      camera.updateMatrixWorld();
      raycaster.setFromCamera(pointer, camera);
      const started = performance.now();
      const hits = raycaster.intersectObjects(body.children, true);
      renderer.domElement.dataset.lastPickMs = (performance.now() - started).toFixed(3);
      return { hit: hits[0], box };
    };
    const registered = hit => hit?.object.name === (current.current.sceneContext?.mesh_part || 'c_thorax');
    const leave = () => setHover(null);
    const move = event => {
      if ((!current.current.placing && !current.current.pickingStimulus) || press || transform.dragging || performance.now() - lastHover < 40) return;
      lastHover = performance.now();
      const { hit, box } = pick(event);
      setHover(hit ? { x: event.clientX - box.left, y: event.clientY - box.top, width: box.width, height: box.height, supported: registered(hit) } : null);
    };
    const down = event => { press = [event.clientX, event.clientY]; setHover(null); };
    const up = event => {
      const origin = press; press = null;
      if ((!current.current.placing && !current.current.pickingStimulus) || !origin || Math.hypot(event.clientX - origin[0], event.clientY - origin[1]) > 4 || transform.dragging) return;
      const { hit } = pick(event);
      if (!hit) return;
      if (current.current.pickingStimulus) {
        const name = hit.object.name, root = hit.object.userData.legName || '';
        let region = name.includes('head') || name.includes('antenna') || name.includes('eye') ? 'head' : name.includes('abdomen') ? 'abdomen' : 'thorax';
        const segment = root.match(/T([123])_(left|right)/);
        if (segment) region = `${{ 1: 'front', 2: 'middle', 3: 'hind' }[segment[1]]}_${segment[2]}`;
        current.current.onStimulusRegion?.(region);
        return;
      }
      if (!registered(hit)) {
        current.current.onRegion('Для этой области ещё нет зарегистрированной модели. Выберите грудную область.');
        return;
      }
      current.current.onRegion('Выбрана локальная грудная область. Контакт задаётся в координатах модели.');
      if (current.current.sceneContext) {
        const face = hit.face, attribute = hit.object.userData.sourceGeometry.attributes.position;
        const vertices = [face.a, face.b, face.c].map(index => new THREE.Vector3().fromBufferAttribute(attribute, index));
        const barycentric = new THREE.Triangle(...vertices).getBarycoord(hit.object.worldToLocal(hit.point.clone()), new THREE.Vector3());
        current.current.onAnchor?.({ mesh_part: hit.object.name, triangle: hit.faceIndex, barycentric: barycentric.toArray() });
      }
      state.current.focusLocal?.();
      // Surface picking selects a region only; no unsupported skin -> physical contact inference.
      transform.attach(contactMeshes[current.current.selectedContact]);
    };
    renderer.domElement.addEventListener('pointerdown', down);
    renderer.domElement.addEventListener('pointerup', up);
    renderer.domElement.addEventListener('pointermove', move);
    renderer.domElement.addEventListener('pointerleave', leave);
    const contextLost = event => {
      event.preventDefault();
      if (!disposed) { setHover(null); setError('Графический контекст потерян. Запись и файлы остаются доступны.'); }
    };
    renderer.domElement.addEventListener('webglcontextlost', contextLost);
    const fit = () => {
      const whole = Boolean(current.current.preview?.connectome);
      const target = center.clone().add(new THREE.Vector3(0, 0, whole ? -.35 : 0));
      camera.position.copy(target).add(whole ? new THREE.Vector3(2.8, -4.05, 2.4) : new THREE.Vector3(3.1, -4.3, 2.5));
      controls.target.copy(target); controls.update();
    };
    const focus = () => { camera.position.copy(center).add(new THREE.Vector3(1.3, -1.5, .9)); controls.target.copy(center); controls.update(); };
    state.current = { fit, focusLocal: focus };
    loadSceneAsset(current.current.sceneContext, abort.signal).then(asset => {
      if (disposed) return;
      asset.parts.forEach(part => {
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(part.positions, 3));
        // Smooth the display normals at genuinely shared STL vertices. The
        // generic crease utility hashes at 0.01 scene units (10 um here),
        // which merges distinct tiny structures. Keep the registered source
        // positions and triangle order intact for picking and provenance.
        if (part.indices) {
          geometry.setIndex(new THREE.BufferAttribute(part.indices, 1));
          geometry.setAttribute('normal', new THREE.Float32BufferAttribute(part.normals, 3));
        } else {
          const welded = mergeVertices(geometry, 1e-7);
          welded.computeVertexNormals();
          const smooth = welded.toNonIndexed();
          geometry.setAttribute('normal', smooth.getAttribute('normal').clone());
          smooth.dispose(); welded.dispose();
        }
        const wing = part.name.includes('wing');
        let displayGeometry = geometry;
        if (!wing && !part.indices) {
          const surface = smoothFlySurface(part.positions);
          displayGeometry = new THREE.BufferGeometry();
          displayGeometry.setAttribute('position', new THREE.Float32BufferAttribute(surface.positions, 3));
          displayGeometry.setIndex(surface.indices); displayGeometry.computeVertexNormals();
        }
        const displayColor = part.name.includes('eye') ? '#a33125' : wing ? '#8b9baf' : part.name.includes('coxa') || part.name.includes('tarsus') || part.name.includes('tibia') ? '#655648' : '#88796b';
        const material = new THREE.MeshStandardMaterial({ color: part.rgba ? new THREE.Color(...part.rgba.slice(0, 3)) : displayColor, roughness: part.rgba ? .55 : part.name.includes('eye') ? .38 : .62, metalness: part.rgba ? .12 : 0, side: wing ? THREE.DoubleSide : THREE.FrontSide });
        aperture.attach(material);
        const mesh = new THREE.Mesh(displayGeometry, material); mesh.name = part.name;
        if (part.name.includes('thorax')) {
          const ghostMaterial = material.clone();
          ghostMaterial.transparent = true; ghostMaterial.opacity = .12; ghostMaterial.depthWrite = false;
          aperture.attach(ghostMaterial, true);
          const ghost = new THREE.Mesh(displayGeometry, ghostMaterial);
          ghost.raycast = () => {};
          ghosts.add(ghost);
        }
        mesh.userData.sourceGeometry = geometry;
        // Surface anchors always refer to the immutable registered STL, even
        // though a smoother derivative is drawn. Triangle numbers stay stable.
        mesh.raycast = function (ray, intersections) {
          const displayed = this.geometry;
          try { this.geometry = this.userData.sourceGeometry; THREE.Mesh.prototype.raycast.call(this, ray, intersections); }
          finally { this.geometry = displayed; }
        };
        body.add(mesh);
        let root = part;
        while (root.parent && !root.name.endsWith('_coxa')) {
          const parentName = root.parent;
          root = asset.parts.find(item => item.name === parentName);
        }
        const legName = part.leg_root || (root.name.endsWith('_coxa') ? root.name : null);
        if (legName) {
          mesh.userData.legName = legName;
          const pivot = part.pivot_mm || root.neutral_position;
          if (!legRigs.has(legName)) legRigs.set(legName, { pivot: new THREE.Vector3(...pivot), matrix: new THREE.Matrix4(), rotation: new THREE.Matrix4(), inversePivot: new THREE.Matrix4().makeTranslation(...pivot.map(value => -value)), side: legName.includes('_left') || legName.startsWith('l') ? 1 : -1 });
          mesh.userData.legRig = legRigs.get(legName); mesh.matrixAutoUpdate = false;
        }
      });
      const thorax = body.children.find(mesh => mesh.name.includes('thorax'));
      if (thorax) { thorax.userData.sourceGeometry.computeBoundingBox(); thorax.userData.sourceGeometry.boundingBox.getCenter(center); }
      const registeredOrigin = current.current.sceneContext?.origin_mm;
      if (registeredOrigin && center.distanceTo(new THREE.Vector3(...registeredOrigin)) > 1e-6) throw new Error('transform_integrity');
      const bounds = new THREE.Box3().setFromObject(body);
      const floor = new THREE.GridHelper(10, 40, 0x25304c, 0x111a2d);
      floor.rotation.x = Math.PI / 2; floor.position.z = bounds.min.z - 0.04;
      floor.material.transparent = true; floor.material.opacity = 0.35; scene.add(floor);
      renderer.domElement.dataset.meshParts = String(body.children.length);
      renderer.domElement.dataset.legRoots = String(legRigs.size);
      renderer.domElement.dataset.surfaceStyle = asset.binary ? 'flybody-source-normals-v1' : 'loop-display-v1';
      dirty = true; cameraReady = true;
      unlinkCamera = cameraLink?.subscribe(cameraOwner, receiveCamera);
      const savedCamera = cameraLink?.snapshot();
      if (savedCamera) receiveCamera(savedCamera); else fit();
      setLoaded(true);
    }).catch(err => { if (err.name !== 'AbortError') setError(err.message.includes('integrity') ? 'Геометрия сцены не соответствует зарегистрированной версии. Обновите страницу.' : 'Не удалось загрузить модель мухи. Повторите загрузку страницы.'); });
    const observer = new ResizeObserver(() => {
      const width = container.clientWidth, height = container.clientHeight;
      renderer.setSize(width, height); camera.aspect = width / Math.max(height, 1); camera.updateProjectionMatrix();
      dirty = true;
    }); observer.observe(container);
    let lastGeometry = null, lastSelected = null, lastPlacing = false;
    let lastConnectome = null, connectomeLayer = null;
    const cellMaterials = [];
    let eventSource = null, segmentEvents = new Map();
    const draw = () => {
      if (disposed) return;
      const view = current.current;
      const signature = [view.timeMs, view.preview, view.modelGeometry, view.placement, view.opacity,
        view.neurons, view.localWindow, view.placing, view.selectedContact, view.invalidPlacement, view.modelVisualization,
        view.connectomeData, view.pickingStimulus];
      const cameraChanged = controls.update();
      if (!dirty && !cameraChanged && !dragging && signature.every((value, index) => value === lastView[index])) {
        frame = requestAnimationFrame(draw); return;
      }
      dirty = false; lastView = signature;
      if (view.connectomeData !== lastConnectome) {
        if (connectomeLayer) { scene.remove(connectomeLayer.group); connectomeLayer.dispose(); }
        lastConnectome = view.connectomeData;
        connectomeLayer = lastConnectome ? createConnectomeLayer(lastConnectome) : null;
        if (connectomeLayer) scene.add(connectomeLayer.group);
        renderer.domElement.dataset.connectomeNodes = String(lastConnectome?.node_ids.length || 0);
        renderer.domElement.dataset.connectomeEdges = String(lastConnectome?.description.edges || 0);
        renderer.domElement.dataset.connectomeDisplayEdges = String(lastConnectome?.edge_pre.length || 0);
        if (!connectomeLayer) {
          renderer.domElement.dataset.connectomeActiveNodes = '0';
          renderer.domElement.dataset.connectomeDeliveredSpikes = '0';
        }
      }
      if (connectomeLayer) {
        const status = connectomeLayer.update(view.timeMs, view.opacity < .5, view.neurons, legRigs);
        renderer.domElement.dataset.connectomeActiveNodes = String(status.active);
        renderer.domElement.dataset.connectomeDeliveredSpikes = String(status.delivered);
      }
      ghosts.visible = Boolean(view.localWindow);
      const reaction = reactionAtTime(view.preview, view.timeMs, view.modelVisualization);
      renderer.domElement.dataset.reactionAngleRad = reaction.toFixed(5);
      renderer.domElement.dataset.modelTimeMs = Number(view.timeMs).toFixed(3);
      renderer.domElement.dataset.poseController = view.preview?.visualization?.reaction?.kind || view.modelVisualization?.reaction?.kind || 'none';
      legRigs.forEach(rig => {
        rig.matrix.makeTranslation(rig.pivot.x, rig.pivot.y, rig.pivot.z)
          .multiply(rig.rotation.makeRotationX(reaction * rig.side))
          .multiply(rig.inversePivot);
      });
      body.children.forEach(mesh => {
        if (mesh.userData.legRig) mesh.matrix.copy(mesh.userData.legRig.matrix);
        const wing = mesh.name.includes('wing');
        const transparent = view.opacity < 1 || wing;
        if (mesh.material.transparent !== transparent) {
          mesh.material.transparent = transparent;
          mesh.material.needsUpdate = true;
        }
        mesh.material.opacity = wing ? Math.min(0.3, view.opacity) : view.opacity;
        // Writing depth prevents unsorted rear STL faces showing through the
        // front surface as a patchwork. Neural lines are overlaid in X-ray mode.
        mesh.material.depthWrite = !wing;
        mesh.material.emissive.setHex(view.placing && mesh.name.includes('thorax') ? 0x183455 : 0x000000);
      });
      const shownGeometry = view.preview?.geometry || view.modelGeometry;
      if (shownGeometry !== lastGeometry) {
        lastGeometry = shownGeometry;
        [...activity.children].forEach(object => { object.geometry?.dispose(); activity.remove(object); });
        cellMaterials.splice(0).forEach(material => material.dispose());
        [...inputs.children].forEach(marker => { marker.geometry.dispose(); marker.material.dispose(); inputs.remove(marker); });
        (lastGeometry?.soma_segment_ids || []).forEach((index, cell) => {
          const first = lastGeometry.starts_um[index], last = lastGeometry.ends_um[index];
          const marker = new THREE.Mesh(new THREE.SphereGeometry(.009, 10, 6), new THREE.MeshBasicMaterial({ color: 0xEAA064, depthTest: false, transparent: true, opacity: .9 }));
          marker.position.set(...first.map((value, axis) => (value + last[axis]) * .0005));
          marker.userData.cell = cell; marker.renderOrder = 3; inputs.add(marker);
        });
        if (lastGeometry) lastGeometry.starts_um.forEach((first, i) => {
          const last = lastGeometry.ends_um[i], cell = lastGeometry.cell_ids[i];
          const start = new THREE.Vector3(...first).multiplyScalar(0.001);
          const end = new THREE.Vector3(...last).multiplyScalar(0.001);
          const geometry = new THREE.BufferGeometry().setFromPoints([start, end]);
          const material = new THREE.LineBasicMaterial({ color: 0x81b9e4, transparent: true, opacity: 0.55 });
          const line = new THREE.Line(geometry, material); line.userData.cell = cell; line.userData.segment = i;
          activity.add(line); cellMaterials.push(material);
        });
      }
      // Preview may arrive before the mesh. Keep the local frame anchored when
      // the asynchronously loaded thorax updates its anatomical centre.
      activity.position.copy(center);
      inputs.position.copy(center); inputs.visible = view.neurons && (!view.connectomeData || view.localWindow);
      const activeInputs = inputEventsAtTime(view.preview, view.timeMs, view.modelVisualization);
      inputs.children.forEach(marker => { marker.visible = Boolean(activeInputs?.some(event => event.cell_id === marker.userData.cell)); });
      renderer.domElement.dataset.activeInputCells = [...new Set((activeInputs || []).map(event => event.cell_id))].join(',');
      activity.visible = view.neurons && (!view.connectomeData || view.localWindow);
      if (view.preview?.compartment_events !== eventSource) {
        eventSource = view.preview?.compartment_events;
        segmentEvents = new Map();
        (eventSource || []).forEach(event => {
          if (!segmentEvents.has(event.segment_id)) segmentEvents.set(event.segment_id, []);
          segmentEvents.get(event.segment_id).push(event.time_ms);
        });
      }
      activity.children.forEach(line => {
        line.renderOrder = view.opacity < .5 ? 2 : 0;
        line.material.depthTest = view.opacity >= .5;
        const times = segmentEvents.get(line.userData.segment);
        const active = times ? times.some(time => view.timeMs >= time && view.timeMs - time < (view.preview?.visualization?.highlight_ms || 5))
          : !eventSource && (view.preview?.spikes || []).some(spike => spike.cell_id === line.userData.cell && view.timeMs >= spike.time_ms && view.timeMs - spike.time_ms < 5);
        line.material.color.setHex(active ? 0x46d5aa : 0x70a8ce);
        line.material.opacity = active ? 1 : 0.55;
      });
      if (!dragging) ['electrode', 'reference'].forEach(key => {
        if (view.placement?.[key] && Object.values(view.placement[key]).every(Number.isFinite)) contactMeshes[key].position.copy(toScene(view.placement[key], center));
      });
      Object.values(contactMeshes).forEach(group => {
        const contact = group.children[0];
        contact.material.color.setHex(view.invalidPlacement ? 0xff5b68 : contact.userData.originalColor);
      });
      if (view.placing !== lastPlacing || view.selectedContact !== lastSelected) {
        if (view.placing) transform.attach(contactMeshes[view.selectedContact]); else transform.detach();
        lastSelected = view.selectedContact; lastPlacing = view.placing;
      }
      camera.updateMatrixWorld();
      aperture.update(renderer, camera, center, view.localWindow && body.children.length > 0);
      const pose = JSON.stringify({
        position: camera.position.clone().sub(center).toArray().map(value => +value.toFixed(6)),
        target: controls.target.clone().sub(center).toArray().map(value => +value.toFixed(6)),
      });
      if (renderer.domElement.dataset.cameraPose !== pose) renderer.domElement.dataset.cameraPose = pose;
      renderer.render(scene, camera);
      renderer.domElement.dataset.renderCount = String(++renderedFrames);
      frame = requestAnimationFrame(draw);
    }; draw();
    return () => {
      disposed = true; abort.abort(); cancelAnimationFrame(frame); observer.disconnect();
      unlinkCamera?.(); controls.removeEventListener('change', publishCamera);
      transform.removeEventListener('change', transformChanged);
      renderer.domElement.removeEventListener('pointerdown', down);
      renderer.domElement.removeEventListener('pointerup', up);
      renderer.domElement.removeEventListener('pointermove', move);
      renderer.domElement.removeEventListener('pointerleave', leave);
      renderer.domElement.removeEventListener('webglcontextlost', contextLost);
      controls.dispose();
      // Three r169's TransformControls.dispose calls this.traverse even though
      // the controller is not an Object3D. Disconnect its public input owner;
      // the registered helper's resources are disposed by scene traversal below.
      transform.disconnect(); transform.detach(); aperture.dispose();
      scene.traverse(object => { object.geometry?.dispose(); if (object.userData.sourceGeometry !== object.geometry) object.userData.sourceGeometry?.dispose(); if (object.material) (Array.isArray(object.material) ? object.material : [object.material]).forEach(m => { m.map?.dispose(); m.dispose(); }); });
      renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); state.current = {};
    };
  }, [assetId, cameraLink, synchronizeCamera, canvasLabel, navigationHelp, graphicsAttempt]);
  useEffect(() => { state.current.fit?.(); }, [resetCamera]);
  useEffect(() => { if (focusLocal) state.current.focusLocal?.(); }, [focusLocal]);
  return <Box ref={host} position="absolute" inset={0} overflow="hidden">
    <VisuallyHidden id={navigationHelp}>Стрелки перемещают камеру; Shift и стрелки вращают её. Приближение цепи и возврат к общему виду доступны кнопками над сценой.</VisuallyHidden>
    {(placing || pickingStimulus) && hover && <Box data-region-preview={pickingStimulus || hover.supported ? 'registered' : 'view-only'} aria-hidden="true" position="absolute" left={`${hover.x}px`} top={`${hover.y}px`} pointerEvents="none">
      <Box w="10px" h="10px" border="2px solid" borderColor={hover.supported ? 'blue.200' : 'gray.400'} borderRadius="full" transform="translate(-50%, -50%)" />
      <Text position="absolute" top={hover.y > hover.height - 70 ? '-54px' : '10px'} left={hover.x > hover.width - 184 ? '-172px' : '12px'} w="160px" px={2} py={1} borderRadius="4px" bg="rgba(6,9,20,.95)" fontSize="11px">{pickingStimulus ? 'Выбрать сенсорный вход этой области' : hover.supported ? 'Грудная область · локальная модель' : 'Область для просмотра; расчёт не зарегистрирован'}</Text>
    </Box>}
    {!loaded && !error && <Text position="absolute" top="50%" w="100%" textAlign="center" role="status">Загрузка модели мухи…</Text>}
    {connectome.loading && <Text position="absolute" top="62px" left={4} role="status" fontSize="12px">Загрузка полной сети и журнала спайков…</Text>}
    {connectome.error && <Stack position="absolute" top="62px" left={4} right={4} align="start" bg="rgba(6,9,20,.96)" p={3}>
      <Text role="alert" fontSize="12px">{connectome.error}</Text><Button size="xs" onClick={connectome.retry}>Повторить загрузку коннектома</Button>
    </Stack>}
    {error && <Stack position="absolute" top="40%" left={6} right={6} p={4} bg="rgba(6,9,20,.96)" align="start">
      <Text role="alert">{error}</Text>
      <Button size="sm" variant="outline" onClick={() => setGraphicsAttempt(value => value + 1)}>Восстановить 3D-сцену</Button>
    </Stack>}
  </Box>;
}
