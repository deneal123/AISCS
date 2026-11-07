import React, { useEffect, useRef, useState } from 'react';
import { Box, Button, HStack, Text } from '@chakra-ui/react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';
import { maleCnsNativePosition, maleCnsViewPosition, NATIVE_VIEW_MATRIX } from '../connectome/connectomeMorphology';
import useFieldMorphologies from './useFieldMorphologies';

const matrix = new THREE.Matrix4().set(...NATIVE_VIEW_MATRIX);
const inverse = matrix.clone().invert();
export const contactToScene = point => new THREE.Vector3(...maleCnsViewPosition(point)).applyMatrix4(matrix);
export const sceneToContact = point => maleCnsNativePosition(point.clone().applyMatrix4(inverse).toArray());
const contacts = [['source_um', 'STIM+', 0xff9859], ['return_um', 'STIM−', 0xf1c15c],
  ['electrode_um', 'E1', 0x5d8fff], ['reference_um', 'REF', 0xc5d4ff]];
export const draggedContactKey = (markers, object, selected) =>
  selected && markers[selected] && markers[selected] === object ? selected : null;

// The drawing uses only verified SWC coordinates. It is deliberately independent
// of the fly body, whose transform is not an anatomical registration.
export default function FieldContactScene({ runId, manifest, bodyIds, coordinates, onChange, disabled }) {
  const morphology = useFieldMorphologies(runId, bodyIds, manifest);
  const host = useRef(null), latest = useRef({}), fitView = useRef(null);
  const [selected, setSelected] = useState('source_um');
  const [graphicsError, setGraphicsError] = useState(false);
  latest.current = { coordinates, onChange, selected, disabled };

  useEffect(() => {
    if (!morphology.data.length || !host.current) return undefined;
    const container = host.current;
    let renderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true }); }
    catch { setGraphicsError(true); return undefined; }
    setGraphicsError(false);
    renderer.setClearColor(0x080d19); renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    container.appendChild(renderer.domElement);
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(45, 1, .001, 100);
    const orbit = new OrbitControls(camera, renderer.domElement); orbit.enableDamping = true;
    const material = new THREE.LineBasicMaterial({ color: 0x6da9ca, transparent: true, opacity: .7 });
    const arbors = new THREE.Group(), geometries = [];
    morphology.data.forEach(cell => {
      const geometry = new THREE.BufferGeometry(); geometries.push(geometry);
      geometry.setAttribute('position', new THREE.BufferAttribute(cell.positions, 3));
      const arbor = new THREE.LineSegments(geometry, material); arbor.applyMatrix4(matrix); arbors.add(arbor);
    });
    scene.add(arbors);
    const markerGeometry = new THREE.SphereGeometry(.008, 16, 12), markers = {};
    contacts.forEach(([key, , color]) => {
      const marker = new THREE.Mesh(markerGeometry, new THREE.MeshBasicMaterial({ color }));
      scene.add(marker); markers[key] = marker;
    });
    const transform = new TransformControls(camera, renderer.domElement);
    scene.add(transform.getHelper()); transform.setSize(.8);
    transform.addEventListener('dragging-changed', event => { orbit.enabled = !event.value; });
    transform.addEventListener('objectChange', () => {
      if (!transform.dragging || latest.current.disabled) return;
      const key = draggedContactKey(markers, transform.object, latest.current.selected);
      if (!key) return;
      const point = sceneToContact(transform.object.position).map(value => Math.round(value * 1000) / 1000);
      if (point.every(Number.isFinite)) latest.current.onChange(key, point);
    });
    const fit = () => {
      const bounds = new THREE.Box3().setFromObject(arbors);
      // Use current coordinates, including values just edited in the form.
      contacts.forEach(([key]) => {
        const point = latest.current.coordinates?.[key];
        if (Array.isArray(point) && point.length === 3 && point.every(value => String(value).trim() !== '' && Number.isFinite(Number(value)))) {
          bounds.expandByPoint(contactToScene(point.map(Number)));
        }
      });
      if (bounds.isEmpty()) return;
      const center = bounds.getCenter(new THREE.Vector3());
      const radius = Math.max(.08, bounds.getSize(new THREE.Vector3()).length() * .5);
      const direction = camera.position.clone().sub(orbit.target);
      if (direction.lengthSq() < 1e-12) direction.set(1, -1, .7);
      const vertical = THREE.MathUtils.degToRad(camera.fov);
      const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * camera.aspect);
      const distance = radius * 1.08 / Math.sin(Math.min(vertical, horizontal) / 2);
      camera.position.copy(center).add(direction.normalize().multiplyScalar(distance));
      orbit.target.copy(center);
      camera.near = Math.max(.0001, radius / 1000); camera.far = Math.max(10, radius * 100); camera.updateProjectionMatrix();
      orbit.update();
      renderer.domElement.dataset.viewRadius = radius.toFixed(6);
      renderer.domElement.dataset.viewCenter = center.toArray().map(value => value.toFixed(6)).join(',');
    };
    fitView.current = fit;
    const resize = () => { const { clientWidth, clientHeight } = container; if (!clientWidth || !clientHeight) return;
      camera.aspect = clientWidth / clientHeight; camera.updateProjectionMatrix(); renderer.setSize(clientWidth, clientHeight); };
    const observer = new ResizeObserver(resize); observer.observe(container); resize(); fit();
    let frame;
    const render = () => {
      const current = latest.current;
      contacts.forEach(([key]) => {
        const point = current.coordinates?.[key];
        const valid = Array.isArray(point) && point.length === 3 && point.every(value => String(value).trim() !== '' && Number.isFinite(Number(value)));
        markers[key].visible = valid;
        if (valid && !(transform.dragging && current.selected === key)) markers[key].position.copy(contactToScene(point.map(Number)));
      });
      if (!current.disabled && markers[current.selected]?.visible) {
        if (transform.object !== markers[current.selected]) transform.attach(markers[current.selected]);
      } else transform.detach();
      orbit.update(); renderer.render(scene, camera); frame = requestAnimationFrame(render);
    };
    render();
    return () => { fitView.current = null; cancelAnimationFrame(frame); observer.disconnect();
      // Three r169 TransformControls.dispose calls this.traverse although the
      // control is not an Object3D. Dispose its helper explicitly instead.
      transform.disconnect(); transform.detach();
      transform.getHelper().traverse(child => {
        child.geometry?.dispose();
        if (child.material) (Array.isArray(child.material) ? child.material : [child.material]).forEach(item => item.dispose());
      });
      orbit.dispose();
      geometries.forEach(geometry => geometry.dispose()); material.dispose(); markerGeometry.dispose(); Object.values(markers).forEach(marker => marker.material.dispose());
      renderer.dispose(); renderer.domElement.remove(); };
  }, [morphology.data]);

  if (!runId || !manifest || !bodyIds.length) return <Text fontSize="12px">Для просмотра отростков выберите завершённый опыт MaleCNS.</Text>;
  return <Box mt={3}>
    <Text fontSize="12px" mb={2}>Исходная морфология выбранных нейронов · координаты MaleCNS, мкм</Text>
    {morphology.loading && <Text fontSize="12px" role="status">Загрузка морфологии…</Text>}
    {morphology.missing.length > 0 && <HStack><Text fontSize="12px" role="alert">Не удалось проверить морфологию: {morphology.missing.join(', ')}.</Text><Button size="xs" onClick={morphology.retry}>Повторить</Button></HStack>}
    {graphicsError && <Text fontSize="12px" role="alert">3D недоступно; координаты можно изменить вручную.</Text>}
    {morphology.data.length > 0 && <>
      <HStack mb={2} spacing={1} flexWrap="wrap">{contacts.map(([key, label, color]) => <Button key={key} size="xs" variant={selected === key ? 'solid' : 'ghost'} aria-pressed={selected === key} isDisabled={disabled} onClick={() => setSelected(key)}>
        <Box as="span" aria-hidden="true" w="8px" h="8px" flexShrink={0} borderRadius="full" bg={`#${color.toString(16).padStart(6, '0')}`} mr={2} />{label}
      </Button>)}<Button size="xs" variant="ghost" ml="auto" onClick={() => fitView.current?.()}>Показать все</Button></HStack>
      <Box ref={host} h="280px" w="100%" border="1px solid" borderColor="#263453" borderRadius="6px" overflow="hidden" aria-label="Размещение контактов относительно отростка в координатах MaleCNS" />
      <Text fontSize="11px" color="gray.400" mt={2}>Выберите контакт и переместите его за цветные оси. Вращение — мышью, масштаб — колёсиком. Показано {morphology.data.length} из {bodyIds.length} выбранных клеток; тело и границы тканей не зарегистрированы.</Text>
    </>}
  </Box>;
}
