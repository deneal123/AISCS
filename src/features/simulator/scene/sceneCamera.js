// Imperative camera synchronization avoids re-rendering the page on every
// orbit frame. Positions are relative to each registered scene origin.
export function createCameraLink() {
  let pose = null;
  const listeners = new Map();
  const copy = value => ({ position: [...value.position], target: [...value.target] });
  return {
    snapshot: () => pose && copy(pose),
    reset() { pose = null; },
    publish(value, owner) {
      if (![value?.position, value?.target].every(vector => Array.isArray(vector) && vector.length === 3 && vector.every(Number.isFinite))) return;
      if (pose && ['position', 'target'].every(key => pose[key].every((coordinate, index) => Math.abs(coordinate - value[key][index]) < 1e-9))) return;
      pose = copy(value);
      listeners.forEach((listener, id) => { if (id !== owner) listener(copy(pose)); });
    },
    subscribe(owner, listener) {
      listeners.set(owner, listener);
      return () => listeners.delete(owner);
    },
  };
}
