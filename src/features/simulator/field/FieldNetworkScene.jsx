import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Box, Button, HStack, Text } from '@chakra-ui/react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { createConnectomeLayer } from '../connectome/connectomeLayer';
import { NATIVE_VIEW_MATRIX } from '../connectome/connectomeMorphology';
import { contactToScene, sceneToContact } from './FieldContactScene';
import useConnectomeData from '../connectome/useConnectomeData';
import useFieldMorphologies from './useFieldMorphologies';
import useStateContrast from '../useStateContrast';
import { createStateContrastLayer } from '../stateContrastLayer';
import { bipolarPotential, fieldSlice, stimulusAtTime } from './fieldSlice';
import { createCompartmentEventLayer } from '../compartmentEvents';

export function fieldCellActive(times, now) {
  return times.some(time => now >= time && now - time < 6);
}

// Native EM landmarks are borrowed from a verified scene; events are exclusively
// the independently verified field-driven run. No body or invented neurites.
export default function FieldNetworkScene({ sceneRunId, description, fieldRun, timeMs }) {
  const graph = useConnectomeData(sceneRunId, description, fieldRun);
  const contrast = useStateContrast(fieldRun, graph.data);
  const positionedContrastCells = useMemo(() => contrast.data && graph.data
    ? contrast.data.indices.reduce((count, index) => count + Number(graph.data.coordinate_kind[index] > 0), 0)
    : 0, [contrast.data, graph.data]);
  const configuration = fieldRun.configuration;
  const cellIds = [...(configuration.source_cells || []).map(cell => String(cell.body_id)), ...(configuration.replay_ids || []).map(String), ...(configuration.source_ids || []).map(String)];
  const morphology = useFieldMorphologies(sceneRunId, cellIds, description.manifest_sha256);
  const host = useRef(null), clock = useRef(timeMs);
  const sceneRef = useRef(null), fieldRef = useRef(null), contrastRef = useRef(null), cameraRef = useRef(null);
  const cameraMemory = useRef(null);
  const [error, setError] = useState('');
  const [showField, setShowField] = useState(false);
  const [showContrast, setShowContrast] = useState(true);
  const [focusEmpty, setFocusEmpty] = useState(false);
  const [fieldPlane, setFieldPlane] = useState('xy');
  const [fieldScope, setFieldScope] = useState('contacts');
  const [slicePosition, setSlicePosition] = useState(null);
  const [nativeBounds, setNativeBounds] = useState(null);
  const [fieldInfo, setFieldInfo] = useState(null);
  const [fieldProbe, setFieldProbe] = useState(null);
  const frameMs = Number.isFinite(timeMs) ? Math.floor(timeMs) : 0;
  clock.current = timeMs;
  useEffect(() => { setSlicePosition(null); }, [fieldRun.id]);
  useEffect(() => { setFocusEmpty(false); }, [fieldRun.id, frameMs]);
  useEffect(() => {
    if (!graph.data || !host.current) return undefined;
    const container = host.current;
    let renderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true }); }
    catch { setError('WebGL недоступен.'); return undefined; }
    setError(''); renderer.setClearColor(0x080d19); renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    container.appendChild(renderer.domElement);
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(45, 1, .001, 100);
    sceneRef.current = scene;
    const orbit = new OrbitControls(camera, renderer.domElement); orbit.enableDamping = true;
    cameraRef.current = { camera, orbit };
    const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
    const probe = event => {
      if (event.buttons) { setFieldProbe(null); return; }
      const field = fieldRef.current;
      if (!field) { setFieldProbe(null); return; }
      const rect = renderer.domElement.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2);
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObject(field.mesh, false)[0];
      if (!hit) { setFieldProbe(null); return; }
      const point = sceneToContact(hit.point), simulation = configuration.simulation;
      const value = bipolarPotential(point, simulation.source_um, simulation.return_um,
        simulation.current_na, simulation.conductivity_s_m, simulation.clearance_um);
      setFieldProbe(value === null || !Number.isFinite(value) ? null : { point, value, field });
    };
    const clearProbe = () => setFieldProbe(null);
    renderer.domElement.addEventListener('pointermove', probe);
    renderer.domElement.addEventListener('pointerleave', clearProbe);
    orbit.addEventListener('start', clearProbe);
    const layer = createConnectomeLayer(graph.data); scene.add(layer.group); layer.coordinateView(true);
    const compartmentLayer = fieldRun.result?.preview?.compartment_events
      ? createCompartmentEventLayer(fieldRun.result.preview.compartment_events) : null;
    if (compartmentLayer) { compartmentLayer.coordinateView(true); scene.add(compartmentLayer.points); }
    const matrix = new THREE.Matrix4().set(...NATIVE_VIEW_MATRIX), arbors = [], markers = [];
    morphology.data.forEach(cell => {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(cell.positions, 3));
      const material = new THREE.LineBasicMaterial({ color: 0x6fa3bf, transparent: true, opacity: .48 });
      const mesh = new THREE.LineSegments(geometry, material); mesh.applyMatrix4(matrix); scene.add(mesh);
      const node = graph.data.node_ids.indexOf(BigInt(cell.id)), times = [];
      graph.data.spike_neurons.forEach((index, i) => { if (index === node) times.push(graph.data.spike_times_ms[i]); });
      arbors.push({ mesh, geometry, material, times });
    });
    const bounds = layer.nativeBounds.clone();
    [['source_um', 0xff9859], ['return_um', 0xf1c15c], ['electrode_um', 0x5d8fff], ['reference_um', 0xc5d4ff]].forEach(([key, color]) => {
      const point = configuration.simulation?.[key];
      if (!Array.isArray(point) || point.length !== 3 || !point.every(Number.isFinite)) return;
      // A fixed-size visual marker, not a claim about physical electrode radius.
      const marker = new THREE.Mesh(new THREE.SphereGeometry(.016, 16, 12), new THREE.MeshBasicMaterial({ color, depthTest: false }));
      marker.position.copy(contactToScene(point)); marker.renderOrder = 5; scene.add(marker); markers.push(marker);
      bounds.expandByPoint(marker.position);
    });
    const center = bounds.getCenter(new THREE.Vector3());
    const corners = [sceneToContact(bounds.min), sceneToContact(bounds.max)];
    setNativeBounds([0, 1, 2].map(axis => [Math.min(corners[0][axis], corners[1][axis]),
      Math.max(corners[0][axis], corners[1][axis])]));
    const radius = Math.max(.08, bounds.getSize(new THREE.Vector3()).length() * .5);
    camera.position.copy(center).add(new THREE.Vector3(1, -1, .6).normalize().multiplyScalar(radius * 2.6));
    orbit.target.copy(center);
    if (cameraMemory.current?.data === graph.data) {
      camera.position.fromArray(cameraMemory.current.position);
      orbit.target.fromArray(cameraMemory.current.target);
    }
    const resize = () => { const { clientWidth, clientHeight } = container; if (!clientWidth || !clientHeight) return;
      camera.aspect = clientWidth / clientHeight; camera.updateProjectionMatrix(); renderer.setSize(clientWidth, clientHeight); };
    const observer = new ResizeObserver(resize); observer.observe(container); resize();
    let frame;
    const render = () => {
      const status = layer.update(clock.current, true, true, null, { cameraDistance: camera.position.distanceTo(orbit.target) });
      const contrastStatus = contrastRef.current?.update(clock.current);
      renderer.domElement.dataset.contrastSample = contrastStatus ? String(contrastStatus.sample) : '';
      renderer.domElement.dataset.contrastActive = contrastStatus ? String(contrastStatus.active) : '';
      renderer.domElement.dataset.eventCount = String(status.delivered);
      renderer.domElement.dataset.compartmentEventCount = String(compartmentLayer?.update(clock.current) || 0);
      renderer.domElement.dataset.activeCount = String(status.active);
      let activeArbors = 0;
      arbors.forEach(arbor => {
        const active = fieldCellActive(arbor.times, clock.current);
        arbor.material.color.setHex(active ? 0x64ffbd : 0x6fa3bf);
        arbor.material.opacity = active ? .95 : .48;
        activeArbors += Number(active);
      });
      renderer.domElement.dataset.activeArbors = String(activeArbors);
      renderer.domElement.dataset.arborCount = String(arbors.length);
      renderer.domElement.dataset.contactCount = String(markers.length);
      const field = fieldRef.current;
      if (field) {
        const fraction = stimulusAtTime(fieldRun.result?.preview, clock.current);
        const sign = Math.sign(fraction);
        if (sign !== field.sign) {
          field.slice.values.forEach((value, index) => {
            const magnitude = value === null || !field.slice.maximum ? 0 : Math.sqrt(Math.abs(value) / field.slice.maximum);
            const positive = value * sign >= 0;
            field.colors.set(positive ? [magnitude, magnitude * .35, .08] : [.08, magnitude * .58, magnitude], index * 3);
          });
          field.geometry.attributes.color.needsUpdate = true; field.sign = sign;
        }
        field.material.opacity = field.slice.maximum ? .65 * Math.min(1, Math.abs(fraction)) : 0;
        renderer.domElement.dataset.fieldFraction = String(fraction);
      }
      orbit.update();
      renderer.domElement.dataset.cameraPosition = camera.position.toArray().map(value => value.toFixed(5)).join(',');
      renderer.render(scene, camera); frame = requestAnimationFrame(render);
    };
    render();
    return () => { cancelAnimationFrame(frame); observer.disconnect();
      cameraMemory.current = { data: graph.data, position: camera.position.toArray(), target: orbit.target.toArray() };
      renderer.domElement.removeEventListener('pointermove', probe);
      renderer.domElement.removeEventListener('pointerleave', clearProbe);
      orbit.removeEventListener('start', clearProbe);
      orbit.dispose(); layer.dispose();
      compartmentLayer?.dispose();
      arbors.forEach(arbor => { arbor.geometry.dispose(); arbor.material.dispose(); });
      markers.forEach(marker => { marker.geometry.dispose(); marker.material.dispose(); });
      if (sceneRef.current === scene) sceneRef.current = null;
      if (cameraRef.current?.camera === camera) cameraRef.current = null;
      renderer.dispose(); renderer.domElement.remove(); };
  }, [graph.data, morphology.data, configuration, fieldRun.id, fieldRun.result]);
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene || !graph.data || !contrast.data || !showContrast) return undefined;
    const layer = createStateContrastLayer(graph.data, contrast.data);
    contrastRef.current = layer; scene.add(layer.points);
    return () => { if (contrastRef.current === layer) contrastRef.current = null;
      scene.remove(layer.points); layer.dispose(); };
  }, [graph.data, morphology.data, contrast.data, showContrast, configuration, fieldRun.id, fieldRun.result]);
  const focusContrast = () => {
    const view = cameraRef.current, layer = contrastRef.current;
    if (!view || !layer) return;
    const bounds = layer.bounds(clock.current);
    if (bounds.isEmpty()) { setFocusEmpty(true); return; }
    setFocusEmpty(false);
    const center = bounds.getCenter(new THREE.Vector3());
    const radius = Math.max(.025, bounds.getSize(new THREE.Vector3()).length() * .55);
    const direction = view.camera.position.clone().sub(view.orbit.target);
    if (direction.lengthSq() < 1e-12) direction.set(1, -1, .6);
    const vertical = THREE.MathUtils.degToRad(view.camera.fov);
    const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * view.camera.aspect);
    view.camera.position.copy(center).add(direction.normalize().multiplyScalar(radius / Math.sin(Math.min(vertical, horizontal) / 2)));
    view.orbit.target.copy(center); view.orbit.update();
  };
  useEffect(() => {
    const scene = sceneRef.current;
    if (!graph.data || !scene || !showField || (fieldScope === 'overview' && !nativeBounds)) { setFieldInfo(null); return undefined; }
    let geometry, material;
    try {
      const slice = fieldSlice(configuration.simulation, fieldScope === 'overview' ? 96 : 48,
        fieldPlane, slicePosition, fieldScope === 'overview' ? nativeBounds : null);
      const positions = new Float32Array(slice.positions.length * 3), colors = new Float32Array(positions.length);
      slice.positions.forEach((point, index) => contactToScene(point).toArray(positions, index * 3));
      geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
      geometry.setIndex(slice.triangles);
      material = new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true,
        opacity: 0, side: THREE.DoubleSide, depthWrite: false });
      const mesh = new THREE.Mesh(geometry, material); scene.add(mesh);
      const field = { slice, colors, geometry, material, mesh, sign: null };
      fieldRef.current = field;
      setFieldInfo({ runId: fieldRun.id, plane: fieldPlane, scope: fieldScope, maximum: slice.maximum, fixedAxis: slice.fixedAxis,
        fixedValue: slice.fixedValue, empty: slice.triangles.length === 0 });
      return () => { if (fieldRef.current === field) fieldRef.current = null; scene.remove(mesh);
        geometry.dispose(); material.dispose(); };
    } catch {
      geometry?.dispose(); material?.dispose();
      setFieldInfo({ runId: fieldRun.id, plane: fieldPlane, scope: fieldScope, error: true });
      return undefined;
    }
  }, [graph.data, morphology.data, configuration, fieldRun.id, fieldRun.result, showField, fieldPlane, fieldScope, nativeBounds, slicePosition]);
  const fixedAxis = fieldPlane === 'xy' ? 2 : fieldPlane === 'xz' ? 1 : 0;
  const range = nativeBounds?.[fixedAxis];
  const midpoint = (configuration.simulation.source_um[fixedAxis] + configuration.simulation.return_um[fixedAxis]) / 2;
  const position = slicePosition ?? midpoint;
  const displayTime = Number.isFinite(timeMs) ? timeMs : 0;
  const rawCurrent = configuration.simulation.current_na * stimulusAtTime(fieldRun.result?.preview, displayTime);
  const stimulusCurrent = Object.is(rawCurrent, -0) ? 0 : rawCurrent;
  return <Box mt={3}>
    <Text fontSize="12px" mb={2}>События электрического расчёта · исходные координаты MaleCNS</Text>
    {fieldRun.result?.preview?.compartment_events && <Text fontSize="11px" color="gray.400" mb={2}>
      Золотые точки — пороговые переходы модельных компартментов: показано {fieldRun.result.preview.compartment_events.shown} из {fieldRun.result.preview.compartment_events.total}. Это не измеренные спайки и не траектории распространения.
    </Text>}
    {graph.loading && <Text role="status" fontSize="12px">Проверка графа и событий…</Text>}
    {graph.error && <HStack><Text role="alert" fontSize="12px">{graph.error}</Text><Button size="xs" onClick={graph.retry}>Повторить</Button></HStack>}
    {graph.morphologyError && <Text role="alert" fontSize="12px">{graph.morphologyError}</Text>}
    {morphology.loading && <Text role="status" fontSize="12px">Загрузка отростков выбранных клеток…</Text>}
    {morphology.missing.length > 0 && <HStack><Text role="alert" fontSize="12px">Не удалось проверить отростки: {morphology.missing.join(', ')}.</Text><Button size="xs" onClick={morphology.retry}>Повторить</Button></HStack>}
    {error && <Text role="alert" fontSize="12px">{error}</Text>}
    {graph.data && <>
      <Text fontSize="11px" color="gray.400" mb={2}>
        События входных клеток: {graph.data.description.spikes - graph.data.description.spikes_outside_input_population} · вне входной группы: {graph.data.description.spikes_outside_input_population}. События вне входа сами по себе не подтверждают передачу от входных клеток.
      </Text>
      {contrast.loading && <Text role="status" fontSize="11px" color="gray.400" mb={2}>Проверка модельной разности…</Text>}
      {contrast.error && <HStack mb={2}><Text role="alert" fontSize="11px" color="orange.200">Не удалось проверить данные модельной разности. События и запись доступны отдельно.</Text><Button size="xs" variant="ghost" onClick={contrast.retry}>Повторить</Button></HStack>}
      {contrast.data && <>
        <Button size="xs" variant="outline" mb={2} mr={2} aria-pressed={showContrast} onClick={() => setShowContrast(value => !value)}>{showContrast ? 'Скрыть разность состояний' : 'Показать разность состояний'}</Button>
        {showContrast && <Button size="xs" variant="outline" mb={2} onClick={focusContrast}>Фокус на ответе</Button>}
        {showContrast && focusEmpty && <Text role="status" fontSize="11px" color="gray.400" mb={2}>В текущий момент видимых изменений нет.</Text>}
        {showContrast && <Text fontSize="11px" color="gray.400" mb={2}>Разность относительно контроля без входа: {contrast.data.cells} из {graph.data.node_ids.length} клеток, показано с координатами: {positionedContrastCells}, шаг 1 мс; общая шкала ±{contrast.data.maximum.toPrecision(3)} мВ. Оранжевый — выше контроля, голубой — ниже; значения до 0,1% шкалы не подсвечиваются. Это состояние модели, не спайки и не измеренный потенциал.</Text>}
      </>}
      <Button size="xs" variant="outline" mb={2} aria-pressed={showField} onClick={() => setShowField(value => !value)}>{showField ? 'Скрыть сечение поля' : 'Сечение поля STIM'}</Button>
      {showField && <><HStack mb={2} spacing={1} aria-label="Плоскость сечения">{['xy', 'xz', 'yz'].map(plane => <Button key={plane} size="xs" type="button" variant={fieldPlane === plane ? 'solid' : 'outline'} aria-pressed={fieldPlane === plane} onClick={() => { setFieldPlane(plane); setSlicePosition(null); }}>{plane.toUpperCase()}</Button>)}</HStack>
        <HStack mb={2} spacing={1} aria-label="Охват сечения"><Button size="xs" variant={fieldScope === 'contacts' ? 'solid' : 'outline'} aria-pressed={fieldScope === 'contacts'} onClick={() => setFieldScope('contacts')}>У контактов</Button><Button size="xs" variant={fieldScope === 'overview' ? 'solid' : 'outline'} aria-pressed={fieldScope === 'overview'} isDisabled={!nativeBounds} onClick={() => setFieldScope('overview')}>Обзор ЦНС</Button></HStack>
        {range && range[1] > range[0] && <HStack mb={2} spacing={2}><Text fontSize="11px" whiteSpace="nowrap">Положение {['X', 'Y', 'Z'][fixedAxis]}</Text><Box as="input" type="range" w="100%" h="16px" cursor="pointer" sx={{ accentColor: '#2D5BFF' }} aria-label={`Положение сечения ${['X', 'Y', 'Z'][fixedAxis]}, мкм`} min={range[0]} max={range[1]} step={(range[1] - range[0]) / 200} value={position} onChange={event => setSlicePosition(Number(event.target.value))} /><Text fontSize="11px" whiteSpace="nowrap">{position.toFixed(1)} мкм</Text></HStack>}
        <Text fontSize="11px" color="gray.400" mb={2}>STIM: {stimulusCurrent.toLocaleString('ru-RU', { maximumSignificantDigits: 4 })} нА · {displayTime.toFixed(2)} мс · интерполяция</Text></>}
      <Box position="relative"><Box ref={host} h="420px" w="100%" border="1px solid" borderColor="#263453" borderRadius="6px" overflow="hidden" aria-label="События электрического расчёта в исходном графе" />
        {fieldProbe && fieldProbe.field === fieldRef.current && showField && <Box position="absolute" top={2} right={2} bg="rgba(6,9,20,.92)" px={2} py={1} borderRadius="4px" fontSize="11px" pointerEvents="none" aria-label="Потенциал в точке сечения">
          <Text>EM: {fieldProbe.point.map(value => value.toFixed(1)).join(' / ')} мкм</Text>
          <Text>Потенциал: {(fieldProbe.value * stimulusAtTime(fieldRun.result?.preview, timeMs)).toPrecision(3)} мВ</Text>
          <Text color="gray.400">Аналитическая модель, не измерение</Text>
        </Box>}</Box>
      {showField && fieldInfo?.plane === fieldPlane && fieldInfo.scope === fieldScope && fieldInfo.runId === fieldRun.id && (fieldInfo.error || fieldInfo.fixedValue === position) && <Text fontSize="11px" color="gray.400" mt={2}>{fieldInfo.error ? 'Не удалось построить сечение поля для этих контактов.' : fieldInfo.empty ? 'Сечение полностью исключено геометрическим зазором.' : `Сечение ${fieldInfo.fixedAxis} = ${fieldInfo.fixedValue.toFixed(1)} мкм; ${fieldScope === 'contacts' ? 'показана область вокруг контактов STIM, не вся ЦНС' : 'обзор охватывает габариты отображаемых точек ЦНС и контактов, не границу всех отростков'}. Максимум в видимых узлах ±${fieldInfo.maximum.toPrecision(3)} мВ при полной амплитуде. Оранжевый — положительный потенциал, синий — отрицательный; в узлах яркость пропорциональна корню модуля, между ними цвет интерполируется. Прозрачность следует форме импульса с интерполяцией.`} Однородная среда, не модель тканей и не карта возбуждения.</Text>}
      <Text fontSize="11px" color="gray.400" mt={2}>Оранжевый и жёлтый — STIM+/STIM−; синий и светлый — E1/REF. Подсветка отростка обозначает событие всей клетки, а не распространение по нему. Тело и пути вне ЦНС не отображаются.</Text>
    </>}
  </Box>;
}
