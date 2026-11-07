import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import StimulusPlot from '../../../src/features/simulator/recording/StimulusPlot';

test('displays both phases and seeks on the same time scale', () => {
  const onTime = jest.fn();
  const props = { time: [0, 1, 2, 3, 4], values: [0, 1, 0, -1, 0], timeMs: 1, onTime };
  const { rerender } = render(<StimulusPlot {...props} />);
  const plot = screen.getByRole('img', { name: /Нормированная форма электрического стимула/ });
  expect(plot.querySelector('path').getAttribute('d')).toContain('250.000 5.000');
  expect(plot.querySelector('path').getAttribute('d')).toContain('750.000 45.000');
  expect(plot.querySelectorAll('line')[1]).toHaveAttribute('x1', '250');
  plot.getBoundingClientRect = () => ({ left: 10, width: 100 });
  fireEvent(plot, new MouseEvent('pointerdown', { bubbles: true, clientX: 85 }));
  expect(onTime).toHaveBeenCalledWith(3);
  const slider = screen.getByRole('slider', { name: 'Время на шкале стимула' });
  fireEvent.keyDown(slider, { key: 'End' });
  expect(onTime).toHaveBeenLastCalledWith(4);
  fireEvent.keyDown(slider, { key: 'ArrowLeft' });
  expect(onTime).toHaveBeenLastCalledWith(.96);
  rerender(<StimulusPlot {...props} timeMs={2} />);
  expect(plot.querySelectorAll('line')[1]).toHaveAttribute('x1', '500');
});

test('does not invent a waveform from missing or invalid samples', () => {
  const { rerender } = render(<StimulusPlot time={[0, 1]} values={[0]} timeMs={0} onTime={() => {}} />);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  rerender(<StimulusPlot time={[0, 1]} values={[0, NaN]} timeMs={0} onTime={() => {}} />);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});
