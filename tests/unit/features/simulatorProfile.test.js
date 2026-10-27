describe('application deployment profiles', () => {
  const previous = process.env.REACT_APP_APPLICATION_PROFILE;
  afterEach(() => { process.env.REACT_APP_APPLICATION_PROFILE = previous; jest.resetModules(); });
  test('simulation profile has an authenticated simulator and excludes chat/billing routes', () => {
    process.env.REACT_APP_APPLICATION_PROFILE = 'simulation'; jest.resetModules();
    const { ROUTE_CONFIG } = require('../../../src/app/router/routes');
    const simulator = ROUTE_CONFIG.find(route => route.path === '/simulator');
    expect(simulator.guard).toBe('auth-only');
    ['/chat', '/chat/:threadId', '/billing', '/pricing', '/admin', '/platform'].forEach(path => {
      expect(ROUTE_CONFIG.some(route => route.path === path)).toBe(false);
    });
    expect(ROUTE_CONFIG.find(route => route.path === '/').redirectTo).toBe('/simulator');
  });
  test('default profile preserves existing GPTHub routes', () => {
    delete process.env.REACT_APP_APPLICATION_PROFILE; jest.resetModules();
    const { ROUTE_CONFIG } = require('../../../src/app/router/routes');
    ['/chat', '/billing', '/pricing', '/simulator'].forEach(path => {
      expect(ROUTE_CONFIG.some(route => route.path === path)).toBe(true);
    });
  });
});
