import { resolveApiBaseUrl } from '@api/httpClient';

describe('resolveApiBaseUrl', () => {
  const originalApiBase = process.env.REACT_APP_API_BASE_URL;

  afterEach(() => {
    if (originalApiBase === undefined) delete process.env.REACT_APP_API_BASE_URL;
    else process.env.REACT_APP_API_BASE_URL = originalApiBase;
  });

  it('uses an explicitly configured API origin', () => {
    process.env.REACT_APP_API_BASE_URL = 'http://localhost:8000';

    expect(resolveApiBaseUrl()).toBe('http://localhost:8000');
  });

  it('uses same-origin when no API origin is configured', () => {
    delete process.env.REACT_APP_API_BASE_URL;

    expect(resolveApiBaseUrl()).toBe('/');
  });
});
