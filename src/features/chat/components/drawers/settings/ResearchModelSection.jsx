import React from 'react';
import { Box, Button, HStack, Icon, Text, VStack } from '@chakra-ui/react';
import { FiSearch } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import AppLoading from '@shared/controls/AppLoading';
import { CHAT_THEME } from '../../../constants/theme';
import StyledSelect from '../../StyledSelect';

/** Research requires positive tool metadata, independently of the chat choice. */
export default function ResearchModelSection({ ldrModel, modelCatalog, onChange, menuOwner,
  status = 'ready', onRetry }) {
  const toolModels = Object.values(modelCatalog || {})
    .filter(model => typeof model?.id === 'string' && Array.isArray(model.capabilities) && model.capabilities.includes('tools'))
    .sort((a, b) => (a.label || a.id).localeCompare(b.label || b.id));
  const missingChoice = ldrModel && !toolModels.some(model => model.id === ldrModel);
  return (
    <VStack role="group" aria-label="Настройка модели ресёрча" align="stretch" spacing={2.5}>
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
          {status === 'loading' && <AppLoading label="Загружаю модели ресёрча…" />}
          {status === 'error' && <Box mb={2.5}>
            <Text role="status" fontSize="12px">Не удалось загрузить сведения о моделях. Сохранённый выбор не изменён.</Text>
            {onRetry && <Button size="document" mt={2} onClick={onRetry}>Повторить загрузку моделей</Button>}
          </Box>}
          {status === 'ready' && !toolModels.length && <Text role="status" fontSize="12px" mb={2.5}>
            В каталоге нет моделей с подтверждённой поддержкой инструментов.
          </Text>}
          {missingChoice && status === 'ready' && <Text role="status" color={colors.warning} fontSize="12px" mb={2.5}>
            Выбранная модель не подтверждена каталогом. Выберите другую или «По умолчанию».
          </Text>}
          <StyledSelect menuPortalTarget={menuOwner} ariaLabel="Модель ресёрча"
            value={ldrModel || ''} onChange={onChange} placeholder="По умолчанию"
            options={[
              { value: '', label: 'По умолчанию' },
              ...toolModels.map(model => ({ value: model.id, label: model.label || model.id })),
              ...(missingChoice ? [{ value: ldrModel, label: ldrModel, isDisabled: true }] : []),
            ]} />
        </Box>
      </Box>
    </VStack>
  );
}
