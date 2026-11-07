import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Box, Button, HStack, Stack, Text, VisuallyHidden } from '@chakra-ui/react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';
import { mergeVertices } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { reactionAtTime, inputEventsAtTime } from './scene/sceneModel';
import { smoothFlySurface } from './scene/flySurface';
import { loadSceneAsset } from './scene/sceneAsset';
import { createLocalWindow } from './scene/sceneWindow';
import useConnectomeData from './connectome/useConnectomeData';
import useStateContrast from './useStateContrast';
import { createStateContrastLayer } from './stateContrastLayer';
import { createFieldContactLayer } from './field/fieldContacts';
import { snapFieldContactToNeuropil } from './field/fieldNeuropilSnap';
import { createCompartmentEventLayer } from './compartmentEvents';
import { maleCnsNativePosition } from './connectome/connectomeMorphology';
import { createConnectomeLayer } from './connectome/connectomeLayer';
import { connectomeCoverage } from './connectome/connectomeRoutes';
import { sensoryRegionForSurface, partReceivesSensoryInput, unsupportedSurfaceInput } from './scene/stimulusRegions';
import NeuronConnections from './connectome/NeuronConnections';
import { inspectConnectomeNode, selectedNodePosition, selectedNodeVisible } from './connectome/connectomeInspection';
import useSensoryArbors from './connectome/useSensoryArbors';
import useSelectedMorphology from './connectome/useSelectedMorphology';
import useNeighborMorphologies from './connectome/useNeighborMorphologies';
import useSynapsePoints from './connectome/useSynapsePoints';
import useCnsOverview from './connectome/useCnsOverview';
import useNeuropil from './connectome/useNeuropil';
import { neighborIsActive } from './connectome/neighborMorphologyActivity';
import { voltageProbeSegment } from './recording/voltageProbeSegment';
import useMotorReadout from './scene/useMotorReadout';
import useFlyKinematics from './scene/useFlyKinematics';
import { createFlyJointLayer } from './scene/flyJointLayer';
import { motorAngleAtTime, motorMaximumAtTime, MOTOR_REGIONS, MOTOR_VERSION } from './scene/motorReadout';
import { surfaceContactPosition, surfaceContactNormal, surfaceContactLocation, SURFACE_CONTACT_OFFSET_UM } from './scene/surfacePlacement';

// A visual mesh is anatomical context; the local solver has its own explicit um frame.
const toScene = (point, center) => new THREE.Vector3(point.x_um / 1000, point.y_um / 1000, point.z_um / 1000).add(center);

