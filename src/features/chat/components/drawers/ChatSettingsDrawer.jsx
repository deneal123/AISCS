import { useEffect, useRef, useState } from 'react';
import {
  Box,
  Button,
  Divider,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerHeader,
  DrawerOverlay,
  HStack,
  Icon,
  Switch,
  Text,
  VStack,
} from '@chakra-ui/react';
import { FiAlertTriangle, FiCloud, FiCpu, FiDatabase, FiEye, FiGitBranch, FiLayers, FiMic, FiRotateCcw, FiSearch, FiSettings, FiZap } from '@shared/icons';
import { colors, borderRadius, shadows } from '@theme/tokens';
import { DRAWER_CLOSE_BUTTON_PROPS, DRAWER_OVERLAY_PROPS, DRAWER_RADIAL_BG, DRAWER_CONTENT_BG } from '@theme/drawer';
import { CHAT_SCROLLBAR_SX, CHAT_THEME } from '../../constants/theme';
import StyledSelect from '../StyledSelect';

const IRIS = colors.iris[300];

const SWITCH_SX = {
  '& .chakra-switch__track[data-checked]': {
    background: colors.accent.base,
  },
  '& .chakra-switch__track:not([data-checked])': {
    background: colors.border.medium,
  },
  '& .chakra-switch__track:focus, & .chakra-switch__track[data-focus]': {
    boxShadow: `0 0 0 3px ${colors.accent.glow}`,
  },
};

function SettingsSection({ icon, title, rows }) {
  return (
    <VStack align="stretch" spacing={2.5}>
      <HStack spacing={2} px={1}>
        <Icon as={icon} boxSize={3.5} color={CHAT_THEME.textTertiary} />
        <Text fontSize="10.5px" fontWeight="700" color={CHAT_THEME.textTertiary} textTransform="uppercase" letterSpacing="0.09em">
          {title}
        </Text>
      </HStack>
      <Box
        borderRadius={borderRadius.md}
        bg={colors.surface.tint2}
        border={`1px solid ${CHAT_THEME.panelBorder}`}
        overflow="hidden"
      >
        {rows.map((row, i, arr) => (
          <HStack
            key={row.key}
            justify="space-between"
            px={4}
            py={3.5}
            spacing={3}
            borderBottom={i < arr.length - 1 ? `1px solid ${CHAT_THEME.panelBorder}` : 'none'}
            transition="background 0.15s"
            _hover={{ bg: colors.surface.tint1 }}
          >
            <HStack spacing={3} align="center" flex="1" minW="0">
              <Box
                w="32px"
                h="32px"
                borderRadius={borderRadius.sm}
                display="flex"
                alignItems="center"
                justifyContent="center"
                bg={row.checked ? CHAT_THEME.accentSoft : colors.border.faint}
                border={`1px solid ${row.checked ? colors.accent.subtleBorder : CHAT_THEME.panelBorder}`}
                flexShrink={0}
                transition="all 0.2s"
              >
                <Icon as={row.icon} boxSize={3.5} color={row.checked ? IRIS : CHAT_THEME.textTertiary} />
              </Box>
              <VStack align="start" spacing={0} minW="0">
                <Text fontSize="13px" fontWeight="600" color={CHAT_THEME.textPrimary} letterSpacing="-0.005em">
                  {row.title}
                </Text>
                <Text fontSize="11.5px" fontWeight="500" color={CHAT_THEME.textSecondary} noOfLines={1}>
                  {row.desc}
                </Text>
              </VStack>
            </HStack>
            <Switch isChecked={row.checked} onChange={row.onChange} size="md" sx={SWITCH_SX} />
          </HStack>
        ))}
      </Box>
    </VStack>
  );
}

/**
 * Секция «Транскрипция голоса»: сегментированный переключатель режима
 * (Локально whisper.cpp | Провайдер) + компактный выбор локальной модели.
 * «Локально» отключается, когда сервер не поддерживает on-device whisper
 * (config.local_enabled === false) — тогда эффективный режим всегда «провайдер».
 */
