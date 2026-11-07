import { sensoryRegionForPart, sensoryRegionForSurface, partReceivesSensoryInput, sensoryInputName } from '../../../src/features/simulator/scene/stimulusRegions';

test('an older catalog cannot describe the pooled six-leg input as thoracic skin', () => {
  expect(sensoryInputName('thorax', [{ id: 'thorax', name: 'Грудь' }])).toBe('Объединённый сенсорный вход шести ног');
  expect(sensoryInputName('front_left', [{ id: 'front_left', name: 'Передняя левая нога' }])).toBe('Передняя левая нога');
});

test('thorax, wings and unmapped body regions never silently select six leg nerves', () => {
  for (const part of ['thorax', 'c_thorax', 'wing_left', 'unknown']) expect(sensoryRegionForPart(part)).toBeNull();
});

test('the dorsal mesh selects the entire notum population only on upward facing triangles', () => {
  expect(sensoryRegionForSurface('c_thorax', '', 0.8)).toBe('notum');
  expect(sensoryRegionForSurface('thorax', '', 0.8)).toBe('notum');
  for (const normal of [0.49, 0, -1, NaN, undefined]) expect(sensoryRegionForSurface('c_thorax', '', normal)).toBeNull();
  expect(sensoryRegionForSurface('wing_left', '', 1)).toBeNull();
  expect(sensoryRegionForSurface('tarsus', 'coxa_T1_left', 1)).toBe('front_left');
});

test('leg selection preserves segment and laterality; head and abdomen are distinct', () => {
  for (const [t, prefix] of [[1, 'front'], [2, 'middle'], [3, 'hind']]) {
    for (const side of ['left', 'right']) expect(sensoryRegionForPart('tarsus', `coxa_T${t}_${side}`)).toBe(`${prefix}_${side}`);
  }
  expect(sensoryRegionForPart('head')).toBe('head');
  expect(sensoryRegionForPart('abdomen')).toBe('abdomen');
});

test('saved pooled leg input highlights legs only, while unilateral input stays unilateral', () => {
  expect(partReceivesSensoryInput('tarsus', 'coxa_T1_left', 'front_left')).toBe(true);
  expect(partReceivesSensoryInput('tarsus', 'coxa_T1_right', 'front_left')).toBe(false);
  expect(partReceivesSensoryInput('tarsus', 'coxa_T3_right', 'thorax')).toBe(true);
  expect(partReceivesSensoryInput('thorax', '', 'thorax')).toBe(false);
  expect(partReceivesSensoryInput('head', '', 'thorax')).toBe(false);
  expect(partReceivesSensoryInput('thorax', '', 'notum')).toBe(true);
  expect(partReceivesSensoryInput('tarsus', 'coxa_T1_left', 'notum')).toBe(false);
});
