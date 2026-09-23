import { useEffect } from 'react';

const PRODUCT_NAME = 'GPTHub';

export default function useDocumentTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} — ${PRODUCT_NAME}` : PRODUCT_NAME;
  }, [title]);
}
