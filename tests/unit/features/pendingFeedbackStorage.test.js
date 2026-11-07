import { clearPendingFeedback, readPendingFeedback, readSelectedFeedbackSource,
  writePendingFeedback, writeSelectedFeedbackSource } from '../../../src/features/simulator/recording/pendingFeedbackStorage';

const scene = '93a6be54-9021-4b67-b00b-b799240f7fce';
const source = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
const request = 'fba50b24-f408-4d70-bd9b-3f0e18f76412';

beforeEach(() => sessionStorage.clear());

test('round-trips only the identifiers needed for the same scene and preserves newer receipts', () => {
  const receipt = { version: 1, sourceId: source, requestId: request, ignored: 'not saved' };
  expect(writePendingFeedback(sessionStorage, scene, receipt)).toBe(true);
  expect(readPendingFeedback(sessionStorage, scene)).toEqual({ version: 1, sourceId: source, requestId: request });
  expect(readPendingFeedback(sessionStorage, request)).toBeNull();
  expect(clearPendingFeedback(sessionStorage, scene, request)).toBe(false);
  expect(readPendingFeedback(sessionStorage, scene)).not.toBeNull();
  expect(clearPendingFeedback(sessionStorage, scene, source)).toBe(true);
  expect(readPendingFeedback(sessionStorage, scene)).toBeNull();
});

test('rejects malformed data and handles disabled browser storage without throwing', () => {
  sessionStorage.setItem(`simulation:pending-feedback:${scene}`, '{bad');
  expect(readPendingFeedback(sessionStorage, scene)).toBeNull();
  expect(writePendingFeedback(sessionStorage, scene, { version: 1, sourceId: 'x', requestId: request })).toBe(false);
  const disabled = { getItem: () => { throw Error('disabled'); }, setItem: () => { throw Error('disabled'); } };
  expect(readPendingFeedback(disabled, scene)).toBeNull();
  expect(writePendingFeedback(disabled, scene, { version: 1, sourceId: source, requestId: request })).toBe(false);
});

test('preserves retry identity without accepting malformed retry flags', () => {
  expect(writePendingFeedback(sessionStorage, scene, { version: 1, sourceId: source, requestId: request, retry: true })).toBe(true);
  expect(readPendingFeedback(sessionStorage, scene)).toEqual({ version: 1, sourceId: source, requestId: request, retry: true });
  expect(writePendingFeedback(sessionStorage, scene, { version: 1, sourceId: source, requestId: request, retry: 'yes' })).toBe(false);
});

test('persists only the selected source for its scene and tolerates blocked storage', () => {
  expect(writeSelectedFeedbackSource(sessionStorage, scene, source)).toBe(true);
  expect(readSelectedFeedbackSource(sessionStorage, scene)).toBe(source);
  expect(readSelectedFeedbackSource(sessionStorage, request)).toBeNull();
  expect(writeSelectedFeedbackSource(sessionStorage, scene, 'invalid')).toBe(false);
  const blocked = { getItem: () => { throw Error('disabled'); }, setItem: () => { throw Error('disabled'); } };
  expect(readSelectedFeedbackSource(blocked, scene)).toBeNull();
  expect(writeSelectedFeedbackSource(blocked, scene, source)).toBe(false);
});
