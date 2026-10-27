import { useEffect, useRef } from 'react';
import { Box, Button, FormControl, FormErrorMessage, FormLabel, HStack, Input, Text } from '@chakra-ui/react';
import { colors } from '@theme/tokens';

export default function IdeLibraryDestination({ copy, target, disabled }) {
  const input = useRef(null);
  const close = useRef(null);
  useEffect(() => { if (copy.file) input.current?.focus(); }, [copy.file?.file_id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (copy.invalid) input.current?.focus(); }, [copy.invalid]);
  useEffect(() => { if (!copy.busy && (copy.done || copy.uncertain)) close.current?.focus(); }, [copy.busy, copy.done, copy.uncertain]);
  if (!copy.file) return null;
  return <Box as="form" noValidate data-testid="ide-library-copy" flexShrink={0} borderBottom="1px solid" borderColor={colors.border.subtle} pb={3}
    onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); if (!copy.busy) copy.clear(); } }}
    onSubmit={event => { event.preventDefault(); void copy.submit(); }}>
    <Text fontSize="xs" mb={2} overflowWrap="anywhere">{copy.file.name} → IDE: {target?.name || 'Репозиторий'}</Text>
    <FormControl id="ide-library-path" isInvalid={copy.invalid}>
      <FormLabel htmlFor="ide-library-path" fontSize="xs">Путь назначения</FormLabel>
      <Input ref={input} id="ide-library-path" size="sm" borderRadius="control" value={copy.path} maxLength={1024}
        isReadOnly={copy.busy || copy.done || copy.uncertain} onChange={event => copy.setPath(event.target.value)} aria-describedby="ide-library-help" />
      {copy.invalid && <FormErrorMessage>Введите относительный путь без «..» и служебных каталогов.</FormErrorMessage>}
    </FormControl>
    <Text id="ide-library-help" fontSize="11px" color={colors.fg[3]} mt={2}>До 20 МиБ. Папка должна существовать. Файлы не перезаписываются; архивы не распаковываются.</Text>
    {copy.error && <Text role="alert" fontSize="xs" mt={2}>{copy.error}</Text>}
    {copy.done && <Text role="status" fontSize="xs" mt={2}>Файл добавлен в IDE: {copy.path}. Это не Git-коммит.</Text>}
    <HStack mt={2} spacing={2}>
      <Button type="submit" size="document" variant="workbenchPrimary" isDisabled={disabled || copy.done || copy.uncertain}
        aria-disabled={copy.busy || undefined} aria-busy={copy.busy || undefined}>Добавить в IDE</Button>
      <Button ref={close} size="document" variant="ghost" isDisabled={copy.busy} onClick={copy.clear}>{copy.done || copy.uncertain ? 'Закрыть' : 'Отмена'}</Button>
    </HStack>
  </Box>;
}
