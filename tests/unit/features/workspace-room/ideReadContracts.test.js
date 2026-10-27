import { ideCloneRecovery, ideFile, idePath, ideRepositoryPage, ideRuntime, ideTree } from '@features/workspace-room/model/ideReadContracts';

const repo = '00000000-0000-0000-0000-000000000001';
const generation = 'a'.repeat(64);
const row = { path: 'src/main.py', type: 'file', size: 5, incomplete: false };
const destination = '00000000-0000-0000-0000-000000000002';
const recovered = (request = { origin: 'https://github.com/owner/repo.git', branch: 'main' }) => ({
  intent_id: '10000000-0000-0000-0000-000000000001', source_repository_id: repo,
  repository: { repository_id: destination, name: 'Clone', state: 'registered', token: 'PRIVATE' }, state: 'preparing', request,
});

it('projects recovery for either owned endpoint without exposing private fields', () => {
  for (const selected of [repo, destination]) {
    const result = ideCloneRecovery({ attempt: { ...recovered(), token: 'PRIVATE' } }, selected);
    expect(result.source_repository_id).toBe(repo);
    expect(result.request).toEqual(recovered().request);
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
  }
  expect(ideCloneRecovery({ attempt: recovered(null) }, repo).request).toBeNull();
  expect(ideCloneRecovery({ attempt: null }, repo)).toBeNull();
});

it.each([
  undefined, { origin: 'https://user:token@github.com/owner/repo.git', branch: '' },
  { origin: 'https://github.com/owner/repo.git?token=secret', branch: '' },
  { origin: 'https://github.com/owner/repo.git', branch: '../main' },
  { origin: 'https://github.com/owner/repo.git', branch: 'feature/.private' },
  { origin: 'https://github.com/owner/repo.git', branch: 'a'.repeat(201) },
])('rejects unsafe or incomplete recovered parameters %p', request => {
  const attempt = recovered(); attempt.request = request;
  expect(() => ideCloneRecovery({ attempt }, repo)).toThrow();
});

it('rejects incomplete discovery, foreign selection and self-clone identity', () => {
  expect(() => ideCloneRecovery({}, repo)).toThrow();
  expect(() => ideCloneRecovery({ attempt: recovered() }, '00000000-0000-0000-0000-000000000003')).toThrow();
  expect(() => ideCloneRecovery({ attempt: { ...recovered(), source_repository_id: destination } }, destination)).toThrow();
});

it.each(['../secret', '/secret', 'a//b', 'a/../b', '.git/config', '.gpthub-state', 'a\\b', 'a\n', null])('rejects unsafe path %s', (path) => {
  expect(idePath(path)).toBe(false);
});
it('does not turn absent or malformed repository data into an empty list', () => {
  expect(() => ideRepositoryPage({}, 0)).toThrow();
  expect(() => ideRepositoryPage({ items: [], next_offset: 0 }, 0)).toThrow();
  expect(ideRepositoryPage({ items: [], next_offset: null }, 0)).toEqual({ items: [], nextOffset: null });
});
it('keeps only bounded public repository fields', () => {
  const item = { repository_id: repo, name: 'Repo', state: 'registered', token: 'PRIVATE' };
  expect(ideRepositoryPage({ items: [item], next_offset: null }, 0).items).toEqual([{ repository_id: repo, name: 'Repo' }]);
  expect(() => ideRepositoryPage({ items: [item, item], next_offset: null }, 0)).toThrow();
});
it('requires the exact repository and runtime state', () => {
  expect(() => ideRuntime({ repository_id: 'other', workspace: { state: 'ready' } }, repo)).toThrow();
  expect(() => ideRuntime({ repository_id: repo, workspace: { state: 'constructor' } }, repo)).toThrow();
  expect(ideRuntime({ repository_id: repo, workspace: { state: 'not_created', expires_at: null, can_retry: false } }, repo).state).toBe('not_created');
});
it('projects bounded trees and rejects duplicate paths, partial contracts and wrong owners', () => {
  const value = { repository_id: repo, generation, entries: [row], truncated: false };
  expect(ideTree({ ...value, token: 'PRIVATE' }, repo)).toEqual({ entries: [row], generation, truncated: false });
  for (const change of [{ repository_id: 'other' }, { generation: '' }, { entries: [row, row] }, { entries: [{ ...row, incomplete: undefined }] }, { entries: [row], truncated: 1 }]) expect(() => ideTree({ ...value, ...change }, repo)).toThrow();
});
it('rejects files belonging to another selection/generation and never exposes private metadata', () => {
  const value = { repository_id: repo, generation, path: 'src/main.py', kind: 'text', size: 5, content: 'hello', digest: 'b'.repeat(64), truncated: false, token: 'PRIVATE' };
  expect(ideFile(value, repo, row.path, generation)).toEqual({ path: row.path, kind: 'text', size: 5, content: 'hello', digest: 'b'.repeat(64), truncated: false });
  for (const change of [{ path: 'another' }, { generation: 'c'.repeat(64) }, { repository_id: 'other' }, { content: null }]) expect(() => ideFile({ ...value, ...change }, repo, row.path, generation)).toThrow();
});
