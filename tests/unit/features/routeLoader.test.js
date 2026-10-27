import routeLoader from '../../../src/app/router/routeLoader';

it('passes successful route modules through without another load', async () => {
  const module = { default: () => null };
  const load = jest.fn().mockResolvedValue(module);
  await expect(routeLoader(load)()).resolves.toBe(module);
  expect(load).toHaveBeenCalledTimes(1);
});

it.each([
  () => Promise.reject(new Error('PRIVATE_ROUTE_FAILURE')),
  () => { throw new Error('PRIVATE_ROUTE_FAILURE'); },
])('bounds asynchronous and synchronous import failures without automatic retry', async (load) => {
  const call = jest.fn(load);
  await expect(routeLoader(call)()).rejects.toMatchObject({
    name: 'AppRouteLoadError', message: 'Страница временно недоступна.',
  });
  expect(call).toHaveBeenCalledTimes(1);
});

it('leaves unrelated runtime and compiler failures visible in the dev overlay', () => {
  const config = require('../../../craco.config');
  const dev = config.devServer({ client: { overlay: { errors: true, warnings: false } } });
  expect(dev.client.overlay.errors).toBe(true);
  expect(dev.client.overlay.runtimeErrors({ name: 'AppRouteLoadError' })).toBe(false);
  expect(dev.client.overlay.runtimeErrors({ name: 'ChunkLoadError' })).toBe(true);
  expect(dev.client.overlay.runtimeErrors(new Error('synthetic unexpected error'))).toBe(true);
});

it('uses the browser-facing port for dev hot reload unless an explicit socket port is configured', () => {
  const config = require('../../../craco.config');
  expect(config.devServer({ client: { webSocketURL: {} } }).client.webSocketURL.port).toBe('0');
  expect(config.devServer({ client: { webSocketURL: {} } }).client.webSocketURL.protocol).toBeUndefined();
  const explicit = config.devServer({ client: { webSocketURL: { hostname: 'dev.example.test', port: '8443', pathname: '/reload' } } });
  expect(explicit.client.webSocketURL).toMatchObject({ hostname: 'dev.example.test', port: '8443', pathname: '/reload' });
});
