import React, { useState } from 'react';
import { Box, Button, HStack, Icon, Text, VStack, VisuallyHidden } from '@chakra-ui/react';
import { FiCheck, FiInfo, FiUser } from '@shared/icons';
import AppSelect from '@shared/controls/AppSelect';
import ChoicePanel from '@shared/controls/ChoicePanel';
import { borderRadius, colors } from '@theme/tokens';
import { getPersonaIcon } from '../../constants/personaIcons';

export const MAX_PERSONAS = 2;

function ComposerPersonaSelector({ personas = [], value = [], onChange, mobileIconOnly = false }) {
  const [details, setDetails] = useState(false);
  if (!personas.length) return null;
  const selected = Array.isArray(value) ? value : [];
  const active = selected.map((id) => personas.find((persona) => persona.id === id)).filter(Boolean);
  const label = active.length ? active.map((persona) => persona.label).join(' + ') : 'Без личности';
  const atCap = selected.length >= MAX_PERSONAS;
  const options = personas.map((persona) => ({ ...persona, value: persona.id }));
  return (
    <ChoicePanel label={`Личность: ${label}`} compactLabel={label} title="Личность ассистента" compactTitle="Личности" icon={FiUser} mobileIconOnly={mobileIconOnly} selected={active.length > 0} done compactWidth={details ? 320 : 240}
      variant="persona-palette" mobileWidth={details ? 320 : 280}
      headerAction={<Button size="document" variant="ghost" px={1} minW="32px" h="32px" aria-label={details ? 'Скрыть описания личностей' : 'Показать описания личностей'} aria-pressed={details}
        onClick={() => setDetails(shown => !shown)}><Icon as={FiInfo} boxSize={3.5} /></Button>}>
      {({ close, isMobile, compact, inputId }) => (
        <>
          {!compact && <Text px={2} fontSize="13px" mb={2} overflowWrap="anywhere">{label}</Text>}
          <HStack px={2} justify="space-between" minH="28px" mb={1}>
            <Text fontSize="11px" color={colors.fg[3]}>Выбрано {selected.length} из {MAX_PERSONAS}{!compact || details ? '. Первая задаёт основной стиль.' : ''}</Text>
            {selected.length > 0 && <Button variant="ghost" size="xs" flexShrink={0} onClick={() => onChange?.([])}>Без личности</Button>}
          </HStack>
          <AppSelect presentation={isMobile && !details ? 'composer-persona-icons' : compact ? 'composer-compact' : 'composer'} inputId={inputId} ariaLabel="Выбор личностей"
            value={selected} options={options} isMulti isSearchable={false} placeholder="Выберите до двух личностей"
            autoFocus={!isMobile} size={isMobile ? 'touch' : 'sm'} onClose={close}
            isOptionDisabled={(option) => atCap && !selected.includes(option.value)}
            onChange={(next) => { if (next.length <= MAX_PERSONAS) onChange?.(next); }}
            formatOptionLabel={(option) => {
              const checked = selected.includes(option.value);
              if (isMobile && !details) return <>
                <Icon as={getPersonaIcon(option.value)} boxSize={5} data-persona-icon={option.value} aria-hidden="true" />
                <VisuallyHidden>{option.label}</VisuallyHidden>
                {checked && <Box as="span" data-persona-order position="absolute" top={0.5} right={1}
                  fontSize="11px" fontWeight={700} color={colors.blue[100]}>{selected.indexOf(option.value) + 1}</Box>}
              </>;
              return (
                <HStack align={compact && !details ? 'center' : 'start'} spacing={compact ? 2 : 3} w="100%">
                  <Box aria-hidden="true" boxSize={4} mt={compact && !details ? 0 : 1} flexShrink={0} border="1px solid"
                    borderColor={checked ? colors.blue[300] : colors.ink[400]}
                    borderRadius={borderRadius.control} bg={checked ? colors.accent.subtle : 'transparent'}>
                    {checked && <Icon as={FiCheck} boxSize={3.5} color={colors.blue[100]} />}
                  </Box>
                  <VStack align="stretch" spacing={1} minW={0}>
                    <HStack flexWrap="wrap"><Text fontSize={compact ? '12px' : '13px'} fontWeight={600}>{option.label}</Text>
                      {selected.length > 1 && selected[0] === option.value && <Text fontSize="11px" color={colors.blue[100]}>Ведущая</Text>}
                    </HStack>
                    {option.hint && (!compact || details) && <Text fontSize="12px" color={colors.fg[3]} lineHeight={1.5}>{option.hint}</Text>}
                  </VStack>
                </HStack>
              );
            }} />
          {atCap && (!compact || details) && <Text px={2} mt={2} fontSize="12px" color={colors.fg[3]}>Чтобы выбрать другую, снимите одну из выбранных.</Text>}
        </>
      )}
    </ChoicePanel>
  );
}

export default React.memo(ComposerPersonaSelector);
