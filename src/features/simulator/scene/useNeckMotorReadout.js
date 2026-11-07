import { useEffect, useState } from 'react';
import { loadNeckMotorReadout } from './neckMotor';

export default function useNeckMotorReadout(data) {
  const [result, setResult] = useState({ source: null, data: null, error: false });
  useEffect(() => {
    const controller = new AbortController();
    setResult({ source: data, data: null, error: false });
    if (data) loadNeckMotorReadout(data, controller.signal).then(value => {
      if (!controller.signal.aborted) setResult({ source: data, data: value, error: false });
    }).catch(() => {
      if (!controller.signal.aborted) setResult({ source: data, data: null, error: true });
    });
    return () => controller.abort();
  }, [data]);
  return result.source === data ? result : { data: null, error: false };
}
