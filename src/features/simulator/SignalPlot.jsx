import React, { useEffect, useId, useMemo, useRef } from 'react';
import { VisuallyHidden } from '@chakra-ui/react';
import { responseSeries } from './sceneModel';
import { SIMULATION_TRACES } from './theme';

// Trace geometry is cached; playback redraws only the shared time cursor.
export default function SignalPlot({ preview, timeMs, onTime, comparison, showResponse = false, modelVisualization, primaryColor = SIMULATION_TRACES.current }) {
  const ref = useRef(null), drawCursor = useRef(null), currentTime = useRef(timeMs);
  const descriptionId = useId();
  currentTime.current = timeMs;
  const series = useMemo(() => responseSeries(preview, modelVisualization), [preview, modelVisualization]);
  const heightPx = showResponse ? 184 : 104, left = showResponse ? 110 : 58;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return undefined;
    const background = document.createElement('canvas');
    const draw = () => {
      const { width, height } = canvas.getBoundingClientRect();
      if (width < left + 15 || height < 1) return;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      [canvas, background].forEach(target => { target.width = width * ratio; target.height = height * ratio; });
      const ctx = background.getContext('2d');
      if (!ctx) return;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      const right = width - 14, top = showResponse ? 100 : 12, bottom = height - 24;
      const times = preview?.time_ms || [], signal = preview?.signal_uv || [], compare = comparison?.signal_uv || [];
      const duration = times.at(-1) || 200;
      const xAt = time => left + time / duration * (right - left);
      const amplitude = Math.max(.1, ...signal.map(Math.abs), ...compare.map(Math.abs));
      canvas.dataset.signalHalfRangeUv = amplitude.toPrecision(9);
      ctx.font = '11px Inter, sans-serif'; ctx.textBaseline = 'middle';
      const label = (text, x, y) => { ctx.fillStyle = '#8A90A2'; ctx.fillText(text, x, y); };
      const horizontal = y => {
        ctx.strokeStyle = 'rgba(138,144,162,.18)'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
      };
      const trace = (t, values, color, first, last, scale) => {
        if (!values.length) return;
        ctx.strokeStyle = color; ctx.lineWidth = 1.1; ctx.beginPath();
        values.forEach((value, i) => {
          const x = xAt(t[i]), y = last - value / scale * (last - first);
          if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
        });
        ctx.stroke();
      };
      if (showResponse) {
        label(preview?.connectome ? 'Проекция Δg' : comparison ? 'Вход B Δg' : 'Вход Δg', 3, 12); label('мкСм', 3, 25); horizontal(28);
        if (series.inputEvents === null) label('Журнал входа не сохранён', left + 4, 17);
        else {
          label(series.maxInputWeightUs.toFixed(3), 71, 12);
          ctx.strokeStyle = '#EAA064'; ctx.lineWidth = 1.4;
          series.inputEvents.forEach(event => {
            const y = 28 - event.weight_us / series.maxInputWeightUs * 20;
            ctx.beginPath(); ctx.moveTo(xAt(event.time_ms), 28); ctx.lineTo(xAt(event.time_ms), y); ctx.stroke();
          });
        }
        label(preview?.connectome ? 'Спайки ЦНС' : comparison ? 'Спайки B' : 'Спайки', 3, 47); label(preview?.connectome ? 'событий / мс' : 'клетки 1–6', 3, 60); horizontal(64);
        ctx.strokeStyle = '#46D5AA'; ctx.lineWidth = 1.2;
        (preview?.connectome ? [] : preview?.spikes || []).forEach(event => {
          const y = 43 + event.cell_id * 3;
          ctx.beginPath(); ctx.moveTo(xAt(event.time_ms), y - 1.3); ctx.lineTo(xAt(event.time_ms), y + 1.3); ctx.stroke();
        });
        const histogram = preview?.connectome?.spikes_by_ms;
        if (preview?.connectome && !histogram) label('Журнал ЦНС — в файле опыта', left + 4, 48);
        if (histogram) {
          const maximum = Math.max(1, ...histogram);
          histogram.forEach((count, time) => {
            if (!count) return;
            ctx.beginPath(); ctx.moveTo(xAt(time), 64); ctx.lineTo(xAt(time), 64 - count / maximum * 24); ctx.stroke();
          });
        }
        label(comparison ? 'Лапки B, °' : 'Лапки, °', 3, 78); label('условно', 3, 91); horizontal(92);
        label(series.maxMotionDegrees.toFixed(1), 77, 76);
        trace(times, series.motionDegrees, '#C3CCD9', 72, 92, series.maxMotionDegrees);
      }
      for (const fraction of [0, .5, 1]) {
        const y = top + (bottom - top) * fraction;
        horizontal(y);
        label((amplitude * (1 - fraction * 2)).toFixed(2), showResponse ? 70 : 3, y);
      }
      if (showResponse) { label('E1 − REF', 3, 121); label('мкВ', 3, 135); }
      else label('мкВ', 3, height - 9);
      trace(times, signal.map(value => value + amplitude), primaryColor, top, bottom, amplitude * 2);
      trace(comparison?.time_ms || [], compare.map(value => value + amplitude), SIMULATION_TRACES.reference, top, bottom, amplitude * 2);
      [0, .5, 1].forEach(fraction => label(`${(duration * fraction).toFixed(0)} мс`,
        fraction === 1 ? right - 38 : xAt(duration * fraction) - 8, height - 9));
      drawCursor.current = time => {
        const target = canvas.getContext('2d');
        if (!target) return;
        target.setTransform(ratio, 0, 0, ratio, 0, 0); target.clearRect(0, 0, width, height);
        target.drawImage(background, 0, 0, width, height);
        if (!preview) return;
        target.strokeStyle = '#E8EAF0'; target.lineWidth = 1;
        target.beginPath(); target.moveTo(xAt(time), showResponse ? 5 : top); target.lineTo(xAt(time), bottom); target.stroke();
      };
      drawCursor.current(currentTime.current);
    };
    const observer = new ResizeObserver(draw); observer.observe(canvas); draw();
    return () => { observer.disconnect(); drawCursor.current = null; };
  }, [preview, comparison, series, showResponse, left, primaryColor]);
  useEffect(() => { drawCursor.current?.(timeMs); }, [timeMs]);

  return <><canvas ref={ref} role="img" style={{ width: '100%', height: `${heightPx}px`, display: 'block' }}
    data-model-time-ms={Number(timeMs).toFixed(3)} data-input-journal={series.inputEvents === null ? 'missing' : 'recorded'}
    data-reference-run={comparison?.run_id || ''} data-current-samples={preview?.time_ms?.length || 0}
    aria-describedby={showResponse ? descriptionId : undefined}
    aria-label={showResponse ? 'Общая временная шкала: синаптический вход, спайки, условное движение лапок и запись E1 относительно REF' : 'Запись разности потенциалов E1 относительно REF, микровольты'}
    onPointerDown={event => {
      const box = event.currentTarget.getBoundingClientRect();
      const fraction = Math.max(0, Math.min(1, (event.clientX - box.left - left) / (box.width - left - 14)));
      onTime(fraction * (preview?.time_ms?.at(-1) || 200));
    }} />{showResponse && <VisuallyHidden id={descriptionId}>События входа заданы в микросименсах; движение лапок — условная визуализация.{comparison ? ' Вход, спайки и движение относятся к выбранному опыту B; записи E1−REF A и B показаны на общей шкале.' : ''}{series.inputEvents === null ? ' Журнал входа этого опыта не сохранён.' : ''}</VisuallyHidden>}</>;
}
