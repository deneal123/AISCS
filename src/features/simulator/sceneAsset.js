export const sceneAssetPath = context => context?.mesh_asset_id?.startsWith('flybody-')
  ? '/assets/simulator/flybody/scene.json' : '/assets/simulator/fly.json';

async function checksum(buffer) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))].map(value => value.toString(16).padStart(2, '0')).join('');
}

export async function loadSceneAsset(context, signal) {
  const url = sceneAssetPath(context);
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error('asset');
  const buffer = await response.arrayBuffer();
  if (context?.mesh_sha256 && await checksum(buffer) !== context.mesh_sha256) throw new Error('mesh_integrity');
  const asset = JSON.parse(new TextDecoder().decode(buffer));
  if (!asset.binary) return asset;
  if (asset.binary.file !== 'scene.bin') throw new Error('mesh_integrity');
  const meshResponse = await fetch(url.replace('scene.json', 'scene.bin'), { signal });
  if (!meshResponse.ok) throw new Error('asset');
  const binary = await meshResponse.arrayBuffer();
  if (binary.byteLength !== asset.binary.bytes || await checksum(binary) !== asset.binary.sha256) throw new Error('mesh_integrity');
  return { ...asset, parts: asset.parts.map(part => ({ ...part,
    positions: new Float32Array(binary, part.positions.byte_offset, part.positions.count),
    normals: new Float32Array(binary, part.normals.byte_offset, part.normals.count),
    indices: new Uint32Array(binary, part.indices.byte_offset, part.indices.count),
  })) };
}
