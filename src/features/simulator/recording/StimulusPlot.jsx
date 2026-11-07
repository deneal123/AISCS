import React, { useMemo } from 'react';
import { Box, Text } from '@chakra-ui/react';

// This is the saved model waveform, sampled on the same clock as E1−REF.
export default function StimulusPlot({ time, values, timeMs, onTime }) {
  const shape = useMemo(() => {
    if (!Array.isArray(time) || !Array.isArray(values) || time.length < 2 || time.length !== values.length
      || !time.every(Number.isFinite) || !values.every(Number.isFinite)
      || time[0] !== 0 || time.at(-1) <= 0 || time.some((value, i) => i > 0 && value <= time[i - 1])) return null;
    const duration = time.at(-1), amplitude = Math.max(1, ...values.map(Math.abs));
    return { duration, amplitude, path: values.map((value, i) =>
      `${i ? 'L' : 'M'} ${(time[i] / duration * 1000).toFixed(3)} ${(25 - value / amplitude * 20).toFixed(3)}`).join(' ') };
  }, [time, values]);
  if (!shape) return null;
  return <Box display="flex" alignItems="center" mt={2}>
    <Text flex="0 0 58px" fontSize="10px" color="#8A90A2">Форма<br />STIM</Text>
    <Box flex="1" mr="14px" minW="0" role="slider" tabIndex={0} aria-label="Время на шкале стимула"
      aria-valuemin={0} aria-valuemax={shape.duration} aria-valuenow={Math.max(0, Math.min(shape.duration, timeMs))}
      aria-valuetext={`${timeMs.toFixed(1)} миллисекунд`} onKeyDown={event => {
        const step = shape.duration / 100;
        const target = event.key === 'Home' ? 0 : event.key === 'End' ? shape.duration
          : event.key === 'ArrowLeft' || event.key === 'ArrowDown' ? timeMs - step
            : event.key === 'ArrowRight' || event.key === 'ArrowUp' ? timeMs + step : null;
        if (target !== null) { event.preventDefault(); onTime(Math.max(0, Math.min(shape.duration, target))); }
      }}>
      <svg viewBox="0 0 1000 50" preserveAspectRatio="none" role="img" aria-label="Нормированная форма электрического стимула на общей временной шкале"
        style={{ width: '100%', height: 50, display: 'block', cursor: 'crosshair' }}
        onPointerDown={event => { const box = event.currentTarget.getBoundingClientRect();
          if (box.width > 0 && Number.isFinite(event.clientX)) onTime(Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)) * shape.duration); }}>
        <line x1="0" x2="1000" y1="25" y2="25" stroke="#596278" strokeOpacity=".5" vectorEffect="non-scaling-stroke" />
        <path d={shape.path} fill="none" stroke="#f7a45c" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        <line x1={Math.max(0, Math.min(1, timeMs / shape.duration)) * 1000} x2={Math.max(0, Math.min(1, timeMs / shape.duration)) * 1000}
          y1="2" y2="48" stroke="#e8eaf0" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      </svg>
    </Box>
  </Box>;
}