function TranscriptionSection({ config, mode, model, onModeChange, onModelChange }) {
  const localEnabled = !!config?.local_enabled;
  const models = Array.isArray(config?.models) ? config.models : [];
  const defaultModel = config?.default_model || '';
  // «Локально» доступно только при серверной поддержке — иначе показываем «провайдер».
  const effectiveMode = mode === 'local' && localEnabled ? 'local' : 'provider';

  const modeOptions = [
    { value: 'local', label: 'Локально', icon: FiCpu, disabled: !localEnabled },
    { value: 'provider', label: 'Провайдер', icon: FiCloud, disabled: false },
  ];

  return (
    <VStack align="stretch" spacing={2.5}>
      <HStack spacing={2} px={1}>
        <Icon as={FiMic} boxSize={3.5} color={CHAT_THEME.textTertiary} />
        <Text fontSize="10.5px" fontWeight="700" color={CHAT_THEME.textTertiary} textTransform="uppercase" letterSpacing="0.09em">
          Транскрипция голоса
        </Text>
      </HStack>
      <Box
        borderRadius={borderRadius.md}
        bg={colors.surface.tint2}
        border={`1px solid ${CHAT_THEME.panelBorder}`}
        overflow="hidden"
      >
        <Box px={4} py={3.5} borderBottom={effectiveMode === 'local' ? `1px solid ${CHAT_THEME.panelBorder}` : 'none'}>
          <HStack
            spacing={1}
            p={1}
            borderRadius={borderRadius.sm}
            bg={colors.border.faint}
            border={`1px solid ${CHAT_THEME.panelBorder}`}
          >
            {modeOptions.map((opt) => {
              const active = effectiveMode === opt.value;
              return (
                <Button
                  key={opt.value}
                  flex="1"
                  h="34px"
                  minW="0"
                  variant="unstyled"
                  isDisabled={opt.disabled}
                  onClick={() => onModeChange(opt.value)}
                  borderRadius={borderRadius.sm}
                  fontSize="12.5px"
                  fontWeight="600"
                  display="flex"
                  alignItems="center"
                  justifyContent="center"
                  color={active ? IRIS : CHAT_THEME.textSecondary}
                  bg={active ? CHAT_THEME.accentSoft : 'transparent'}
                  border={`1px solid ${active ? colors.accent.subtleBorder : 'transparent'}`}
                  _hover={opt.disabled ? {} : { color: CHAT_THEME.textPrimary, bg: active ? CHAT_THEME.accentSoft : CHAT_THEME.panelHover }}
                  _disabled={{ opacity: 0.4, cursor: 'not-allowed' }}
                >
                  <Icon as={opt.icon} boxSize="13px" mr={1.5} />
                  {opt.label}
                </Button>
              );
            })}
          </HStack>
          <Text fontSize="11px" color={CHAT_THEME.textTertiary} fontWeight="500" mt={2.5} lineHeight="1.45">
            {effectiveMode === 'local'
              ? 'Распознавание на устройстве сервера (whisper.cpp) — приватно, без обращения к внешним провайдерам.'
              : localEnabled
                ? 'Распознавание речи через облачного провайдера.'
                : 'Локальное распознавание недоступно на сервере — используется провайдер.'}
          </Text>
        </Box>

        {effectiveMode === 'local' && (
          <Box px={4} py={3.5}>
            <Text fontSize="12px" fontWeight="600" color={CHAT_THEME.textSecondary} mb={2}>
              Модель whisper
            </Text>
            <StyledSelect
              value={model}
              onChange={onModelChange}
              placeholder={`По умолчанию${defaultModel ? ` — ${defaultModel}` : ''}`}
              options={[
                { value: '', label: `По умолчанию${defaultModel ? ` — ${defaultModel}` : ''}` },
                ...models.map((m) => ({ value: m, label: m })),
              ]}
            />
          </Box>
        )}
      </Box>
    </VStack>
  );
}

/** Секция «Модель глубокого ресёрча (LDR)»: выбор модели, отдельной от чат-модели.
 * Только tool-совместимые модели — агентная стратегия LDR требует function-calling. */
