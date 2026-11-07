import React from 'react';
import { Text } from '@chakra-ui/react';

export default function DiscretizationNotice({ geometry }) {
  const valid = Number.isSafeInteger(geometry?.checked_events)
    && Number.isSafeInteger(geometry?.relocated_endpoints)
    && geometry.checked_events >= geometry.relocated_endpoints
    && geometry.relocated_endpoints >= 0
    && Number.isFinite(geometry?.max_shift_um)
    && geometry.max_shift_um >= 0;
  if (!valid) {
    return <Text>Синапсы на концах секций могут передаваться некорректно; сохранённый результат требует повторной проверки.</Text>;
  }
  return <Text>Уточнение сетки: проверено событий — {geometry.checked_events}, перенесено с концов секций — {geometry.relocated_endpoints}; максимальный сдвиг — {geometry.max_shift_um.toFixed(3)} мкм. Численная сходимость не подтверждена.</Text>;
}
