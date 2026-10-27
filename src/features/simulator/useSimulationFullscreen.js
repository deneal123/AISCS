import { useEffect, useRef, useState } from 'react';

export default function useSimulationFullscreen(onError) {
  const root = useRef(null), error = useRef(onError);
  error.current = onError;
  const [active, setActive] = useState(false);
  useEffect(() => {
    const changed = () => setActive(Boolean(root.current && document.fullscreenElement === root.current));
    const key = event => {
      if (event.key === 'Escape' && root.current && document.fullscreenElement === root.current) {
        document.exitFullscreen().catch(() => error.current('Не удалось выйти из полноэкранного режима. Используйте кнопку выхода браузера.'));
      }
    };
    document.addEventListener('fullscreenchange', changed);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('fullscreenchange', changed); document.removeEventListener('keydown', key); };
  }, []);
  const toggle = async () => {
    try {
      if (root.current && document.fullscreenElement === root.current) await document.exitFullscreen();
      else if (root.current?.requestFullscreen) await root.current.requestFullscreen();
      else throw new Error('unsupported');
    } catch { error.current('Полноэкранный режим недоступен. Симулятор продолжает работать в окне.'); }
  };
  return { root, active, toggle };
}