function LdrModelSection({ ldrModel, modelCatalog, onChange }) {
  // modelCatalog — это карта {id: {id, label, capabilities}}, не массив.
  const toolModels = Object.values(modelCatalog || {})
    .filter((m) => Array.isArray(m?.capabilities) && m.capabilities.includes('tools'))
    .sort((a, b) => (a.label || a.id).localeCompare(b.label || b.id));
  return (
    <VStack align="stretch" spacing={2.5}>
      <HStack spacing={2} px={1}>
        <Icon as={FiSearch} boxSize={3.5} color={CHAT_THEME.textTertiary} />
        <Text fontSize="10.5px" fontWeight="700" color={CHAT_THEME.textTertiary} textTransform="uppercase" letterSpacing="0.09em">
          Модель глубокого ресёрча
        </Text>
      </HStack>
      <Box borderRadius={borderRadius.md} bg={colors.surface.tint2} border={`1px solid ${CHAT_THEME.panelBorder}`} overflow="hidden">
        <Box px={4} py={3.5}>
          <Text fontSize="11px" color={CHAT_THEME.textTertiary} fontWeight="500" mb={2.5} lineHeight="1.45">
            Отдельная от чат-модели. Только модели с поддержкой инструментов (function-calling).
          </Text>
          <StyledSelect
            value={ldrModel || ''}
            onChange={onChange}
            placeholder="По умолчанию"
            options={[
              { value: '', label: 'По умолчанию' },
              ...toolModels.map((m) => ({ value: m.id, label: m.label || m.id })),
            ]}
          />
        </Box>
      </Box>
    </VStack>
  );
}

/** Стратегии поиска LDR. Имена совпадают с теми, что знает сам LDR: незнакомое он
 * НЕ отвергает, а молча откатывает на source-based, поэтому список фиксированный, а
 * отсев мусора живёт на стороне агентов (DeepResearchAgent._sanitize_strategy). */
const LDR_STRATEGIES = [
  { value: '', label: 'По умолчанию' },
  { value: 'langgraph-agent', label: 'Агентная — сам подбирает источники' },
  { value: 'source-based', label: 'По источникам — быстрее и дешевле' },
  { value: 'focused-iteration', label: 'Итеративная — уточняет вопросы' },
  { value: 'topic-organization', label: 'По темам — раскладывает по разделам' },
];

/** Секция «Стратегия глубокого ресёрча»: как LDR ведёт поиск. Влияет и на глубину,
 * и на цену прогона, поэтому вынесена пользователю, а не спрятана в админке. */
function LdrStrategySection({ ldrStrategy, onChange }) {
  return (
    <VStack align="stretch" spacing={2.5}>
      <HStack spacing={2} px={1}>
        <Icon as={FiSearch} boxSize={3.5} color={CHAT_THEME.textTertiary} />
        <Text fontSize="10.5px" fontWeight="700" color={CHAT_THEME.textTertiary} textTransform="uppercase" letterSpacing="0.09em">
          Стратегия ресёрча
        </Text>
      </HStack>
      <Box borderRadius={borderRadius.md} bg={colors.surface.tint2} border={`1px solid ${CHAT_THEME.panelBorder}`} overflow="hidden">
        <Box px={4} py={3.5}>
          <Text fontSize="11px" color={CHAT_THEME.textTertiary} fontWeight="500" mb={2.5} lineHeight="1.45">
            Агентная идёт глубже и сама выбирает источники — дольше и дороже. По источникам — короче и дешевле.
          </Text>
          <StyledSelect
            value={ldrStrategy || ''}
            onChange={onChange}
            placeholder="По умолчанию"
            options={LDR_STRATEGIES}
          />
        </Box>
      </Box>
    </VStack>
  );
}

