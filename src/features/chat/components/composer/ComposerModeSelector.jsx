import React, { useEffect, useState } from 'react';
import { Button, Icon, Text, VisuallyHidden } from '@chakra-ui/react';
import { FiZap, FiGlobe, FiSearch, FiImage, FiMessageCircle, FiInfo } from '@shared/icons';
import ChoicePanel from '@shared/controls/ChoicePanel';
import ComposerModeOptions from './ComposerModeOptions';

export const CHAT_MODES = [
  { value: null, label: 'Авто', icon: FiZap, hint: 'Выбирает подходящий режим для каждой задачи.' },
  { value: 'web_search', label: 'Веб-поиск', icon: FiGlobe, hint: 'Актуальные сведения и ссылки на источники. С надбавкой за поиск.' },
  { value: 'deep_research', label: 'Deep Research', icon: FiSearch, hint: 'Подробное исследование нескольких источников. Дольше и дороже обычного ответа.' },
  { value: 'image_gen', label: 'Изображение', icon: FiImage, hint: 'Создаёт изображение по описанию. Надбавка за созданный файл.' },
  { value: 'general', label: 'Обычный', icon: FiMessageCircle, hint: 'Ответ без принудительного специализированного режима.' },
];

const PDF_HINTS = {
  web_search: 'Уточняет факты и находит источники для документа. Правки можно просмотреть перед применением.',
  deep_research: 'Исследует тему для открытого документа. Источники сохраняются вместе с результатом исследования.',
  image_gen: 'Создаёт иллюстрацию для документа. Для точных графиков нужны проверяемые данные.',
  general: 'Пишет и редактирует документ или выделенные блоки.',
};

export default function ComposerModeSelector({ value = null, onChange, mobileIconOnly = false, documentMode = false, multiIntentEnabled = false,
  onToggleMultiIntent, planningEnabled = false, onTogglePlanning }) {
  const legacy = ['pptx_gen', 'research_deck'].includes(value);
  const [details, setDetails] = useState(false);
  useEffect(() => { if (legacy) onChange?.(null); }, [legacy, onChange]);
  const current = CHAT_MODES.find((mode) => mode.value === value) || CHAT_MODES[0];
  const options = CHAT_MODES.map((mode) => ({ ...mode, value: mode.value ?? '',
    ...(documentMode ? {
      label: mode.value === 'general' ? 'Работа с текстом' : mode.label,
      hint: PDF_HINTS[mode.value] || 'Выбирает способ работы с открытым документом.',
    } : {}),
  }));
  return (
    <ChoicePanel label={`Режим: ${documentMode && value === 'general' ? 'Работа с текстом' : current.label}`} compactLabel={documentMode && value === 'general' ? 'Работа с текстом' : current.label} title={documentMode ? 'Работа с документом' : 'Режим ответа'}
      variant="mode-palette" mobileWidth={details ? 320 : 280}
      compactTitle={details ? undefined : <VisuallyHidden>{documentMode ? 'Работа с документом' : 'Режим ответа'}</VisuallyHidden>}
      icon={current.icon} mobileIconOnly={mobileIconOnly} selected={value != null} compactWidth={details ? 280 : 88} compactListHeight={264}
      headerAction={<Button size="document" variant="ghost" px={1} minW="32px" h="32px"
        aria-label={details ? 'Скрыть описания режимов' : 'Показать описания режимов'} aria-pressed={details}
        title={details ? 'Скрыть описания режимов' : 'Показать описания режимов'} onClick={() => setDetails((shown) => !shown)}><Icon as={FiInfo} boxSize={3.5} /></Button>}>
      {({ close, isMobile, compact, inputId }) => (
        <>
          {legacy && <Text role="status" fontSize="12px" p={2}>Презентации теперь создаются во вкладке PDF. Выбран режим Авто.</Text>}
          <ComposerModeOptions {...{ options, value, onChange, close, isMobile, compact, inputId, details,
            multiIntentEnabled, onToggleMultiIntent, planningEnabled, onTogglePlanning }} />
        </>
      )}
    </ChoicePanel>
  );
}
