import { useEffect, useRef, useState } from 'react';
import { Box, Button, Flex, FormControl, FormErrorMessage, FormLabel, Icon, Input, Text } from '@chakra-ui/react';
import { FiCode, FiPlus } from '@shared/icons';
import AppLoading from '@shared/controls/AppLoading';
import { colors } from '@theme/tokens';

export default function IdeProjectStart({ setup, hasThread }) {
  const [name, setName] = useState(setup.submittedName || '');
  const [invalid, setInvalid] = useState(false);
  const input = useRef(null);
  useEffect(() => { if (hasThread) input.current?.focus({ preventScroll: true }); }, [hasThread]);
  const submit = async (event) => {
    event.preventDefault();
    const value = name.normalize('NFC').trim();
    if (!value || value.length > 120 || [...value].some((char) => char.codePointAt(0) < 32 || [127, 8232, 8233].includes(char.codePointAt(0)))) {
      setInvalid(true); input.current?.focus(); return;
    }
    await setup.create(value);
  };
  return <Flex flex="1" minH={0} overflowY="auto" align="center" direction="column" p={{ base: 4, md: 8 }}>
    <Box w="100%" maxW="440px" my="auto" flexShrink={0}>
      <Icon as={FiCode} boxSize={6} color={colors.blue[300]} mb={3} />
      <Text as="h1" fontSize="lg" fontWeight="semibold" mb={2}>Новый проект IDE</Text>
      <Text fontSize="sm" color={colors.fg[3]} mb={5}>
        {hasThread ? 'Отдельный репозиторий и своя среда. Текущий проект не изменится.' : 'Выберите или создайте чат для работы с репозиторием.'}
      </Text>
      {hasThread && <Box as="form" noValidate onSubmit={submit}>
        <FormControl isInvalid={invalid} mb={3}>
          <FormLabel htmlFor="ide-project-name" fontSize="sm">Название проекта</FormLabel>
          <Input ref={input} id="ide-project-name" value={name} maxLength={120} borderRadius="control" placeholder="Например, мой первый проект"
            isReadOnly={Boolean(setup.busy || setup.locked)} aria-describedby={invalid ? 'ide-name-error' : 'ide-create-help'}
            onChange={(event) => { setName(event.target.value); setInvalid(false); }} />
          {invalid && <FormErrorMessage id="ide-name-error">Введите название от 1 до 120 символов без переносов строки.</FormErrorMessage>}
        </FormControl>
        <Button type="submit" size="document" variant="workbenchPrimary" minW="180px" leftIcon={<Icon as={FiPlus} boxSize={3.5} />}
          aria-busy={Boolean(setup.busy)} aria-disabled={Boolean(setup.busy)} onClick={(event) => { if (setup.busy) event.preventDefault(); }}>
          {setup.locked && !setup.busy ? 'Повторить создание' : 'Создать проект'}
        </Button>
        {setup.busy && <Box mt={3}><AppLoading label="Создаю проект…" /></Box>}
        {setup.error && <Text mt={3} fontSize="sm" color={colors.warning} role="alert">Результат не подтверждён. Повтор использует тот же запрос — без создания копии.</Text>}
      </Box>}
      <Text id="ide-create-help" mt={4} fontSize="xs" color={colors.fg[4]}>Подготовим пустой проект с Git. ИИ не запускается, другие проекты не меняются.</Text>
    </Box>
  </Flex>;
}
