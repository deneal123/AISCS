import { Box, Button, Text } from '@chakra-ui/react';
import AppSelect from '@shared/controls/AppSelect';
import { colors } from '@theme/tokens';

/** Selection only edits the local semantic draft; bibliography stays authoritative. */
export function PdfCitationSource({ inventory, value, onChange, label = 'Источник цитаты', ariaLabel = label, disabled }) {
  const missing = Boolean(value && !inventory.sources.some((source) => source.value === String(value)));
  const options = missing ? [...inventory.sources, { value: String(value), label: `Источник ${value} · нет в списке`, isDisabled: true }] : inventory.sources;
  const selected = inventory.sources.find((source) => source.value === String(value));
  return <Box minW={0} maxW="full">
    <Text fontSize="11px" color={colors.fg[3]} mb={1}>{label}</Text>
    <AppSelect ariaLabel={ariaLabel} size="document" options={options} value={value || ''}
      placeholder={inventory.status === 'loading' ? 'Загружаю источники…' : 'Выберите источник'}
      isDisabled={disabled || inventory.status !== 'ready' || !inventory.sources.length}
      onChange={onChange} />
    {inventory.status === 'unavailable' ? <Box role="status" mt={1}>
      <Text fontSize="11px" color={colors.warning}>Не удалось прочитать актуальные источники. Ссылки в черновике сохранены.</Text>
      <Button size="document" variant="ghost" onClick={inventory.retry || inventory.load}>Повторить загрузку источников</Button>
    </Box> : inventory.status === 'ready' && !inventory.sources.length ? <Text fontSize="11px" color={colors.fg[3]} mt={1}>
      В библиографии проекта пока нет доступных зарегистрированных источников. Файлы Библиотеки не становятся источниками автоматически.
    </Text> : missing && inventory.status === 'ready' ? <Text role="status" fontSize="11px" color={colors.warning} mt={1}>
      Источник не найден в текущей библиографии. Ссылка не изменена; проверьте исходник библиографии перед сохранением.
    </Text> : null}
    {selected?.author && <Text fontSize="11px" color={colors.fg[3]} mt={1} overflowWrap="anywhere">{selected.author}</Text>}
    {(selected?.doi || selected?.url) && <Text fontSize="11px" color={colors.fg[3]} mt={1} overflowWrap="anywhere">
      {selected.doi ? `DOI: ${selected.doi}` : selected.url}
    </Text>}
    {inventory.unresolved > 0 && <Text fontSize="11px" color={colors.warning} mt={1}>
      Часть записей нельзя выбрать: ключ не зарегистрирован или неоднозначен. Исходная библиография не изменена.
    </Text>}
  </Box>;
}
