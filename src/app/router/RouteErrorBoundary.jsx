import React from 'react';
import { ErrorFallback } from '@shared/ui/molecules/ErrorBoundary';

/** Eager fallback: recovery must not depend on another lazy route chunk. */
export default function RouteErrorBoundary() {
  return <ErrorFallback
    onReload={() => window.location.reload()}
    description="Страница временно недоступна. Обновите интерфейс или вернитесь на главную. Несохранённые правки могут быть потеряны при обновлении."
  />;
}
