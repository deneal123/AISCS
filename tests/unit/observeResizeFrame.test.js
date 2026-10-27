import { observeResizeFrame } from '../../src/shared/utils/observeResizeFrame';

describe('frame-owned resize delivery', () => {
  let notify;
  let frames;
  let disconnect;
  const originalObserver = global.ResizeObserver;
  beforeEach(() => {
    frames = [];
    disconnect = jest.fn();
    global.ResizeObserver = jest.fn(callback => {
      notify = callback;
      return { observe: jest.fn(), disconnect };
    });
    jest.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => {
      frames.push(callback); return frames.length;
    });
    jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
  });
  afterEach(() => {
    global.ResizeObserver = originalObserver;
    jest.restoreAllMocks();
  });
  it('never writes during observer delivery and coalesces the latest dimensions', () => {
    const fit = jest.fn();
    const stop = observeResizeFrame(document.createElement('textarea'), fit);
    notify([{ contentRect: { width: 400 } }]);
    notify([{ contentRect: { width: 300 } }]);
    expect(fit).not.toHaveBeenCalled();
    expect(frames).toHaveLength(1);
    frames[0]();
    expect(fit).toHaveBeenCalledTimes(1);
    expect(fit).toHaveBeenCalledWith([{ contentRect: { width: 300 } }]);
    stop();
  });
  it('cancels a pending layout update when its surface closes', () => {
    const fit = jest.fn();
    const stop = observeResizeFrame(document.createElement('textarea'), fit);
    notify([]);
    stop();
    expect(disconnect).toHaveBeenCalledTimes(1);
    expect(window.cancelAnimationFrame).toHaveBeenCalledWith(1);
    frames[0]();
    notify([]);
    expect(fit).not.toHaveBeenCalled();
    expect(frames).toHaveLength(1);
  });
});
