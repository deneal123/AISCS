import { useEffect } from 'react';
import { SIMULATION_PROFILE } from '@shared/config/applicationProfile';

const PRODUCT_NAME = 'GPTHub';

export default function useDocumentTitle(title) {
  useEffect(() => {
    document.title = SIMULATION_PROFILE ? (title || 'Симулятор') : (title ? `${title} — ${PRODUCT_NAME}` : PRODUCT_NAME);
  }, [title]);
}
