const { EventEmitter } = require('events');
const { collectLiveWorkTimings } = require('../e2e/helpers/liveWorkTimings');

describe('private live Work timings', () => {
  it('records bounded timing categories without request details', () => {
    const page = new EventEmitter();
    let now = 100;
    const stop = collectLiveWorkTimings(page, () => now);
    const request = {
      url: () => 'http://user:secret@localhost/api/chats/private-thread/work?token=private-token',
      resourceType: () => 'xhr',
      headers: () => ({ Cookie: 'secret-cookie' }),
      postData: () => 'private-content',
    };
    page.emit('request', request);
    now = 380;
    page.emit('response', { request: () => request, status: () => 200 });
    page.emit('requestfinished', request);
    const result = stop();
    expect(result).toEqual({ samples: [{ category: 'work_snapshot', outcome: 'completed', status: 200, elapsed_ms: 280 }], incomplete_count: 0, incomplete_by_category: {}, dropped: 0 });
    expect(JSON.stringify(result)).not.toMatch(/secret|private|http|Cookie|token/);
    expect(page.listenerCount('request')).toBe(0);
  });

  it('bounds inventory and drops raw network failures', () => {
    const page = new EventEmitter();
    const stop = collectLiveWorkTimings(page, () => 1);
    for (let index = 0; index < 258; index += 1) {
      const request = { url: () => 'http://localhost/api/profile/me', resourceType: () => 'xhr', failure: () => ({ errorText: 'secret-body' }) };
      page.emit('request', request);
      page.emit('requestfailed', request);
    }
    const result = stop();
    expect(result.samples).toHaveLength(256);
    expect(result.dropped).toBe(2);
    expect(result.samples[0]).toEqual({ category: 'profile', outcome: 'transport_failed', status: 0, elapsed_ms: 0 });
    expect(JSON.stringify(result)).not.toContain('secret-body');
  });

  it('reports only safe categories for requests still pending at teardown', () => {
    const page = new EventEmitter();
    const stop = collectLiveWorkTimings(page, () => 1);
    page.emit('request', { url: () => 'http://user:secret@localhost/private-chunk.js?token=private', resourceType: () => 'script' });
    page.emit('request', { url: () => 'http://localhost/api/chats/private-thread/work', resourceType: () => 'xhr' });
    const result = stop();
    expect(result.incomplete_count).toBe(2);
    expect(result.incomplete_by_category).toEqual({ javascript: 1, work_snapshot: 1 });
    expect(JSON.stringify(result)).not.toMatch(/secret|private|http|token/);
    expect(page.listenerCount('request')).toBe(0);
  });
});
