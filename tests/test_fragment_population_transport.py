import hashlib
import json
import zipfile

import pytest

from service.infrastructure.stimulation.fragment_population_transport import (
    LEGACY_FILES,
    pack_fragment_population,
    unpack_fragment_population,
)


def source_archive(path):
    path.mkdir()
    files = []
    for name in LEGACY_FILES:
        data = name.encode('ascii')
        (path / name).write_bytes(data)
        files.append({'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    manifest = {'kind': 'experimental-fragment-population', 'files': files}
    (path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
    return manifest


def test_population_transport_round_trip_and_digest_guard(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    manifest = source_archive(source)
    monkeypatch.setattr(
        'service.infrastructure.stimulation.fragment_population_transport.'
        'load_verified_fragment_population', lambda *_: {'manifest': manifest})
    package = tmp_path / 'archive.zip'
    receipt = pack_fragment_population(source, None, package)
    duplicate = tmp_path / 'duplicate.zip'
    assert pack_fragment_population(source, None, duplicate) == receipt
    assert package.read_bytes() == duplicate.read_bytes()
    restored = tmp_path / 'restored'
    assert unpack_fragment_population(package, receipt['sha256'], receipt['manifest_sha256'],
                                      restored, None)['manifest'] == manifest
    assert all((source / name).read_bytes() == (restored / name).read_bytes()
               for name in LEGACY_FILES)
    with pytest.raises(ValueError, match='checksum'):
        unpack_fragment_population(package, '0' * 64, receipt['manifest_sha256'],
                                   tmp_path / 'bad', None)
    with pytest.raises(FileExistsError):
        pack_fragment_population(source, None, package)


def test_population_transport_rejects_unexpected_paths(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    manifest = source_archive(source)
    monkeypatch.setattr(
        'service.infrastructure.stimulation.fragment_population_transport.'
        'load_verified_fragment_population', lambda *_: {'manifest': manifest})
    package = tmp_path / 'archive.zip'
    receipt = pack_fragment_population(source, None, package)
    with zipfile.ZipFile(package, 'a') as archive:
        archive.writestr('../outside', b'bad')
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='Unexpected'):
        unpack_fragment_population(package, digest, receipt['manifest_sha256'],
                                   tmp_path / 'restored', None)
    assert not (tmp_path / 'outside').exists()
