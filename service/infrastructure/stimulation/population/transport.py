"""Transfer a verified population archive without extracting arbitrary ZIP paths."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

from service.infrastructure.stimulation.population.archive import (
    BINARY_RESPONSE_FILES,
    FILES,
    LEGACY_FILES,
    RESPONSE_FILES,
    SPARSE_RESPONSE_FILES,
    load_verified_fragment_population,
)
from service.infrastructure.stimulation.recording.current_archive import _stream_sha

MAX_PACKAGE_BYTES = 512 * 1024 * 1024
ALLOWED = tuple(map(list, (LEGACY_FILES, FILES, RESPONSE_FILES, BINARY_RESPONSE_FILES,
                           SPARSE_RESPONSE_FILES)))


def _member(name):
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    return info


def _parse_manifest(payload, expected_sha):
    if (not isinstance(expected_sha, str) or not re.fullmatch(r'[a-f0-9]{64}', expected_sha)
            or hashlib.sha256(payload).hexdigest() != expected_sha or len(payload) > 65536):
        raise ValueError('Fragment manifest checksum mismatch')
    manifest = json.loads(payload)
    rows = manifest.get('files') if isinstance(manifest, dict) else None
    if (not isinstance(rows, list) or manifest.get('kind') != 'experimental-fragment-population'
            or [row.get('name') if isinstance(row, dict) else None for row in rows] not in ALLOWED
            or any(set(row) != {'name', 'bytes', 'sha256'} or type(row['bytes']) is not int
                   or not 0 < row['bytes'] <= MAX_PACKAGE_BYTES
                   or not isinstance(row['sha256'], str)
                   or not re.fullmatch(r'[a-f0-9]{64}', row['sha256']) for row in rows)
            or sum(row['bytes'] for row in rows) + len(payload) > MAX_PACKAGE_BYTES):
        raise ValueError('Invalid fragment manifest')
    return manifest


def pack_fragment_population(directory: Path, graph, target: Path):
    """Verify the source and package its exact members without overwriting."""
    verified = load_verified_fragment_population(directory, graph)
    manifest_path = directory / 'manifest.json'
    payload = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(payload).hexdigest()
    manifest = _parse_manifest(payload, manifest_sha)
    if manifest != verified['manifest'] or directory.resolve() in target.resolve().parents:
        raise ValueError('Fragment archive changed or target is inside it')
    with target.open('xb') as output, zipfile.ZipFile(output, 'w', zipfile.ZIP_STORED) as package:
        # Fixed ZIP timestamps make a package of the same checked input stable
        # across retries and independent workers.
        package.writestr(_member('manifest.json'), payload)
        for row in manifest['files']:
            path = directory / row['name']
            if path.is_symlink() or not path.is_file() or path.stat().st_size != row['bytes']:
                raise ValueError('Invalid fragment source member')
            with path.open('rb') as source:
                if _stream_sha(source) != row['sha256']:
                    raise ValueError('Fragment member checksum mismatch')
                source.seek(0)
                with package.open(_member(row['name']), 'w', force_zip64=True) as dest:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        dest.write(chunk)
                if _stream_sha(source) != row['sha256']:
                    raise ValueError('Fragment member changed during packaging')
    if target.stat().st_size > MAX_PACKAGE_BYTES:
        raise ValueError('Fragment package exceeds transport limit')
    with target.open('rb') as source:
        digest = _stream_sha(source)
    return {'sha256': digest, 'bytes': target.stat().st_size, 'manifest_sha256': manifest_sha}


def unpack_fragment_population(package_path: Path, package_sha: str, manifest_sha: str,
                               destination: Path, graph):
    """Verify transport and restore only the declared members into a new directory."""
    if (not isinstance(package_sha, str) or not re.fullmatch(r'[a-f0-9]{64}', package_sha)
            or not package_path.is_file() or package_path.is_symlink()
            or package_path.stat().st_size > MAX_PACKAGE_BYTES
            or destination.resolve() in package_path.resolve().parents):
        raise ValueError('Invalid fragment package')
    with package_path.open('rb') as source:
        if _stream_sha(source) != package_sha:
            raise ValueError('Fragment package checksum mismatch')
        source.seek(0)
        with zipfile.ZipFile(source) as package:
            infos = package.infolist()
            if (len(infos) > 10 or any(info.is_dir() or info.compress_type != zipfile.ZIP_STORED
                                       for info in infos)
                    or sum(info.filename == 'manifest.json' for info in infos) != 1
                    or package.getinfo('manifest.json').file_size > 65536):
                raise ValueError('Invalid fragment package contents')
            payload = package.read('manifest.json')
            manifest = _parse_manifest(payload, manifest_sha)
            expected = {'manifest.json', *(row['name'] for row in manifest['files'])}
            if len(infos) != len(expected) or {info.filename for info in infos} != expected:
                raise ValueError('Unexpected or duplicate fragment package members')
            destination.mkdir(parents=True, exist_ok=False)
            for row in manifest['files']:
                info = package.getinfo(row['name'])
                if info.file_size != row['bytes'] or info.compress_size != info.file_size:
                    raise ValueError('Fragment package member size mismatch')
                digest = hashlib.sha256()
                with package.open(info) as member, (destination / row['name']).open('xb') as output:
                    for chunk in iter(lambda: member.read(1024 * 1024), b''):
                        if output.write(chunk) != len(chunk):
                            raise OSError('Incomplete fragment archive restoration')
                        digest.update(chunk)
                if digest.hexdigest() != row['sha256']:
                    raise ValueError('Fragment package member checksum mismatch')
        if _stream_sha(source) != package_sha:
            raise ValueError('Fragment package changed during restoration')
    (destination / 'manifest.json').write_bytes(payload)
    return load_verified_fragment_population(destination, graph)
