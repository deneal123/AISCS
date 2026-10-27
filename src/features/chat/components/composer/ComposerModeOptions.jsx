import React, { useState } from 'react';
import { Box, Checkbox, HStack, Icon, IconButton, Text, VStack, VisuallyHidden } from '@chakra-ui/react';
import { FiCheck, FiGitBranch, FiLayers } from '@shared/icons';
import AppSelect from '@shared/controls/AppSelect';
import ChoiceHint from '@shared/controls/ChoiceHint';
import { borderRadius, colors } from '@theme/tokens';

const STRATEGIES = [
  { key: 'multi', label: 'Мульти-интент', hint: 'Решать несколько задач по очереди', icon: FiLayers },
  { key: 'planning', label: 'Планирование', hint: 'Всегда строить план в режиме Авто', icon: FiGitBranch },
];

/** One mode listbox; the narrow presentation reveals only the focused explanation. */
export default function ComposerModeOptions({ options, value, onChange, close, isMobile, compact, inputId, details,
  multiIntentEnabled, onToggleMultiIntent, planningEnabled, onTogglePlanning }) {
  const [keyboardHints, setKeyboardHints] = useState(false);
  const icons = compact && !details;
  const column = icons && !isMobile;
  const strategies = STRATEGIES.map((strategy) => ({ ...strategy,
    checked: strategy.key === 'multi' ? multiIntentEnabled : planningEnabled,
    change: strategy.key === 'multi' ? onToggleMultiIntent : onTogglePlanning,
  })).filter((strategy) => strategy.change);
  return <Box onKeyDownCapture={(event) => { if (['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) setKeyboardHints(true); }}
    onPointerDownCapture={() => setKeyboardHints(false)}
    onPointerMoveCapture={() => setKeyboardHints(false)}>
    <AppSelect presentation={column ? 'composer-icon-column' : icons ? 'composer-icons' : 'composer'} inputId={inputId} ariaLabel="Выбор режима"
      value={value ?? ''} options={options} isSearchable={false} placeholder="Выберите режим"
      autoFocus={!isMobile} size={isMobile ? 'touch' : 'sm'} onClose={close}
      showOptionHints={icons && keyboardHints}
      onChange={(next) => { onChange?.(next || null); close(); }}
      formatOptionLabel={(option) => icons ? <>
        <Icon as={option.icon} boxSize={4} aria-hidden="true" />
        <VisuallyHidden>{option.label}</VisuallyHidden>
        {option.value === (value ?? '') && <Icon as={FiCheck} boxSize={2.5} position="absolute" top={1} right={1} color={colors.blue[100]} aria-hidden="true" />}
      </> : <HStack align="start" spacing={3}>
        <Icon as={option.icon} mt={1} boxSize={4} flexShrink={0} />
        <VStack align="stretch" spacing={1} flex={1} minW={0}>
          <Text fontWeight={600}>{option.label}</Text>
          <Text fontSize="12px" color={colors.fg[3]} lineHeight={1.5}>{option.hint}</Text>
        </VStack>
        {option.value === (value ?? '') && <Icon as={FiCheck} mt={1} color={colors.blue[100]} />}
      </HStack>} />
    {value == null && strategies.length > 0 && <Box borderTop="1px solid" borderColor={colors.border.medium} mt={1} px={1} pt={1} pb={0}
      sx={{ '.chakra-checkbox__control': { borderRadius: borderRadius.control, borderColor: colors.ink[400],
        '&[data-checked]': { borderColor: colors.blue[300], bg: colors.blue[500] } } }}>
      {!icons && <Text fontSize="11px" color={colors.fg[3]} mb={2}>Дополнительно</Text>}
      <Box role="group" aria-label="Стратегии ответа" display="flex" flexDirection={icons && !column ? 'row' : 'column'} alignItems={column ? 'center' : undefined}
        justifyContent={icons && !column ? 'center' : undefined} gap={icons ? 2 : 3}>
        {strategies.map((strategy) => <ChoiceHint key={strategy.key} label={icons ? `${strategy.label}: ${strategy.hint}` : null} flex={icons ? '0 0 auto' : undefined}>
          {icons ? <IconButton aria-label={strategy.label} aria-pressed={Boolean(strategy.checked)}
            icon={<Icon as={strategy.icon} boxSize={4} />} onClick={strategy.change}
            variant="ghost" w="44px" minW="44px" h="44px" borderRadius={borderRadius.control}
            color={strategy.checked ? colors.blue[100] : colors.fg[2]}
            bg={strategy.checked ? colors.accent.subtle : undefined}
            boxShadow={strategy.checked ? `inset 0 0 0 2px ${colors.blue[300]}` : undefined}
          /> : <Checkbox isChecked={strategy.checked} onChange={strategy.change}
          aria-label={icons ? strategy.label : undefined} minH={icons ? '44px' : undefined} flex={icons ? 1 : undefined}
          >
          {icons ? <><Icon as={strategy.icon} boxSize={4} aria-hidden="true" /><VisuallyHidden>{strategy.label}</VisuallyHidden></>
            : <><Text fontSize="13px">{strategy.label}</Text><Text fontSize="12px" color={colors.fg[3]}>{strategy.hint}</Text></>}
        </Checkbox>}</ChoiceHint>)}
      </Box>
    </Box>}
  </Box>;
}
