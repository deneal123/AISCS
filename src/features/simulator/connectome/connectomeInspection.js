// Read-only interpretation of the saved event journal. Display landmarks are
// neither reconstructed somata nor electrode source compartments.
import { maleCnsNativePosition } from './connectomeMorphology';
import { hasDisplayPosition } from './connectomeRoutes';
export const COORDINATE_NAMES = {
  0: 'Условное положение',
  1: 'Сома из исходной аннотации',
  2: 'Ориентир to-soma из исходной аннотации',
  3: 'Вершина реконструированного отростка; не сома',
};

// A graph edge transmits from its presynaptic cell after a saved spike.
// Progress is along the displayed origin→endpoint line, so incoming reverses it.
export function connectionPulseProgress(direction, now, spikeTime, delay) {
  if (!['incoming', 'outgoing'].includes(direction) || !Number.isFinite(now)
      || !Number.isFinite(spikeTime) || !Number.isFinite(delay) || delay <= 0) return null;
  const elapsed = now - spikeTime;
  if (elapsed < 0 || elapsed >= delay) return null;
  const fraction = elapsed / delay;
  return direction === 'incoming' ? 1 - fraction : fraction;
}

export function inspectConnectomeNode(data, index, timeMs) {
  if (!Number.isSafeInteger(index) || index < 0 || index >= data.node_ids.length || !Number.isFinite(timeMs)) return null;
  let first = null, last = null, delivered = 0;
  for (let event = 0; event < data.spike_neurons.length; event += 1) {
    if (data.spike_neurons[event] !== index) continue;
    const time = data.spike_times_ms[event];
    if (first === null) first = time;
    if (time <= timeMs) { last = time; delivered += 1; }
  }
  const kind = data.coordinate_kind?.[index] ?? 0;
  const point = Array.from(data.positions_mm.subarray(index * 3, index * 3 + 3));
  const nativeUm = kind !== 0 && data.description.scene.embedding === 'male-cns-flybody-view-only-v2'
    && point.length === 3 && point.every(Number.isFinite) ? maleCnsNativePosition(point) : null;
  const displayedOutgoing = [];
  for (let edge = 0; edge < (data.edge_pre?.length || 0); edge += 1) {
    if (data.edge_pre[edge] !== index) continue;
    const target = data.edge_post[edge];
    if (target >= data.node_ids.length) continue;
    displayedOutgoing.push({ targetId: data.node_ids[target].toString(), sign: data.edge_sign[edge] });
  }
  return {
    id: data.node_ids[index].toString(), index,
    region: data.description.scene.regions?.[data.regions?.[index]] || 'unknown',
    coordinateKind: kind,
    coordinateName: COORDINATE_NAMES[kind], nativeUm,
    morphologyVertex: kind === 3 ? data.morphology_vertices?.[index] || null : null, displayedOutgoing,
    isInput: data.input_indices.includes(index), firstSpikeMs: first,
    lastSpikeMs: last, deliveredSpikes: delivered, totalSpikes: data.counts?.[index] ?? null,
  };
}
// A graph node may exist even when this view has no measured position for it.
export function selectedNodeVisible(data, id, nativeView) {
  if (!data || !id || !/^[1-9]\d{0,19}$/.test(id)) return false;
  const index = data.node_ids.indexOf(BigInt(id));
  return index >= 0 && hasDisplayPosition(data, index) && (!nativeView || data.coordinate_kind?.[index] > 0);
}

export function selectedNodePosition(data, id, nativeView) {
  if (!data || !id || !/^[1-9]\d{0,19}$/.test(id)) return null;
  const index = data.node_ids.indexOf(BigInt(id));
  if (index < 0) return 'Выбранный нейрон отсутствует в данных сцены.';
  const kind = data.coordinate_kind?.[index] || 0;
  if (nativeView && !kind) return 'В исходном виде положение этого нейрона не зарегистрировано; точка не показана.';
  if (!hasDisplayPosition(data, index)) return 'Для этого нейрона нет отображаемого положения; точка не показана.';
  if (!kind) return 'Выделенное положение нейрона показано условно, вдоль схемы периферического пути.';
  if (kind === 3) return 'Выделена зарегистрированная точка отростка, а не положение тела нейрона.';
  return 'Выделена точка по зарегистрированным координатам; совмещение с телом является обзорным.';
}
