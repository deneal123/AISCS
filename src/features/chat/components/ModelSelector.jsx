import React, { useMemo, useState } from 'react';
import { Box, Button, HStack, Icon, Text, VStack } from '@chakra-ui/react';
import { FiCheck, FiCpu, FiInfo } from '@shared/icons';
import AppSelect from '@shared/controls/AppSelect';
import ChoicePanel from '@shared/controls/ChoicePanel';
import AppLoading from '@shared/controls/AppLoading';
import { colors } from '@theme/tokens';
import { parseModelMeta, resolveModelTriggerLabel, sortModelsByProvider } from '../utils/modelSelector';
import ModelOptionBadges, { modelBadges } from './ModelOptionBadges';

const BATCH = 60;
const CAP_LABELS = { vision: 'Изображения на входе', audio: 'Аудио', files: 'Файлы', image_out: 'Создание изображений', tools: 'Инструменты' };

function contextLabel(info) {
  if (!Number.isFinite(info?.context_window) || info.context_window <= 0) return '';
  const tokens = new Intl.NumberFormat('ru-RU', { notation: 'compact' }).format(info.context_window);
  return `${info.context_estimated ? '≈ ' : ''}${tokens} токенов${info.context_estimated ? ' · оценка' : ''}`;
}

export default function ModelSelector({ selectedModel, availableModels = [], catalog = {}, onChange,
  modelStatus = 'ready', onRetry, mobileIconOnly = false }) {
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(BATCH);
  const [details, setDetails] = useState(false);
  const [keyboardHints, setKeyboardHints] = useState(false);
  const models = useMemo(() => sortModelsByProvider(availableModels), [availableModels]);
  const filtered = useMemo(() => models.filter((id) => {
    const meta = parseModelMeta(id);
    return `${id} ${meta.providerLabel || ''} ${meta.label}`.toLocaleLowerCase('ru-RU').includes(query.trim().toLocaleLowerCase('ru-RU'));
  }), [models, query]);
  const unavailable = modelStatus === 'ready' && selectedModel && !models.includes(selectedModel);
  const options = useMemo(() => {
    const groups = new Map();
    filtered.slice(0, limit).forEach((id) => {
      const meta = parseModelMeta(id);
      const provider = meta.providerLabel || 'Другие модели';
      if (!groups.has(provider)) groups.set(provider, { label: provider, options: [] });
      groups.get(provider).options.push({ value: id, label: meta.label, info: catalog[id],
        hint: catalog[id]?.is_free === true ? 'Без списания кредитов за токены. Платные инструменты учитываются отдельно.' : undefined,
        invitation: meta.provider === 'local' && catalog[id]?.is_free === true });
    });
    const local = groups.get('Локальная модель');
    groups.delete('Локальная модель');
    return [...(local ? [local] : []), { label: 'Автоматический выбор', options: [{ value: '', label: 'Авто', hint: 'Система выбирает модель под задачу.' }] }, ...groups.values()];
  }, [filtered, limit, catalog]);

  return (
    <ChoicePanel label={`Модель: ${selectedModel ? resolveModelTriggerLabel(selectedModel) : 'Авто'}`}
      title="Модель ответа" mobileIcon={FiCpu} mobileIconOnly={mobileIconOnly}
      selected={!!selectedModel} width={384} compactWidth={details ? 320 : 256} placement="top-end"
      variant="model-palette" mobileWidth={details || !mobileIconOnly ? 320 : 280}
      headerAction={<Button size="document" variant="ghost" px={1} minW="32px" h="32px" aria-label={details ? 'Скрыть описания моделей' : 'Показать описания моделей'} aria-pressed={details}
        onClick={() => setDetails(shown => !shown)}><Icon as={FiInfo} boxSize={3.5} /></Button>}>
      {({ close, isMobile, compact, inputId }) => (
        <>
          {selectedModel && !compact && <Text px={2} mb={2} fontSize="12px" color={colors.fg[3]}>Выбрана: {resolveModelTriggerLabel(selectedModel)}</Text>}
          {modelStatus === 'loading' && <AppLoading label="Загружаю модели…" />}
          {modelStatus === 'error' && <Box px={2} mb={2}><Text fontSize="12px">Каталог временно недоступен. Ваш выбор сохранён.</Text>
            {onRetry && <Button size="sm" mt={2} onClick={onRetry}>Повторить загрузку</Button>}</Box>}
          {modelStatus === 'ready' && !models.length && <Text px={2} mb={2} fontSize="12px">Нет доступных моделей.</Text>}
          {unavailable && <Text px={2} mb={2} fontSize="12px" color={colors.warning}>Выбранная модель недоступна. Выберите другую или Авто.</Text>}
          <Box onKeyDownCapture={event => { if (['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) setKeyboardHints(true); }}
            onPointerMoveCapture={() => setKeyboardHints(false)} onBlurCapture={() => setKeyboardHints(false)}>
          <AppSelect presentation={compact ? 'composer-compact' : 'composer'} inputId={inputId} ariaLabel="Поиск модели" value={selectedModel || ''}
            options={options} isSearchable placeholder={compact ? 'Найти модель…' : 'Поиск модели или провайдера…'}
            showOptionHints={compact && !details && keyboardHints}
            getOptionHint={option => compact && !details && option ? [option.hint, ...modelBadges(option.info, contextLabel(option.info)).map(badge => badge.label)].filter(Boolean).join(' · ') : null}
            autoFocus={!isMobile} size={isMobile ? 'touch' : 'sm'} onClose={close} inputValue={query}
            onInputChange={(next, action) => {
              if (action.action === 'input-change') { setQuery(next); setLimit(BATCH); }
            }}
            noOptionsMessage="Ничего не найдено"
            onChange={(next) => { onChange?.(next); setQuery(''); setLimit(BATCH); close(); }}
            formatOptionLabel={(option) => compact && !details ? (
              <HStack spacing={2} w="100%" minW={0} align="center">
                <Text flex={1} minW={0} fontWeight={600} fontSize="12px" noOfLines={1} title={option.label}>{option.label}</Text>
                <ModelOptionBadges badges={modelBadges(option.info, contextLabel(option.info))} />
                <Box w={3} flexShrink={0}>{option.value === (selectedModel || '') && <Icon as={FiCheck} boxSize={3} color={colors.blue[100]} />}</Box>
              </HStack>
            ) : (
              <HStack align="start" spacing={3} w="100%">
                <VStack flex={1} minW={0} align="stretch" spacing={1}>
                  <Text fontWeight={600} fontSize={compact ? '12px' : '13px'} overflowWrap="anywhere">{option.label}</Text>
                  {option.hint && (!compact || details) && <Text fontSize="12px" color={colors.fg[3]}>{option.hint}</Text>}
                  {option.info && <>
                    <HStack flexWrap="wrap" spacing={2} fontSize="11px">
                      {contextLabel(option.info) && (!compact || details) && <Text color={colors.fg[3]}>{contextLabel(option.info)}</Text>}
                      {option.info.is_free === true && <Text color={colors.success}>Бесплатно</Text>}
                      {option.info.is_free !== true && option.info.cost_tier === 0 && <Text color={colors.success}>Экономная</Text>}
                      {option.info.cost_tier === 2 && <Text color={colors.warning}>Повышенная стоимость</Text>}
                    </HStack>
                    {Array.isArray(option.info.capabilities) && (!compact || details) && <Text fontSize="11px" color={colors.fg[3]}>
                      {option.info.capabilities.filter((capability) => typeof capability === 'string' && Object.hasOwn(CAP_LABELS, capability)).map((capability) => CAP_LABELS[capability]).join(' · ')}
                    </Text>}
                  </>}
                </VStack>
                {option.value === (selectedModel || '') && <Icon as={FiCheck} mt={1} color={colors.blue[100]} />}
              </HStack>
            )} />
          </Box>
          {filtered.length > limit && <Button size="sm" variant="ghost" w="100%" mt={2}
            onClick={() => setLimit((previous) => previous + BATCH)}>Показать ещё · {filtered.length - limit}</Button>}
          {query && !filtered.length && <Text px={2} fontSize="12px" color={colors.fg[3]} mt={2}>Ничего не найдено. Измените или очистите поиск.</Text>}
        </>
      )}
    </ChoicePanel>
  );
}