export default function SimulatorScene({ opacity, neurons, placement, onPlacement, placing,
  preview, timeMs, selectedContact = 'electrode', onRegion, resetCamera,
  modelGeometry, sceneContext, onAnchor, focusLocal, invalidPlacement, modelVisualization, localWindow = false,
  cameraLink, synchronizeCamera = false, runId, pickingStimulus = false, onStimulusRegion,
  sceneLabel, fullConnectome = false, onMotorReadout, nativeView = false, fieldRun = null,
  fieldSourceConfiguration = null,
  fieldContactDraft = null, fieldContactNormals = null, fieldSnapRequest = 0, onFieldContactsSnap,
  fieldContactPick = null, onFieldContactPick, onFieldContactSelect, onShowTarget, targetProbe = null, sceneControls, bodyVisible = true, regionsVisible = true }) {
  const canvasLabel = sceneLabel || (fullConnectome || preview?.connectome
    ? 'Трёхмерная сцена мухи и полного коннектома'
    : 'Трёхмерная сцена мухи и локальной модели');
  const host = useRef(null);
  const selectedNodeRef = useRef(null);
  const selectedEdgesRef = useRef(null);
  const selectedMorphologyRef = useRef(null);
  const neighborMorphologyRef = useRef(null);
  const synapsePointsRef = useRef(null);
  const overviewRef = useRef(null);
  const neuropilRef = useRef(null);
  const navigationHelp = useId();
  const state = useRef({});
  const current = useRef({});
  const connectome = useConnectomeData(runId, preview?.connectome, fieldRun);
  // A contact draft is not an electrical result. Never animate the previous
  // sensory experiment as if it were caused by the newly placed electrodes.
  const currentConnectome = useMemo(() => {
    const data = connectome.data;
    if (!data || !fieldContactDraft || fieldRun) return data;
    return { ...data, spike_neurons: new Int32Array(0), spike_times_ms: new Float32Array(0),
      counts: new Int32Array(data.node_ids.length), input_indices: new Int32Array(0),
      description: { ...data.description, spikes: 0, active_neurons: 0, input_neurons: 0 } };
  }, [connectome.data, fieldContactDraft, fieldRun]);
  const fieldSimulation = fieldContactDraft || fieldSourceConfiguration?.simulation || fieldRun?.configuration?.simulation;
  const fieldContactsValid = ['source_um', 'return_um', 'electrode_um', 'reference_um'].every(key =>
    Array.isArray(fieldSimulation?.[key]) && fieldSimulation[key].length === 3
      && fieldSimulation[key].every(Number.isFinite));
  const contrast = useStateContrast(fieldRun, connectome.data);
  const motor = useMotorReadout(currentConnectome);
  const [showJoints, setShowJoints] = useState(false);
  const kinematics = useFlyKinematics(sceneContext?.mesh_asset_id, showJoints);
  useEffect(() => { onMotorReadout?.({ runId, fieldRunId: fieldRun?.id || null, data: motor.data }); }, [onMotorReadout, runId, fieldRun?.id, motor.data]);
  const [showFieldContacts, setShowFieldContacts] = useState(true);
  const showNeuropil = regionsVisible;
  const neuropilRegion = 'all';
  const neuropil = useNeuropil(runId, preview?.connectome?.manifest_sha256, true);
  neuropilRef.current = neuropil.meshes;
  const [insideContacts, setInsideContacts] = useState('');
  const arbors = useSensoryArbors(currentConnectome, !fieldRun && !fieldContactDraft);
  const overview = useCnsOverview(runId, preview?.connectome?.manifest_sha256);
  overviewRef.current = overview.chunks;
  const sceneConnectome = useMemo(() => currentConnectome && arbors.data
    ? { ...currentConnectome, arbors: arbors.data } : currentConnectome, [currentConnectome, arbors.data]);
  const coverage = useMemo(() => currentConnectome ? connectomeCoverage(currentConnectome) : null, [currentConnectome]);
  current.current = { opacity, neurons, placement, onPlacement, placing, preview, timeMs, selectedContact, onRegion, fieldRun, fieldSimulation, fieldContactDraft, fieldContactNormals, fieldSnapRequest, onFieldContactsSnap, fieldContactPick, onFieldContactPick, targetProbe,
    onFieldContactSelect, bodyVisible, modelGeometry, sceneContext, onAnchor, invalidPlacement, modelVisualization, localWindow, focusLocal,
    connectomeData: sceneConnectome, contrastData: contrast.data, fieldContactsValid, showFieldContacts, motorReadout: motor.data, peripheralReadout: null, showPeripheral: false,
    kinematics: kinematics.data, showJoints, showNeuropil, neuropilRegion,
    nativeView: nativeView && Boolean(sceneConnectome), pickingStimulus, onStimulusRegion, fullConnectome };
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [graphicsAttempt, setGraphicsAttempt] = useState(0);
  const [hover, setHover] = useState(null);
  const [nodeHit, setNodeHit] = useState(null);
  const [pinnedNode, setPinnedNode] = useState(null);
  const [selectedEdges, setSelectedEdges] = useState(null);
  const selectedMorphology = useSelectedMorphology(runId, pinnedNode, preview?.connectome?.manifest_sha256);
  const neighborMorphology = useNeighborMorphologies(runId,
    selectedEdges?.nodeId === pinnedNode ? selectedEdges : null, preview?.connectome?.manifest_sha256);
  const synapses = useSynapsePoints(runId,
    selectedEdges?.nodeId === pinnedNode ? selectedEdges : null, preview?.connectome?.manifest_sha256);
  selectedNodeRef.current = pinnedNode;
  selectedEdgesRef.current = selectedEdges?.nodeId === pinnedNode ? selectedEdges : null;
  selectedMorphologyRef.current = selectedMorphology.data;
  neighborMorphologyRef.current = neighborMorphology.data;
  synapsePointsRef.current = synapses.data;
  const pinnedPosition = useMemo(() => selectedNodePosition(connectome.data, pinnedNode, nativeView),
    [connectome.data, pinnedNode, nativeView]);
  const pinnedVisible = useMemo(() => selectedNodeVisible(connectome.data, pinnedNode, nativeView),
    [connectome.data, pinnedNode, nativeView]);
  const hoveredNode = useRef(null);
  const inspected = useMemo(() => connectome.data && nodeHit
    ? inspectConnectomeNode(connectome.data, nodeHit.index, timeMs) : null, [connectome.data, nodeHit, timeMs]);
  const assetId = sceneContext?.mesh_asset_id;
  useEffect(() => { setHover(null); setNodeHit(null); setPinnedNode(null); hoveredNode.current = null; }, [placing, pickingStimulus, fieldContactPick, neurons, runId]);

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
    renderer.domElement.dataset.simulatorScene = 'true';
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
    controls.zoomToCursor = true;
    const body = new THREE.Group(); scene.add(body);
    const ghosts = new THREE.Group(); scene.add(ghosts);
    const activity = new THREE.Group(); scene.add(activity);
    const inputs = new THREE.Group(); scene.add(inputs);
    const electrodes = new THREE.Group(); scene.add(electrodes);
    const selectedMorph = new THREE.LineSegments(new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({ color: 0xffd68a, transparent: true, opacity: .7, depthWrite: false, depthTest: false }));
    selectedMorph.matrixAutoUpdate = false; selectedMorph.frustumCulled = false; selectedMorph.renderOrder = 6; scene.add(selectedMorph);
    const physicalProbe = new THREE.Group();
    physicalProbe.matrixAutoUpdate = false; physicalProbe.renderOrder = 7;
    const probeMarker = new THREE.Mesh(new THREE.SphereGeometry(.008, 12, 8),
      new THREE.MeshBasicMaterial({ color: 0xffef7a, transparent: true, opacity: .6, depthTest: false, depthWrite: false }));
    probeMarker.renderOrder = 10;
    physicalProbe.add(probeMarker); scene.add(physicalProbe);
    const neighborMorph = new THREE.LineSegments(new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: .6, depthTest: false, depthWrite: false }));
    neighborMorph.matrixAutoUpdate = false; neighborMorph.frustumCulled = false; neighborMorph.renderOrder = 5; scene.add(neighborMorph);
    const synapsePoints = new THREE.Points(new THREE.BufferGeometry(),
      new THREE.PointsMaterial({ vertexColors: true, size: 3, sizeAttenuation: false, transparent: true, opacity: .9, depthTest: false, depthWrite: false }));
    synapsePoints.matrixAutoUpdate = false; synapsePoints.frustumCulled = false; synapsePoints.renderOrder = 7; scene.add(synapsePoints);
    const neuropilGroup = new THREE.Group(); neuropilGroup.matrixAutoUpdate = false; scene.add(neuropilGroup);
    let floor = null;
    const nativeAxes = new THREE.AxesHelper(.1); nativeAxes.visible = false; scene.add(nativeAxes);
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
      current.current.onPlacement(active, Object.fromEntries(['x_um', 'y_um', 'z_um'].map((key, axis) => [key, Number(position.getComponent(axis).toFixed(3))])));
    });
    const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
    let press = null, lastHover = 0, fieldHover = null;
    let overlap = [], overlapIndex = 0, overlapPosition = null;
    const setFieldHover = key => {
      if (fieldHover === key) return;
      fieldHover = key; dirty = true;
      renderer.domElement.dataset.hoveredFieldContact = key || '';
      renderer.domElement.style.cursor = key ? 'pointer' : '';
    };
    const fieldContactAt = event => {
      if (!fieldContacts?.group.visible || current.current.nativeView) return null;
      const box = renderer.domElement.getBoundingClientRect();
      pointer.set((event.clientX - box.left) / box.width * 2 - 1, -(event.clientY - box.top) / box.height * 2 + 1);
      camera.updateMatrixWorld(); fieldContacts.group.updateWorldMatrix(true, true); raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(fieldContacts.group.children, true);
      const hit = hits.find(item => item.object.name === 'contact-label') || hits.find(item => item.object.name === 'probe-hit-target');
      const labels = fieldContacts.group.children.map(marker => {
        const label = marker.children.find(object => object.name === 'contact-label');
        if (!label) return null;
        const position = label.getWorldPosition(new THREE.Vector3()).project(camera);
        return { key: marker.userData.contactKey, distance: Math.hypot(
          (position.x + 1) * box.width / 2 - (event.clientX - box.left),
          (1 - position.y) * box.height / 2 - (event.clientY - box.top)) };
      }).filter(Boolean).sort((a, b) => a.distance - b.distance);
      return (labels[0]?.distance <= 12 ? labels[0].key : hit?.object.parent?.userData.contactKey) || null;
    };
    const pick = event => {
      const box = renderer.domElement.getBoundingClientRect();
      pointer.set((event.clientX - box.left) / box.width * 2 - 1, -(event.clientY - box.top) / box.height * 2 + 1);
      camera.updateMatrixWorld();
      raycaster.setFromCamera(pointer, camera);
      const started = performance.now();
      const hits = current.current.fieldContactPick
        ? raycaster.intersectObjects(neuropilGroup.children, true)
        : body.visible ? raycaster.intersectObjects(body.children, true) : [];
      renderer.domElement.dataset.lastPickMs = (performance.now() - started).toFixed(3);
      return { hit: hits[0], box };
    };
    const registered = hit => hit?.object.name === (current.current.sceneContext?.mesh_part || 'c_thorax');
    const sensoryForHit = hit => {
      if (!hit?.face) return null;
      const normal = hit.face.normal.clone().applyNormalMatrix(new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld));
      return sensoryRegionForSurface(hit.object.name, hit.object.userData.legName, normal.z);
    };
    const leave = () => { setFieldHover(null); setHover(null); setNodeHit(null); hoveredNode.current = null; overlap = []; overlapPosition = null; };
    const showOverlap = () => {
      const detail = connectomeLayer?.inspectIndex(overlap[overlapIndex], current.current.timeMs);
      hoveredNode.current = detail?.id || null;
      renderer.domElement.dataset.inspectedNeuron = detail?.id || '';
      renderer.domElement.dataset.inspectionCandidates = String(overlap.length);
      renderer.domElement.dataset.inspectionCandidateIndex = String(overlapIndex);
      setNodeHit(detail && overlapPosition ? { index: detail.index, ...overlapPosition,
        candidateIndex: overlapIndex, candidateCount: overlap.length } : null);
    };
    const move = event => {
      if (!current.current.placing && !current.current.pickingStimulus && !current.current.fieldContactPick) {
        setFieldHover(!press ? fieldContactAt(event) : null);
        if (fieldHover && (!event.altKey || event.shiftKey)) { setNodeHit(null); hoveredNode.current = null; overlap = []; overlapPosition = null; return; }
        if (!event.altKey || press || !current.current.neurons || !connectomeLayer) { setNodeHit(null); hoveredNode.current = null; overlap = []; overlapPosition = null; return; }
        if (performance.now() - lastHover < 80) return;
        lastHover = performance.now();
        const box = renderer.domElement.getBoundingClientRect();
        pointer.set((event.clientX - box.left) / box.width * 2 - 1, -(event.clientY - box.top) / box.height * 2 + 1);
        camera.updateMatrixWorld(); raycaster.setFromCamera(pointer, camera);
        // Match a five CSS-pixel aperture at the CNS viewing depth, independent
        // of device pixel ratio. It is a picking tolerance, never a cell radius.
        raycaster.params.Points.threshold = 10 * camera.position.distanceTo(controls.target)
          * Math.tan(camera.fov * Math.PI / 360) / Math.max(box.height, 1);
        const started = performance.now();
        const priorId = hoveredNode.current;
        const nearPrevious = overlapPosition && Math.hypot(event.clientX - box.left - overlapPosition.x,
          event.clientY - box.top - overlapPosition.y) <= 1;
        overlap = connectomeLayer.inspectCandidates(raycaster); overlapIndex = 0;
        if (nearPrevious && priorId) {
          const previousIndex = overlap.findIndex(index => String(current.current.connectomeData?.node_ids[index]) === priorId);
          if (previousIndex >= 0) overlapIndex = previousIndex;
        }
        overlapPosition = { x: event.clientX - box.left, y: event.clientY - box.top, width: box.width, height: box.height };
        showOverlap();
        renderer.domElement.dataset.lastNeuronPickMs = (performance.now() - started).toFixed(3);
        return;
      }
      if ((!current.current.placing && !current.current.pickingStimulus && !current.current.fieldContactPick) || press || transform.dragging || performance.now() - lastHover < 40) return;
      lastHover = performance.now();
      const { hit, box } = pick(event);
      const sensory = sensoryForHit(hit);
      setHover(hit ? { x: event.clientX - box.left, y: event.clientY - box.top, width: box.width, height: box.height,
        supported: current.current.fieldContactPick ? Boolean(hit.object.userData.region) : current.current.pickingStimulus ? Boolean(sensory && sensory !== 'abdomen') : registered(hit) } : null);
    };
    const down = event => { press = [event.clientX, event.clientY]; setHover(null); };
    const cycleInspection = event => {
      if (!event.altKey || event.shiftKey || !['ArrowUp', 'ArrowDown'].includes(event.key)
          || overlap.length < 2 || !overlapPosition || !connectomeLayer) return;
      event.preventDefault(); event.stopImmediatePropagation();
      overlapIndex = (overlapIndex + (event.key === 'ArrowDown' ? 1 : -1) + overlap.length) % overlap.length;
      showOverlap();
    };
    const releaseInspection = event => { if (event.key === 'Alt' || event.key === 'Escape') { setNodeHit(null); hoveredNode.current = null; overlap = []; overlapPosition = null; } };
    const up = event => {
      const origin = press; press = null;
      if (!current.current.placing && !current.current.pickingStimulus && !current.current.fieldContactPick && event.altKey && event.shiftKey && origin
          && Math.hypot(event.clientX - origin[0], event.clientY - origin[1]) <= 4 && fieldContacts?.group.visible && !current.current.nativeView) {
        const key = fieldContactAt(event);
        if (key) { renderer.domElement.dataset.selectedFieldContact = key; current.current.onFieldContactSelect?.(key); }
        return;
      }
      if (!current.current.placing && !current.current.pickingStimulus && !current.current.fieldContactPick && event.altKey && !event.shiftKey && origin
          && Math.hypot(event.clientX - origin[0], event.clientY - origin[1]) <= 4 && hoveredNode.current) {
        setPinnedNode(hoveredNode.current); return;
      }
      if ((!current.current.placing && !current.current.pickingStimulus && !current.current.fieldContactPick) || !origin || Math.hypot(event.clientX - origin[0], event.clientY - origin[1]) > 4 || transform.dragging) return;
      const { hit } = pick(event);
      if (!hit) return;
      renderer.domElement.dataset.lastPickedPart = hit.object.name;
      renderer.domElement.dataset.lastPickedNormalZ = hit.face
        ? hit.face.normal.clone().applyNormalMatrix(new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld)).z.toFixed(3) : '';
      if (current.current.fieldContactPick) {
        if (!hit.object.userData.region) { current.current.onRegion('Выберите поверхность области ЦНС.'); return; }
        const point = hit.point.clone();
        let normal = null;
        if (hit.face) {
          normal = hit.face.normal.clone().applyNormalMatrix(new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld)).normalize();
        }
        const coordinates = maleCnsNativePosition(point.toArray()).map(value => Number(value.toFixed(3)));
        if (coordinates.every(Number.isFinite)) {
          renderer.domElement.dataset.fieldContactPick = JSON.stringify({ key: current.current.fieldContactPick, coordinates, part: hit.object.userData.region });
          current.current.onFieldContactPick?.(current.current.fieldContactPick, coordinates, normal?.toArray());
        }
        return;
      }
      if (current.current.pickingStimulus) {
        const region = sensoryForHit(hit);
        renderer.domElement.dataset.lastPickedSensoryRegion = region || 'unavailable';
        if (!region) { current.current.onRegion(unsupportedSurfaceInput); return; }
        current.current.onStimulusRegion?.(region);
        return;
      }
      if (!registered(hit)) {
        current.current.onRegion('Для этой области ещё нет зарегистрированной модели. Выберите грудную область.');
        return;
      }
      if (current.current.sceneContext) {
        const face = hit.face, attribute = hit.object.userData.sourceGeometry.attributes.position;
        const vertices = [face.a, face.b, face.c].map(index => new THREE.Vector3().fromBufferAttribute(attribute, index));
        const barycentric = new THREE.Triangle(...vertices).getBarycoord(hit.object.worldToLocal(hit.point.clone()), new THREE.Vector3());
        const normal = face.normal.clone().applyNormalMatrix(new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld));
        let contact;
        try { contact = surfaceContactPosition(hit.point.toArray(), normal.toArray(), center.toArray()); }
        catch {
          current.current.onRegion('Выбранная точка находится вне области локального оператора. Выберите точку ближе к центру груди или задайте координаты.');
          return;
        }
        current.current.onPlacement(current.current.selectedContact, contact);
        current.current.onAnchor?.({ mesh_part: hit.object.name, triangle: hit.faceIndex,
          barycentric: barycentric.toArray(), contact: current.current.selectedContact });
        renderer.domElement.dataset.surfaceContact = JSON.stringify({ contact: current.current.selectedContact,
          triangle: hit.faceIndex, position_um: contact, offset_um: SURFACE_CONTACT_OFFSET_UM,
          surface_mm: hit.point.toArray(), normal: normal.toArray() });
        current.current.onRegion(`${current.current.selectedContact === 'reference' ? 'REF' : 'E1'} установлен снаружи поверхности: центр контакта на ${SURFACE_CONTACT_OFFSET_UM} мкм от неё. Это записывающий контакт; сенсорный вход не изменён.`);
      }
      transform.attach(contactMeshes[current.current.selectedContact]);
    };
    renderer.domElement.addEventListener('pointerdown', down);
    renderer.domElement.addEventListener('pointerup', up);
    renderer.domElement.addEventListener('pointermove', move);
    renderer.domElement.addEventListener('pointerleave', leave);
    window.addEventListener('keydown', cycleInspection, true);
    window.addEventListener('keyup', releaseInspection);
    window.addEventListener('blur', leave);
    const contextLost = event => {
      event.preventDefault();
      if (!disposed) { setHover(null); setError('Графический контекст потерян. Запись и файлы остаются доступны.'); }
    };
    renderer.domElement.addEventListener('webglcontextlost', contextLost);
    const fit = () => {
      if (current.current.nativeView && connectomeLayer && !connectomeLayer.nativeBounds.isEmpty()) {
        const bounds = connectomeLayer.nativeBounds, target = bounds.getCenter(new THREE.Vector3());
        const radius = bounds.getSize(new THREE.Vector3()).length() * .5;
        camera.position.copy(target).add(new THREE.Vector3(1, -1, .6).normalize().multiplyScalar(radius / Math.sin(camera.fov * Math.PI / 360) * 1.15));
        controls.target.copy(target); controls.update(); return;
      }
      const whole = Boolean(current.current.preview?.connectome);
      const target = center.clone().add(new THREE.Vector3(0, 0, whole ? -.35 : 0));
      camera.position.copy(target).add(whole ? new THREE.Vector3(2.8, -4.05, 2.4) : new THREE.Vector3(3.1, -4.3, 2.5));
      controls.target.copy(target); controls.update();
    };
    const focus = () => { if (fieldContacts) { focusFieldContacts(); return; } camera.position.copy(center).add(new THREE.Vector3(1.3, -1.5, .9)); controls.target.copy(center); controls.update(); };
    const orient = direction => {
      const distance = camera.position.distanceTo(controls.target);
      camera.position.copy(controls.target).add(new THREE.Vector3(...direction).normalize().multiplyScalar(distance));
      controls.update();
    };
    const focusNode = id => {
      const target = connectomeLayer?.nodeWorldPosition(id);
      if (!target) return;
      const direction = camera.position.clone().sub(controls.target).normalize();
      if (direction.lengthSq() === 0) direction.set(1, -1, .6).normalize();
      camera.position.copy(target).addScaledVector(direction, .6);
      controls.target.copy(target); controls.update(); dirty = true;
    };
    const focusProbe = previewData => {
      const probe = voltageProbeSegment(selectedMorphologyRef.current, previewData,
        selectedNodeRef.current, current.current.timeMs);
      if (!probe || !connectomeLayer) return;
      connectomeLayer.group.updateWorldMatrix(true, false);
      const target = new THREE.Vector3(...probe.positions.slice(0, 3))
        .add(new THREE.Vector3(...probe.positions.slice(3))).multiplyScalar(.5)
        .applyMatrix4(connectomeLayer.group.matrixWorld);
      const direction = camera.position.clone().sub(controls.target).normalize();
      if (direction.lengthSq() === 0) direction.set(1, -1, .6).normalize();
      camera.position.copy(target).addScaledVector(direction, .15);
      controls.target.copy(target); controls.update(); dirty = true;
    };
    const focusNeuropil = id => {
      const mesh = neuropilGroup.children.find(child => child.userData.region === id);
      if (!mesh) return;
      mesh.updateWorldMatrix(true, false);
      const bounds = new THREE.Box3().setFromObject(mesh);
      if (bounds.isEmpty()) return;
      const target = bounds.getCenter(new THREE.Vector3());
      const direction = camera.position.clone().sub(controls.target).normalize();
      if (direction.lengthSq() === 0) direction.set(1, -1, .6).normalize();
      const distance = Math.max(.3, bounds.getSize(new THREE.Vector3()).length() * 1.8);
      camera.position.copy(target).addScaledVector(direction, distance);
      controls.target.copy(target); controls.update(); dirty = true;
    };
    const focusFieldContacts = () => {
      if (!fieldContacts) return;
      fieldContacts.group.updateWorldMatrix(true, true);
      const bounds = new THREE.Box3().setFromObject(fieldContacts.group);
      if (bounds.isEmpty()) return;
      const target = bounds.getCenter(new THREE.Vector3());
      const direction = camera.position.clone().sub(controls.target).normalize();
      if (direction.lengthSq() === 0) direction.set(1, -1, .6).normalize();
      const radius = Math.max(.08, bounds.getSize(new THREE.Vector3()).length() * .55);
      const vertical = THREE.MathUtils.degToRad(camera.fov);
      const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * camera.aspect);
      camera.position.copy(target).addScaledVector(direction, radius / Math.sin(Math.min(vertical, horizontal) / 2));
      controls.target.copy(target); controls.update(); dirty = true;
    };
    state.current = { fit, focusLocal: focus, focusNode, focusProbe, focusNeuropil, focusFieldContacts, orient };
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
      floor = new THREE.GridHelper(10, 40, 0x25304c, 0x111a2d);
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
    let lastGeometry = null, lastSelected = null, lastPlacing = false, lastContactPlacement = null;
    let lastConnectome = null, connectomeLayer = null, lastSelectedMorphology = null, lastNeighborMorphology = null, lastSynapsePoints = null;
    let lastContrast = null, contrastGraph = null, contrastLayer = null;
    let lastFieldSimulation = null, lastFieldNormals = null, lastFieldSnap = 0, fieldContacts = null;
    let lastCompartmentPreview = null, compartmentLayer = null;
    let drawnNeuropil = [];
    let neighborActivity = [];
    let synapseActivity = new Map();
    let lastNativeView = false, lastFocusLocal = current.current.focusLocal;
    let lastKinematics = null, jointLayer = null;
    const cellMaterials = [];
    let eventSource = null, segmentEvents = new Map();
    const draw = () => {
      if (disposed) return;
      const view = current.current;
      const signature = [view.timeMs, view.preview, view.modelGeometry, view.placement, view.opacity,
        view.neurons, view.bodyVisible, view.localWindow, view.placing, view.selectedContact, view.invalidPlacement, view.modelVisualization,
        view.connectomeData, view.contrastData, view.showFieldContacts, view.motorReadout, view.peripheralReadout, view.showPeripheral, view.kinematics, view.showJoints,
        view.nativeView, view.focusLocal, view.pickingStimulus, view.fullConnectome, view.showNeuropil, view.neuropilRegion, view.fieldRun, view.fieldSimulation, view.fieldContactNormals, view.fieldSnapRequest, view.fieldContactPick, view.targetProbe, selectedNodeRef.current, selectedEdgesRef.current, selectedMorphologyRef.current, neighborMorphologyRef.current, synapsePointsRef.current, overviewRef.current, neuropilRef.current];
      const cameraChanged = controls.update();
      if (!dirty && !cameraChanged && !dragging && signature.every((value, index) => value === lastView[index])) {
        frame = requestAnimationFrame(draw); return;
      }
      dirty = false; lastView = signature;
      if (view.kinematics !== lastKinematics) {
        if (jointLayer) { scene.remove(jointLayer.group); jointLayer.dispose(); }
        lastKinematics = view.kinematics;
        jointLayer = lastKinematics ? createFlyJointLayer(lastKinematics) : null;
        if (jointLayer) scene.add(jointLayer.group);
      }
      if (view.connectomeData !== lastConnectome) {
        if (connectomeLayer) { scene.remove(connectomeLayer.group); connectomeLayer.dispose(); }
        lastConnectome = view.connectomeData;
        connectomeLayer = lastConnectome ? createConnectomeLayer(lastConnectome) : null;
        if (connectomeLayer) scene.add(connectomeLayer.group);
        renderer.domElement.dataset.connectomeNodes = String(lastConnectome?.node_ids.length || 0);
        renderer.domElement.dataset.connectomeEdges = String(lastConnectome?.description.edges || 0);
        renderer.domElement.dataset.connectomeDisplayEdges = String(lastConnectome?.edge_pre.length || 0);
        renderer.domElement.dataset.connectomeRouting = connectomeLayer?.group.userData.routing.version || 'none';
        renderer.domElement.dataset.connectomeRouteSamples = String(connectomeLayer?.group.userData.routing.samples || 0);
        renderer.domElement.dataset.connectomeVisibleNodes = String(connectomeLayer?.group.userData.routing.visibleNodes || 0);
        renderer.domElement.dataset.connectomeVisibleEdges = String(connectomeLayer?.group.userData.routing.visibleEdges || 0);
        renderer.domElement.dataset.connectomeMorphologyNodes = String(lastConnectome?.morphology?.count || 0);
        renderer.domElement.dataset.connectomeArborCells = String(lastConnectome?.arbors?.cells || 0);
        renderer.domElement.dataset.connectomeArborVertices = String(lastConnectome?.arbors?.vertices || 0);
        renderer.domElement.dataset.connectomeRoutingMs = (connectomeLayer?.group.userData.routing.buildMilliseconds || 0).toFixed(1);
        if (!connectomeLayer) {
          renderer.domElement.dataset.connectomeActiveNodes = '0';
          renderer.domElement.dataset.connectomeDeliveredSpikes = '0';
        }
      }
      if (connectomeLayer) connectomeLayer.coordinateView(view.nativeView);
      const shownFieldSimulation = (view.fieldRun || view.fieldContactDraft) && view.connectomeData && view.fieldContactsValid ? view.fieldSimulation : null;
      if (shownFieldSimulation !== lastFieldSimulation || view.fieldContactNormals !== lastFieldNormals) {
        if (fieldContacts) { scene.remove(fieldContacts.group); fieldContacts.dispose(); }
        lastFieldSimulation = shownFieldSimulation;
        lastFieldNormals = view.fieldContactNormals;
        fieldContacts = shownFieldSimulation ? createFieldContactLayer(shownFieldSimulation, view.fieldContactNormals || {}) : null;
        if (fieldContacts) scene.add(fieldContacts.group);
      }
      if (fieldContacts) { fieldContacts.coordinateView(view.nativeView); fieldContacts.group.visible = view.showFieldContacts; fieldContacts.setHighlight(fieldHover, view.fieldContactPick); }
      renderer.domElement.dataset.highlightedFieldContact = view.fieldContactPick || fieldHover || '';
      renderer.domElement.dataset.fieldContactsVisible = String(Boolean(fieldContacts && fieldContacts.group.visible));
      if (fieldContacts?.group.visible) {
        fieldContacts.group.updateWorldMatrix(true, true);
        renderer.domElement.dataset.fieldContactPixels = JSON.stringify(Object.fromEntries(fieldContacts.group.children.map(marker => {
          const target = marker.children.find(object => object.name === 'contact-label') || marker.children.find(object => object.name === 'probe-hit-target');
          const projected = target.getWorldPosition(new THREE.Vector3()).project(camera);
          return [marker.userData.contactKey, [(projected.x + 1) * container.clientWidth / 2, (1 - projected.y) * container.clientHeight / 2]];
        })));
      } else renderer.domElement.dataset.fieldContactPixels = '';
      let visibleLabels = 0;
      fieldContacts?.group.traverse(object => { if (object.name === 'contact-label' && object.visible && fieldContacts.group.visible) visibleLabels += 1; });
      renderer.domElement.dataset.fieldVisibleLabels = String(visibleLabels);
      renderer.domElement.dataset.fieldContactCount = String(fieldContacts?.group.children.length || 0);
      const compartmentPreview = view.connectomeData ? view.fieldRun?.result?.preview?.compartment_events || null : null;
      if (compartmentPreview !== lastCompartmentPreview) {
        if (compartmentLayer) { scene.remove(compartmentLayer.points); compartmentLayer.dispose(); }
        lastCompartmentPreview = compartmentPreview;
        compartmentLayer = compartmentPreview ? createCompartmentEventLayer(compartmentPreview) : null;
        if (compartmentLayer) scene.add(compartmentLayer.points);
      }
      if (compartmentLayer) {
        compartmentLayer.coordinateView(view.nativeView);
        compartmentLayer.points.visible = view.neurons;
        compartmentLayer.points.material.depthTest = !view.nativeView && view.bodyVisible && view.opacity >= 1;
        renderer.domElement.dataset.compartmentEventCount = String(compartmentLayer.update(view.timeMs));
      } else renderer.domElement.dataset.compartmentEventCount = '0';
      if (view.contrastData !== lastContrast || view.connectomeData !== contrastGraph) {
        if (contrastLayer) { scene.remove(contrastLayer.points); contrastLayer.dispose(); }
        lastContrast = view.contrastData; contrastGraph = view.connectomeData;
        contrastLayer = lastContrast && contrastGraph ? createStateContrastLayer(contrastGraph, lastContrast) : null;
        if (contrastLayer) scene.add(contrastLayer.points);
      }
      if (contrastLayer) {
        contrastLayer.coordinateView(view.nativeView);
        contrastLayer.points.visible = view.neurons;
        contrastLayer.points.material.depthTest = !view.nativeView && view.bodyVisible && view.opacity >= 1;
        const status = contrastLayer.update(view.timeMs);
        renderer.domElement.dataset.contrastSample = String(status.sample);
        renderer.domElement.dataset.contrastActive = String(status.active);
        renderer.domElement.dataset.contrastVisibleCells = String(contrastLayer.visibleCells);
        renderer.domElement.dataset.contrastVisible = String(contrastLayer.points.visible);
      } else {
        renderer.domElement.dataset.contrastSample = '';
        renderer.domElement.dataset.contrastActive = '';
        renderer.domElement.dataset.contrastVisibleCells = '0';
        renderer.domElement.dataset.contrastVisible = 'false';
      }
      if (connectomeLayer) connectomeLayer.setOverview(overviewRef.current || []);
      const meshes = neuropilRef.current || [];
      if (meshes.length < drawnNeuropil.length || drawnNeuropil.some((mesh, index) => mesh !== meshes[index])) {
        while (neuropilGroup.children.length) {
          const child = neuropilGroup.children[0]; neuropilGroup.remove(child); child.geometry.dispose(); child.material.dispose();
        }
        drawnNeuropil = [];
      }
      for (const item of meshes.slice(drawnNeuropil.length)) {
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(item.positions, 3));
        geometry.setIndex(new THREE.BufferAttribute(item.indices, 1));
        const material = new THREE.MeshBasicMaterial({ color: item.dataset === 'fullbrain-roi-v4' ? 0x4889db : 0x40bca9,
          transparent: true, opacity: .012, side: THREE.DoubleSide, depthWrite: false, depthTest: false });
        const mesh = new THREE.Mesh(geometry, material); mesh.renderOrder = 2;
        mesh.userData.region = `${item.dataset}:${item.id}`; neuropilGroup.add(mesh);
      }
      drawnNeuropil = meshes;
      neuropilGroup.visible = Boolean(connectomeLayer && view.showNeuropil);
      neuropilGroup.children.forEach(mesh => {
        mesh.visible = true;
        mesh.material.opacity = .012;
        mesh.material.depthTest = !view.nativeView && view.bodyVisible && view.opacity >= 1;
      });
      if (connectomeLayer) { neuropilGroup.matrix.copy(connectomeLayer.group.matrix); neuropilGroup.matrixWorldNeedsUpdate = true; }
      if (view.fieldSnapRequest && view.fieldSnapRequest !== lastFieldSnap && shownFieldSimulation && neuropilGroup.children.length === 114 && !view.nativeView) {
        lastFieldSnap = view.fieldSnapRequest;
        try {
          const snapped = Object.fromEntries(['source_um', 'return_um', 'electrode_um', 'reference_um'].map(key =>
            [key, snapFieldContactToNeuropil(shownFieldSimulation[key], neuropilGroup)]));
          renderer.domElement.dataset.fieldContactSnap = String(Object.keys(snapped).length);
          view.onFieldContactsSnap?.(snapped);
        } catch { view.onRegion('Не удалось привязать контакты к областям ЦНС.'); }
      }
      renderer.domElement.dataset.neuropilLoaded = String(neuropilGroup.children.length);
      renderer.domElement.dataset.neuropilRegions = String(neuropilGroup.visible
        ? neuropilGroup.children.filter(mesh => mesh.visible).length : 0);
      const shownOverview = connectomeLayer && view.neurons ? (overviewRef.current || []) : [];
      renderer.domElement.dataset.overviewCells = String(shownOverview.reduce((sum, chunk) => sum + chunk.cells, 0));
      renderer.domElement.dataset.overviewSegments = String(shownOverview.reduce((sum, chunk) => sum + chunk.segments, 0));
      if (view.nativeView !== lastNativeView) {
        lastNativeView = view.nativeView; setNodeHit(null);
        if (!view.nativeView && view.focusLocal !== lastFocusLocal) focus(); else fit();
      }
      lastFocusLocal = view.focusLocal;
      body.visible = !view.nativeView && view.bodyVisible; electrodes.visible = !view.nativeView && !view.fullConnectome && !view.fieldRun && !view.fieldContactDraft;
      if (floor) floor.visible = !view.nativeView;
      nativeAxes.visible = view.nativeView && Boolean(connectomeLayer);
      if (nativeAxes.visible) nativeAxes.position.copy(connectomeLayer.nativeBounds.min).addScalar(-.04);
      renderer.domElement.dataset.coordinateView = view.nativeView ? 'native-em-mm' : 'body-view-only';
      renderer.domElement.dataset.eventSource = view.fieldRun ? 'field-graph' : view.fieldContactDraft ? 'pending' : 'primary-run';
      renderer.domElement.dataset.fieldRunId = view.fieldRun?.id || '';
      renderer.domElement.dataset.bodyVisible = String(body.visible);
      renderer.domElement.dataset.bodyOpacity = String(view.opacity);
      renderer.domElement.dataset.recordingContactsVisible = String(electrodes.visible);
      renderer.domElement.dataset.schematicConnectionsVisible = String(!view.nativeView);
      let inputActive = 0;
      if (connectomeLayer) {
        renderer.domElement.dataset.selectedNeuronIndex = String(connectomeLayer.selectNode(selectedNodeRef.current));
        renderer.domElement.dataset.selectedNeuronId = selectedNodeRef.current || '';
        const status = connectomeLayer.update(view.timeMs, view.nativeView || view.opacity < .5, view.neurons, legRigs,
          { visible: view.showPeripheral, readout: view.peripheralReadout, width: container.clientWidth, height: container.clientHeight,
            cameraDistance: camera.position.distanceTo(controls.target) });
        inputActive = status.inputActive;
        renderer.domElement.dataset.connectomeActiveNodes = String(status.active);
        renderer.domElement.dataset.connectomePointScale = String(status.pointScale);
        renderer.domElement.dataset.connectomeActiveInputs = String(inputActive);
        renderer.domElement.dataset.connectomeDeliveredSpikes = String(status.delivered);
        renderer.domElement.dataset.connectomeSourceCrossings = String(status.sourceDelivered);
        renderer.domElement.dataset.peripheralVisible = String(status.peripheralVisible);
        renderer.domElement.dataset.peripheralPaths = String(status.peripheralPaths);
        renderer.domElement.dataset.peripheralReadoutCells = String(view.peripheralReadout?.cells || 0);
        renderer.domElement.dataset.peripheralActivity = JSON.stringify(status.peripheralActivity);
      }
      const wholeCns = Boolean(view.fullConnectome || view.preview?.connectome);
      // Highlight the population actually used by this saved calculation, not
      // an unapplied draft and never the position of a passive recording contact.
      const sensoryRegion = view.fieldRun || view.fieldContactDraft ? null : view.preview?.connectome?.stimulus_region;
      const stimulusOn = inputActive > 0;
      renderer.domElement.dataset.sensoryRegion = sensoryRegion || 'none';
      renderer.domElement.dataset.notumHighlight = String(sensoryRegion === 'notum' && stimulusOn && !view.nativeView);
      ghosts.visible = !wholeCns && Boolean(view.localWindow);
      const reaction = wholeCns ? motorMaximumAtTime(view.motorReadout, view.timeMs) : reactionAtTime(view.preview, view.timeMs, view.modelVisualization);
      renderer.domElement.dataset.reactionAngleRad = reaction.toFixed(5);
      renderer.domElement.dataset.modelTimeMs = Number(view.timeMs).toFixed(3);
      renderer.domElement.dataset.poseController = wholeCns ? (view.motorReadout ? MOTOR_VERSION : 'unavailable') : view.preview?.visualization?.reaction?.kind || view.modelVisualization?.reaction?.kind || 'none';
      renderer.domElement.dataset.motorActiveNeurons = String(view.motorReadout?.active || 0);
      renderer.domElement.dataset.firstMotorEventMs = Number.isFinite(view.motorReadout?.first) ? String(view.motorReadout.first) : '';
      const legAngles = {};
      legRigs.forEach((rig, name) => {
        const index = ['T1_left', 'T1_right', 'T2_left', 'T2_right', 'T3_left', 'T3_right'].indexOf(name.replace('coxa_', ''));
        const angle = wholeCns ? motorAngleAtTime(view.motorReadout, MOTOR_REGIONS[index], view.timeMs) : reaction;
        legAngles[name] = Number(angle.toFixed(6));
        rig.matrix.makeTranslation(rig.pivot.x, rig.pivot.y, rig.pivot.z)
          .multiply(rig.rotation.makeRotationX(angle * rig.side))
          .multiply(rig.inversePivot);
      });
      renderer.domElement.dataset.legReactionsRad = JSON.stringify(legAngles);
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
        mesh.material.emissive.setHex(view.placing && mesh.name.includes('thorax') ? 0x183455
          : !view.nativeView && stimulusOn && partReceivesSensoryInput(mesh.name, mesh.userData.legName, sensoryRegion) ? 0x542307 : 0x000000);
      });
      const occludeNeuralLayers = !view.nativeView && view.bodyVisible && view.opacity >= 1;
      selectedMorph.material.depthTest = occludeNeuralLayers;
      neighborMorph.material.depthTest = occludeNeuralLayers;
      synapsePoints.material.depthTest = occludeNeuralLayers;
      probeMarker.material.depthTest = occludeNeuralLayers;
      renderer.domElement.dataset.neuralBodyOcclusion = String(occludeNeuralLayers);
      renderer.domElement.dataset.selectedConnectionLines = '0';
      if (synapsePointsRef.current !== lastSynapsePoints) {
        lastSynapsePoints = synapsePointsRef.current;
        synapseActivity = new Map();
        synapsePoints.geometry.dispose(); synapsePoints.geometry = new THREE.BufferGeometry();
        if (lastSynapsePoints) {
          synapsePoints.geometry.setAttribute('position', new THREE.BufferAttribute(lastSynapsePoints.positions, 3));
          synapsePoints.geometry.setAttribute('color', new THREE.BufferAttribute(new Float32Array(lastSynapsePoints.positions.length), 3).setUsage(THREE.DynamicDrawUsage));
        }
      }
      synapsePoints.visible = Boolean(lastSynapsePoints && connectomeLayer && view.neurons);
      if (synapsePoints.visible) {
        synapsePoints.matrix.copy(connectomeLayer.group.matrix); synapsePoints.matrixWorldNeedsUpdate = true;
        const colors = synapsePoints.geometry.attributes.color;
        let active = 0, changed = false;
        lastSynapsePoints.presynaptic.forEach((indices, id) => {
          const firing = neighborIsActive(view.timeMs, connectomeLayer.lastSpikeTime(id));
          if (firing) active += indices.length;
          if (synapseActivity.get(id) === firing) return;
          synapseActivity.set(id, firing); changed = true;
          indices.forEach(index => colors.setXYZ(index, firing ? .25 : 1, firing ? 1 : .76, firing ? .72 : .35));
        });
        if (changed) colors.needsUpdate = true;
        renderer.domElement.dataset.activeSynapsePoints = String(active);
      } else {
        renderer.domElement.dataset.activeSynapsePoints = '0';
      }
      renderer.domElement.dataset.synapsePoints = String(synapsePoints.visible ? lastSynapsePoints.returned : 0);
      if (selectedMorphologyRef.current !== lastSelectedMorphology) {
        lastSelectedMorphology = selectedMorphologyRef.current;
        selectedMorph.geometry.dispose(); selectedMorph.geometry = new THREE.BufferGeometry();
        if (lastSelectedMorphology) selectedMorph.geometry.setAttribute('position', new THREE.BufferAttribute(lastSelectedMorphology.positions, 3));
      }
      selectedMorph.visible = Boolean(lastSelectedMorphology && connectomeLayer && view.neurons);
      if (selectedMorph.visible) {
        selectedMorph.matrix.copy(connectomeLayer.group.matrix); selectedMorph.matrixWorldNeedsUpdate = true;
        const spike = connectomeLayer.lastSpikeTime(selectedNodeRef.current);
        selectedMorph.material.opacity = spike !== null && view.timeMs - spike < 6 ? .95 : .55;
      }
      renderer.domElement.dataset.selectedMorphologyVertices = String(lastSelectedMorphology?.vertices || 0);
      renderer.domElement.dataset.selectedMorphologyVisible = String(selectedMorph.visible);
      const probe = selectedMorph.visible
        ? voltageProbeSegment(lastSelectedMorphology, view.targetProbe, selectedNodeRef.current, view.timeMs) : null;
      physicalProbe.visible = Boolean(probe);
      if (probe) {
        physicalProbe.matrix.copy(connectomeLayer.group.matrix); physicalProbe.matrixWorldNeedsUpdate = true;
        probeMarker.position.set(...probe.positions.slice(0, 3)).add(new THREE.Vector3(...probe.positions.slice(3)).sub(new THREE.Vector3(...probe.positions.slice(0, 3))).multiplyScalar(.5));
        probeMarker.material.opacity = .6 + .4 * Math.min(Math.abs(probe.deltaMv) / 20, 1);
      }
      renderer.domElement.dataset.physicalProbeVisible = String(physicalProbe.visible);
      renderer.domElement.dataset.physicalProbeDeltaMv = probe ? probe.deltaMv.toFixed(6) : '';
      renderer.domElement.dataset.physicalProbeSampleMs = probe ? probe.sampleTimeMs.toFixed(6) : '';
      if (neighborMorphologyRef.current !== lastNeighborMorphology) {
        lastNeighborMorphology = neighborMorphologyRef.current;
        neighborActivity = [];
        neighborMorph.geometry.dispose(); neighborMorph.geometry = new THREE.BufferGeometry();
        if (lastNeighborMorphology) {
          neighborMorph.geometry.setAttribute('position', new THREE.BufferAttribute(lastNeighborMorphology.positions, 3));
          neighborMorph.geometry.setAttribute('color', new THREE.BufferAttribute(new Float32Array(lastNeighborMorphology.positions.length), 3).setUsage(THREE.DynamicDrawUsage));
        }
      }
      neighborMorph.visible = Boolean(lastNeighborMorphology && connectomeLayer && view.neurons);
      if (neighborMorph.visible) {
        neighborMorph.matrix.copy(connectomeLayer.group.matrix); neighborMorph.matrixWorldNeedsUpdate = true;
        const color = neighborMorph.geometry.attributes.color;
        let active = 0, changed = false;
        lastNeighborMorphology.ranges.forEach((range, index) => {
          const isActive = neighborIsActive(view.timeMs, connectomeLayer.lastSpikeTime(range.id));
          if (isActive) active += 1;
          if (neighborActivity[index] === isActive) return;
          neighborActivity[index] = isActive; changed = true;
          for (let i = range.start; i < range.start + range.count; i += 1) {
            color.setXYZ(i, isActive ? .12 : .25, isActive ? 1 : .61, isActive ? .7 : .9);
          }
        });
        if (changed) color.needsUpdate = true;
        renderer.domElement.dataset.neighborMorphologyActive = String(active);
      } else {
        renderer.domElement.dataset.neighborMorphologyActive = '0';
      }
      renderer.domElement.dataset.neighborMorphologyVertices = String(lastNeighborMorphology?.vertices || 0);
      if (jointLayer) {
        jointLayer.group.visible = view.showJoints && !view.nativeView;
        if (jointLayer.group.visible) jointLayer.update(legRigs, view.opacity < .5);
      }
      renderer.domElement.dataset.sourceRigVisible = String(Boolean(jointLayer?.group.visible));
      renderer.domElement.dataset.sourceRigJoints = String(lastKinematics?.joints.size || 0);
      renderer.domElement.dataset.sourceRigBodies = String(lastKinematics?.bodies.length || 0);
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
      inputs.position.copy(center); inputs.visible = view.neurons && !wholeCns;
      const activeInputs = inputEventsAtTime(view.preview, view.timeMs, view.modelVisualization);
      inputs.children.forEach(marker => { marker.visible = Boolean(activeInputs?.some(event => event.cell_id === marker.userData.cell)); });
      renderer.domElement.dataset.activeInputCells = [...new Set((activeInputs || []).map(event => event.cell_id))].join(',');
      activity.visible = view.neurons && !wholeCns;
      renderer.domElement.dataset.localModelVisible = String(activity.visible);
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
      renderer.domElement.dataset.recordingContactCoordinates = JSON.stringify({
        electrode: view.placement?.electrode, reference: view.placement?.reference,
      });
      const registeredSurface = body.children.find(mesh => mesh.name === view.sceneContext?.mesh_part);
      if (!dragging && registeredSurface && view.placement !== lastContactPlacement) {
        lastContactPlacement = view.placement;
        const inside = [];
        ['electrode', 'reference'].forEach(key => {
          const contact = contactMeshes[key];
          const normal = surfaceContactNormal(contact.position.toArray(), registeredSurface);
          const location = surfaceContactLocation(contact.position.toArray(), registeredSurface);
          renderer.domElement.dataset[key + 'BodyLocation'] = location;
          if (location === 'inside') inside.push(key === 'electrode' ? 'E1' : 'REF');
          contact.quaternion.identity();
          if (normal) contact.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);
          renderer.domElement.dataset[key + 'SurfaceAligned'] = String(Boolean(normal));
        });
        setInsideContacts(inside.join(' и '));
      }
      Object.values(contactMeshes).forEach(group => {
        const contact = group.children[0];
        contact.material.color.setHex(view.invalidPlacement ? 0xff5b68 : contact.userData.originalColor);
      });
      if (view.placing !== lastPlacing || view.selectedContact !== lastSelected) {
        if (view.placing) transform.attach(contactMeshes[view.selectedContact]); else transform.detach();
        lastSelected = view.selectedContact; lastPlacing = view.placing;
      }
      camera.updateMatrixWorld();
      aperture.update(renderer, camera, center, !wholeCns && view.localWindow && body.children.length > 0);
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
      window.removeEventListener('keydown', cycleInspection, true);
      window.removeEventListener('keyup', releaseInspection);
      window.removeEventListener('blur', leave);
      renderer.domElement.removeEventListener('webglcontextlost', contextLost);
      controls.dispose();
      // Three r169's TransformControls.dispose calls this.traverse even though
      // the controller is not an Object3D. Disconnect its public input owner;
      // the registered helper's resources are disposed by scene traversal below.
      transform.disconnect(); transform.detach(); aperture.dispose();
      if (connectomeLayer) { scene.remove(connectomeLayer.group); connectomeLayer.dispose(); connectomeLayer = null; }
      if (contrastLayer) { scene.remove(contrastLayer.points); contrastLayer.dispose(); contrastLayer = null; }
      if (fieldContacts) { scene.remove(fieldContacts.group); fieldContacts.dispose(); fieldContacts = null; }
      if (compartmentLayer) { scene.remove(compartmentLayer.points); compartmentLayer.dispose(); compartmentLayer = null; }
      scene.traverse(object => { object.geometry?.dispose(); if (object.userData.sourceGeometry !== object.geometry) object.userData.sourceGeometry?.dispose(); if (object.material) (Array.isArray(object.material) ? object.material : [object.material]).forEach(m => { m.map?.dispose(); m.dispose(); }); });
      renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); state.current = {};
    };
  }, [assetId, cameraLink, synchronizeCamera, canvasLabel, navigationHelp, graphicsAttempt]);
  useEffect(() => { state.current.fit?.(); }, [resetCamera]);
  useEffect(() => { if (focusLocal) state.current.focusLocal?.(); }, [focusLocal]);
  return <Box ref={host} position="absolute" inset={0} overflow="hidden">
    <VisuallyHidden id={navigationHelp}>Стрелки перемещают камеру; Shift и стрелки вращают её. Alt и наведение показывают сведения о нейроне; Alt и стрелки вверх и вниз переключают перекрывающиеся точки; Alt и щелчок открывают связи.</VisuallyHidden>
    {pinnedNode && runId && <NeuronConnections key={`${runId}:${pinnedNode}:${fieldRun?.id || ''}`} runId={runId} nodeId={pinnedNode}
      fragmentRunId={Array.isArray(fieldRun?.configuration?.source_ids) ? fieldRun.id : null}
      onShowTarget={onShowTarget}
      onFocusProbe={previewData => state.current.focusProbe?.(previewData)}
      positionDescription={pinnedPosition}
      canFocusNode={pinnedVisible} onFocusNode={() => state.current.focusNode?.(pinnedNode)}
      onPage={setSelectedEdges} morphology={selectedMorphology} neighborMorphology={neighborMorphology} synapses={synapses} onSelectNode={setPinnedNode} onClose={() => setPinnedNode(null)} />}
    {inspected && nodeHit && <Box role="tooltip" aria-label="Сведения о нейроне" position="absolute" pointerEvents="none"
      left={`${Math.max(8, Math.min(nodeHit.x + 16, nodeHit.width - 284))}px`} top={`${Math.max(54, Math.min(nodeHit.y + 16, nodeHit.height - 220))}px`}
      w="268px" p={3} border="1px solid #31405d" borderRadius="6px" bg="rgba(6,9,20,.97)" fontSize="12px" color="#cbd4e3">
      <Text fontWeight="600" color="white">MaleCNS · {inspected.id}</Text>
      {nodeHit.candidateCount > 1 && <Text color="#a9b7d2">Точка {nodeHit.candidateIndex + 1} из {nodeHit.candidateCount}{nodeHit.candidateCount === 64 ? ' ближайших' : ''} · Alt + ↑/↓ переключить</Text>}
      <Text color={inspected.isInput ? '#ffb16b' : '#8ee4c4'}>{inspected.isInput ? 'Входная сенсорная популяция' : 'Нейрон сети'}</Text>
      <Text mt={1}>{inspected.coordinateName}</Text>
      {inspected.nativeUm && <Text>EM, мкм (приблизительно): {inspected.nativeUm.map(value => value.toFixed(2)).join(' · ')}</Text>}
      {inspected.morphologyVertex && <Text>Вершина SWC: {inspected.morphologyVertex}</Text>}
      {inspected.displayedOutgoing.slice(0, 3).map((edge, i) => <Text key={`${edge.targetId}-${i}`}>Связь в выборке → {edge.targetId} · знак в LIF: {edge.sign > 0 ? '+' : edge.sign < 0 ? '−' : 'не определён'}</Text>)}
      <Text color="#8792aa">Выборка связей для отображения неполная; знак основан на предсказании медиатора.</Text>
      <Text>Спайков к {timeMs.toFixed(2)} мс: {inspected.deliveredSpikes} · всего: {inspected.totalSpikes ?? 'неизвестно'}</Text>
      <Text>Первый: {inspected.firstSpikeMs === null ? 'не зарегистрирован' : `${inspected.firstSpikeMs.toFixed(2)} мс`}</Text>
      <Text color="#8792aa" mt={1}>Положение в сцене — обзорное совмещение; это не электродный источник.</Text>
    </Box>}
    {(placing || pickingStimulus || fieldContactPick) && hover && <Box data-region-preview={hover.supported ? 'registered' : 'view-only'} aria-hidden="true" position="absolute" left={`${hover.x}px`} top={`${hover.y}px`} pointerEvents="none">
      <Box w="10px" h="10px" border="2px solid" borderColor={hover.supported ? 'blue.200' : 'gray.400'} borderRadius="full" transform="translate(-50%, -50%)" />
      <Text position="absolute" top={hover.y > hover.height - 70 ? '-54px' : '10px'} left={hover.x > hover.width - 184 ? '-172px' : '12px'} w="160px" px={2} py={1} borderRadius="4px" bg="rgba(6,9,20,.95)" fontSize="11px">{fieldContactPick ? 'Установить контакт на область ЦНС' : pickingStimulus ? hover.supported ? 'Выбрать сенсорный вход этой области' : 'Локальный сенсорный вход не определён' : hover.supported ? 'Установить записывающий контакт · зазор 25 мкм' : 'Область для просмотра; расчёт не зарегистрирован'}</Text>
    </Box>}
    {!loaded && !error && <Text position="absolute" top="50%" w="100%" textAlign="center" role="status">Загрузка модели мухи…</Text>}
    {assetId?.startsWith('flybody-') && !nativeView && <Box position="absolute" top="62px" right={4} maxW="220px" textAlign="right" fontSize="11px">
      <HStack justify="end" spacing={1} mb={1}>
        <Button size="xs" variant="outline" onClick={() => state.current.orient?.([0, -.001, 1])}>Сверху</Button>
        <Button size="xs" variant="outline" onClick={() => state.current.orient?.([0, -1, 0])}>Сбоку</Button>
        <Button size="xs" variant="outline" onClick={() => state.current.orient?.([1, 0, 0])}>Спереди</Button>
      </HStack>
    </Box>}
    {connectome.loading && <Text position="absolute" top="62px" left={4} role="status" fontSize="12px">Загрузка полной сети и журнала спайков…</Text>}
    {coverage && !connectome.morphologyError && <Box position="absolute" top={3} left={3} w="fit-content" maxW="min(800px, 75%)" pointerEvents="none" fontSize="12px" color="gray.300">
      <HStack spacing={1} flexWrap="wrap" pointerEvents="auto" bg="rgba(9,13,25,.94)" border="1px solid #202a43" borderRadius="6px" p={1}>
      {sceneControls}
      {assetId?.startsWith('flybody-') && !nativeView && <Button size="xs" variant="ghost" aria-pressed={showJoints} onClick={() => setShowJoints(value => !value)}>{showJoints ? 'Скрыть суставы' : 'Показать суставы'}</Button>}
      {overview.error && <Button size="xs" variant="ghost" onClick={overview.retry}>Повторить загрузку отростков</Button>}
      {(fieldRun || fieldContactDraft) && fieldContactsValid && <Button size="xs" variant="ghost" aria-pressed={showFieldContacts} onClick={() => setShowFieldContacts(value => !value)}>{showFieldContacts ? 'Скрыть электроды' : 'Показать электроды'}</Button>}
      </HStack>
      <Text color="#aebbd2" mt={1}>Alt + наведение — нейрон · Alt + щелчок — его связи</Text>
      {(fieldRun || fieldContactDraft) && fieldContactsValid && !fieldContactPick && <Text color="#aebbd2">Shift + Alt + щелчок — выбрать электрод · щелчок по области ЦНС — разместить</Text>}
      {showJoints && kinematics.loading && <Text role="status" mt={1}>Загрузка суставов исходной модели…</Text>}
      {showJoints && kinematics.error && <Box pointerEvents="auto"><Text role="alert">{kinematics.error}</Text><Button size="xs" onClick={kinematics.retry}>Повторить загрузку суставов</Button></Box>}
      {fieldContactPick && <Text color="#aebbd2" mt={1}>Щёлкните по области ЦНС, чтобы разместить электрод · Esc — отмена</Text>}
      {fieldRun && !fieldContactsValid && <Text color="orange.200" mt={1}>Координаты контактов недоступны; они не показаны.</Text>}
      {fieldRun && contrast.loading && <Text role="status" mt={1}>Загрузка разности состояний…</Text>}
      {fieldRun && contrast.error && <Box pointerEvents="auto"><Text role="alert" mt={1}>Не удалось проверить разность состояний.</Text><Button size="xs" onClick={contrast.retry}>Повторить загрузку</Button></Box>}
      {!fieldRun && !fieldContactDraft && !nativeView && insideContacts && <Text color="orange.200" data-testid="internal-recording-contacts">{insideContacts} внутри меша тела. Это прежние внутренние координаты записи; наружное положение задаётся отдельно в режиме «Электроды».</Text>}
      {arbors.loading && <Text role="status" mt={1}>Загрузка отростков…</Text>}
      {showNeuropil && neuropil.loading && <Text role="status" mt={1}>Загрузка областей ЦНС: {neuropil.meshes.length} из 114</Text>}
      {showNeuropil && neuropil.error && <Box pointerEvents="auto"><Text role="alert" mt={1}>Не удалось загрузить области ЦНС.</Text><Button size="xs" onClick={neuropil.retry}>Повторить загрузку областей</Button></Box>}
      {arbors.error && <Box pointerEvents="auto"><Text role="alert" mt={1}>{arbors.error}</Text><Button size="xs" onClick={arbors.retry}>Повторить загрузку отростков</Button></Box>}
      {motor.error && <Box pointerEvents="auto"><Text role="alert" mt={1}>{motor.error}</Text><Button size="xs" onClick={motor.retry}>Повторить загрузку моторных популяций</Button></Box>}
    </Box>}
    {connectome.morphologyError && <Stack position="absolute" top="62px" left={4} right={4} align="start" bg="rgba(6,9,20,.96)" p={3}>
      <Text role="alert" fontSize="12px">{connectome.morphologyError}</Text><Button size="xs" onClick={connectome.retry}>Повторить загрузку морфологии</Button>
    </Stack>}
    {connectome.error && <Stack position="absolute" top="62px" left={4} right={4} align="start" bg="rgba(6,9,20,.96)" p={3}>
      <Text role="alert" fontSize="12px">{connectome.error}</Text><Button size="xs" onClick={connectome.retry}>Повторить загрузку коннектома</Button>
    </Stack>}
    {error && <Stack position="absolute" top="40%" left={6} right={6} p={4} bg="rgba(6,9,20,.96)" align="start">
      <Text role="alert">{error}</Text>
      <Button size="sm" variant="outline" onClick={() => setGraphicsAttempt(value => value + 1)}>Восстановить 3D-сцену</Button>
    </Stack>}
  </Box>;
}
