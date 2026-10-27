import { presentTaskResult } from '@features/chat/model/taskResult';
import manifest from '@features/chat/model/protocolManifest.json';

const complete = {
  schema_version: 2, status: 'completed', verified: true, blocker: null,
  confirmed: ['source'], unchecked: [], references: [{ target: 'source.py' }],
};

it.each(manifest.task_result.v2.blockers)('uses a closed Russian reason for %s', blocker => {
  const result = presentTaskResult({
    schema_version: 2, status: 'blocked', verified: false, blocker, detail: 'PRIVATE_CONTEXT',
  });
  expect(result.status).toBe('blocked');
  expect(result.kind).toBe('info');
  expect(result.detail).toMatch(/[а-яё]/i);
  expect(result.detail).not.toMatch(/PRIVATE_CONTEXT|Автоматический запуск разрешён/);
  expect(result.detail).not.toBe('Обязательные результаты пока не подтверждены.');
});

it('keeps v1 readable without upgrading its partial outcome', () => {
  const result = presentTaskResult({ schema_version: 1, status: 'partial', verified: false, blocker: 'no_progress' });
  expect(result.status).toBe('partial');
  expect(result.title).toBe('Задача выполнена частично');
});

it('recognizes only a complete verified v2 result as completed', () => {
  expect(presentTaskResult(complete).kind).toBe('done');
  for (const invalid of [
    { verified: false }, { unchecked: ['missing'] }, { confirmed: [] }, { references: [] },
    { blocker: 'cost_unknown' }, { schema_version: 1 }, { schema_version: 99 },
  ]) {
    expect(presentTaskResult({ ...complete, ...invalid }).status).toBe('blocked');
  }
  expect(presentTaskResult()).toBeNull();
});

it.each(['PRIVATE_TOKEN', '__proto__', 'constructor', { secret: 'PRIVATE_TOKEN' }])(
  'never renders an unknown blocker %p or arbitrary diagnostic', blocker => {
    const value = presentTaskResult({ schema_version: 2, status: 'blocked', verified: false, blocker });
    expect(value.status).toBe('blocked');
    expect(value.detail).toBe('Обязательные результаты пока не подтверждены.');
  },
);
