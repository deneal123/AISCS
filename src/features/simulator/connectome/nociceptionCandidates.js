import ascending from './nociceptionAscendingCandidates.json';

// Predicted MaleCNS cross-dataset matches, not verified identities or function.
// Source audit: docs/Материалы/План_генератора_2026-10/17-nociception-reference-and-id-boundaries.md
const GRAPH = '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2';
const IDS = new Set(['806527', '804528', '848690', '810474', '804024', '805587', '804202', '805314',
  '908138', '805493', '906519', '902929', '809260', '806067', '805534', '811993', '910127',
  '905881', '903750', '909515', '801695', '812018', '805594', '813922', '814579', '1050213678']);
const ASCENDING_IDS = new Set(ascending.ids);

function matchingIndices(data, ids) {
  if (data?.description?.manifest_sha256 !== GRAPH || ascending.graph_manifest_sha256 !== GRAPH || !data.node_ids) return [];
  const indices = [];
  data.node_ids.forEach((id, index) => {
    if (ids.has(String(id)) && data.coordinate_kind?.[index] > 0) indices.push(index);
  });
  return indices;
}

export const nociceptionCandidateIndices = data => matchingIndices(data, IDS);
export const nociceptionAscendingIndices = data => matchingIndices(data, ASCENDING_IDS);
