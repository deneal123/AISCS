const { ensureNativeDevRoutes } = require('../e2e/helpers/nativeAndroid');

it('настраивает только отсутствующие dev-порты через no-rebind', () => {
  const run = jest.fn(() => '');
  ensureNativeDevRoutes(run);
  expect(run.mock.calls).toEqual([
    ['reverse', '--list'],
    ['reverse', '--no-rebind', 'tcp:3001', 'tcp:3001'],
    ['reverse', '--no-rebind', 'tcp:8001', 'tcp:8001'],
  ]);
});

it('повтор не изменяет уже правильные маршруты', () => {
  const run = jest.fn(() => 'host-serial tcp:3001 tcp:3001\r\nhost-serial tcp:8001 tcp:8001\r\n');
  ensureNativeDevRoutes(run);
  expect(run).toHaveBeenCalledTimes(1);
});

it('чужое назначение блокирует замену существующего маршрута', () => {
  const run = jest.fn(() => 'host-serial tcp:3001 tcp:9000');
  expect(() => ensureNativeDevRoutes(run)).toThrow('уже принадлежит другому назначению');
  expect(run).toHaveBeenCalledTimes(1);
});

it('конфликт второго порта обнаруживается до любой записи первого', () => {
  const run = jest.fn(() => 'host-serial tcp:8001 tcp:9000');
  expect(() => ensureNativeDevRoutes(run)).toThrow('уже принадлежит другому назначению');
  expect(run).toHaveBeenCalledTimes(1);
});