/** Drawer настроек чата: интерфейс и инструменты по умолчанию (хранятся локально). */
/**
 * Кнопка сброса локальных настроек с двухшаговым подтверждением in-place (без
 * модалки): первый клик «взводит» (жёлтая, «Нажмите ещё раз»), второй в течение
 * 3.5с — сбрасывает. Взвод сам снимается по таймауту. Защита от случайного
 * клика по деструктивному действию, которое сносит ВСЕ локальные настройки.
 */
function ResetLocalButton({ onReset }) {
  const [armed, setArmed] = useState(false);
  const timerRef = useRef(0);
  useEffect(() => () => clearTimeout(timerRef.current), []);
  const handleClick = () => {
    if (armed) {
      clearTimeout(timerRef.current);
      setArmed(false);
      onReset?.();
    } else {
      setArmed(true);
      timerRef.current = setTimeout(() => setArmed(false), 3500);
    }
  };
  return (
    <Button
      leftIcon={armed ? <FiAlertTriangle /> : <FiRotateCcw />}
      size="md"
      h="42px"
      variant="ghost"
      fontWeight="600"
      fontSize="13px"
      borderRadius={borderRadius.sm}
      color={armed ? colors.warning : CHAT_THEME.textSecondary}
      bg={armed ? colors.warningSoft : colors.surface.tint2}
      border={`1px solid ${armed ? colors.warningBorder : CHAT_THEME.panelBorder}`}
      _hover={{
        bg: armed ? colors.warningSoft : CHAT_THEME.panelHover,
        color: armed ? colors.warning : CHAT_THEME.textPrimary,
        borderColor: armed ? colors.warningBorder : CHAT_THEME.panelBorderStrong,
      }}
      onClick={handleClick}
    >
      {armed ? 'Нажмите ещё раз для сброса' : 'Сбросить локальные настройки'}
    </Button>
  );
}

