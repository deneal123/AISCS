const { safeLiveRequest } = require('../e2e/helpers/safeLiveRequest');

describe('live browser transport diagnostics', () => {
  it('preserves successful responses without replaying the request', async () => {
    const response = { status: 200 };
    const invoke = jest.fn().mockResolvedValue(response);
    expect(await safeLiveRequest('create_thread', invoke)).toBe(response);
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it.each(['create_thread', 'delete_thread', 'delete_file', 'read_file', 'write_response', 'unknown'])
  ('does not retain transport cookies, payload or exception cause: %s', async (operation) => {
    const marker = 'PRIVATE_TRANSPORT_SENTINEL';
    const original = new Error(`cookie: auth_token=${marker}; raw body ${marker}`);
    const invoke = jest.fn().mockRejectedValue(original);
    const failure = await safeLiveRequest(operation, invoke).catch((error) => error);
    expect(failure).not.toBe(original);
    expect(failure.message).toMatch(/^live_[a-z_]+_unavailable$/);
    expect(failure.stack).not.toContain(marker);
    expect(failure.cause).toBeUndefined();
    expect(invoke).toHaveBeenCalledTimes(1);
  });
});
