// These are annotation-selected sensory populations, not an electrical field
// solved on the surface. In particular, a thorax click must not stimulate legs.
export function sensoryRegionForPart(name = '', legRoot = '') {
  if (/head|antenna|eye/.test(name)) return 'head';
  if (name.includes('abdomen')) return 'abdomen';
  const leg = legRoot.match(/T([123])_(left|right)/);
  if (leg) return `${{ 1: 'front', 2: 'middle', 3: 'hind' }[leg[1]]}_${leg[2]}`;
  return null;
}

// The dorsal face is a coarse visual selector for the whole notum population;
// it does not define a local receptor position or solve a stimulus field.
export function sensoryRegionForSurface(name, legRoot, normalZ) {
  if (['thorax', 'c_thorax'].includes(name) && Number.isFinite(normalZ) && normalZ >= 0.5) return 'notum';
  return sensoryRegionForPart(name, legRoot);
}

export function partReceivesSensoryInput(name, legRoot, region) {
  if (region === 'notum') return ['thorax', 'c_thorax'].includes(name);
  const selected = sensoryRegionForPart(name, legRoot);
  return region === 'thorax' ? Boolean(selected && /^(front|middle|hind)_/.test(selected))
    : selected !== null && selected === region;
}

export const unsupportedSurfaceInput = 'Для этой поверхности сенсорный вход не определён. Выберите верхнюю поверхность груди, голову или отдельную ногу. E1 и REF — контакты регистрации.';

// The legacy key "thorax" has always selected the pooled leg afferents. Older
// running catalogs called it simply "thorax", which incorrectly implied skin.
export function sensoryInputName(region, regions = []) {
  return region === 'thorax' ? 'Объединённый сенсорный вход шести ног'
    : regions.find(item => item.id === region)?.name || region;
}