export default function ChatSettingsDrawer({
  isOpen,
  onClose,
  showTracePanel,
  multiIntentEnabled,
  planningEnabled,
  memoryEnabled,
  ldrModel,
  ldrStrategy,
  modelCatalog,
  transcriptionConfig,
  transcriptionMode,
  transcriptionModel,
  setChatUiSettings,
  onReset,
}) {
  const handleTranscriptionModeChange = (nextMode) =>
    setChatUiSettings((p) => ({ ...p, transcriptionMode: nextMode }));
  const handleTranscriptionModelChange = (nextModel) =>
    setChatUiSettings((p) => ({ ...p, transcriptionModel: nextModel }));

  const interfaceRows = [
    {
      key: 'trace',
      icon: FiLayers,
      title: 'Пошаговый режим',
      desc: 'Показывать этапы подготовки ответа',
      checked: showTracePanel,
      onChange: () => setChatUiSettings((p) => ({ ...p, showTracePanel: !p.showTracePanel })),
    },
  ];

  // Тумблер долговременной памяти (см. секцию «Память» ниже).
  const memoryRows = [
    {
      key: 'memory',
      icon: FiDatabase,
      title: 'Долговременная память',
      desc: 'Запоминать факты о вас между чатами',
      checked: memoryEnabled,
      onChange: () => setChatUiSettings((p) => ({ ...p, memoryEnabled: !p.memoryEnabled })),
    },
  ];

  // ⚠️ ВЕБ-ПОИСКА И DEEP RESEARCH ЗДЕСЬ БОЛЬШЕ НЕТ. Это ЗНАЧЕНИЯ РЕЖИМА (селектор в
  // композере), а не переключатели: сайдкар резолвит и тоггл, и режим в одну категорию
  // (`routing/policy.py::resolve_forced_category`). Держать их ещё и здесь значило иметь
  // третий орган управления одним и тем же — а после вывода флагов из режима эти
  // переключатели ещё и перестали бы что-либо менять, оставаясь на вид рабочими.
  //
  // Остаются СТРАТЕГИИ «Авто» — то, чего в списке режимов нет по смыслу: они не
  // маршрут, а способ обработки внутри него.
  const toolRows = [
    {
      key: 'multi_intent',
      icon: FiGitBranch,
      title: 'Мульти-интент',
      desc: 'Разбивать составной запрос на под-задачи и выполнять по очереди',
      checked: multiIntentEnabled,
      onChange: () => setChatUiSettings((p) => ({ ...p, multiIntentEnabled: !p.multiIntentEnabled })),
    },
    {
      key: 'planning',
      icon: FiLayers,
      title: 'Планирование',
      desc: 'Строить план решения всегда, а не только на задачах, признанных сложными',
      checked: planningEnabled,
      onChange: () => setChatUiSettings((p) => ({ ...p, planningEnabled: !p.planningEnabled })),
    },
  ];

  return (
    <Drawer
      isOpen={isOpen}
      placement="right"
      onClose={onClose}
      size="md"
      motionPreset="none"
      blockScrollOnMount={false}
      autoFocus={false}
      isLazy
      lazyBehavior="keepMounted"
      preserveScrollBarGap
    >
      <DrawerOverlay {...DRAWER_OVERLAY_PROPS} />
      <DrawerContent
        bg={DRAWER_CONTENT_BG}
        borderLeft={`1px solid ${CHAT_THEME.panelBorder}`}
        boxShadow={shadows.drawer}
        sx={{
          willChange: 'transform',
          backgroundImage: DRAWER_RADIAL_BG,
        }}
      >
        <DrawerCloseButton
          aria-label="Закрыть настройки"
          mt={3}
          mr={2}
          borderRadius={borderRadius.sm}
          color={CHAT_THEME.textSecondary}
          {...DRAWER_CLOSE_BUTTON_PROPS}
          _hover={{ bg: CHAT_THEME.panelHover, color: CHAT_THEME.textPrimary }}
        />
        <DrawerHeader borderBottomWidth="1px" borderColor={colors.border.subtle} py={5}>
          <HStack spacing={3} align="center" pr={10}>
            <Box
              w="38px"
              h="38px"
              borderRadius={borderRadius.sm}
              display="flex"
              alignItems="center"
              justifyContent="center"
              bg={CHAT_THEME.accentSoft}
              border={`1px solid ${colors.accent.subtleBorder}`}
              flexShrink={0}
            >
              <Icon as={FiSettings} boxSize={6} color={IRIS} />
            </Box>
            <VStack align="start" spacing={0.5}>
              <Text fontWeight="700" letterSpacing="-0.01em" fontSize="17px" color={CHAT_THEME.textPrimary}>
                Настройки
              </Text>
              <Text fontSize="11.5px" color={CHAT_THEME.textSecondary} fontWeight="500" lineHeight="1.35">
                Поведение интерфейса и инструменты по умолчанию
              </Text>
            </VStack>
          </HStack>
        </DrawerHeader>
        <DrawerBody px={5} py={5} sx={CHAT_SCROLLBAR_SX}>
          <VStack align="stretch" spacing={5}>
            <SettingsSection icon={FiEye} title="Интерфейс" rows={interfaceRows} />
            <SettingsSection icon={FiDatabase} title="Память" rows={memoryRows} />
            <SettingsSection icon={FiZap} title="Инструменты по умолчанию" rows={toolRows} />
            <TranscriptionSection
              config={transcriptionConfig}
              mode={transcriptionMode}
              model={transcriptionModel}
              onModeChange={handleTranscriptionModeChange}
              onModelChange={handleTranscriptionModelChange}
            />
            <LdrModelSection
              ldrModel={ldrModel}
              modelCatalog={modelCatalog}
              onChange={(id) => setChatUiSettings((p) => ({ ...p, ldrModel: id }))}
            />
            <LdrStrategySection
              ldrStrategy={ldrStrategy}
              onChange={(id) => setChatUiSettings((p) => ({ ...p, ldrStrategy: id }))}
            />

            <Divider borderColor={colors.border.subtle} />

            <ResetLocalButton onReset={onReset} />

            <Text fontSize="11px" color={CHAT_THEME.textTertiary} textAlign="center" fontWeight="500" mt={-1}>
              Настройки сохраняются локально в этом браузере
            </Text>
          </VStack>
        </DrawerBody>
      </DrawerContent>
    </Drawer>
  );
}
