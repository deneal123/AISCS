import { useRef, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  FormControl,
  FormErrorMessage,
  FormLabel,
  HStack,
  Input,
  Text,
  VStack,
} from '@chakra-ui/react';
import AppTextarea from '@shared/controls/AppTextarea';
import { borderRadius, colors } from '@theme/tokens';
import { ISSUE_STATUS_LABELS } from '../model/constants';

const issueTone = (status) => ({
  resolved: 'green',
  stale: 'orange',
  open: 'blue',
}[status] || 'gray');

const EMPTY_FORM = { title: '', body: '', start: '1', end: '1' };

export function WorkIssuesPanel({ room, file, busy, onCreateIssue, onUpdateIssue }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [errors, setErrors] = useState({});
  const titleRef = useRef(null);
  const startRef = useRef(null);
  const endRef = useRef(null);

  const validate = () => {
    const next = {};
    const start = Number(form.start);
    const end = Number(form.end);
    if (!form.title.trim()) next.title = 'Введите название задачи.';
    if (!Number.isInteger(start) || start < 1 || start > 1000000) {
      next.start = 'Укажите строку от 1 до 1 000 000.';
    }
    if (!Number.isInteger(end) || end < 1 || end > 1000000) {
      next.end = 'Укажите строку от 1 до 1 000 000.';
    } else if (!next.start && end < start) {
      next.end = 'Конечная строка не может быть меньше начальной.';
    }
    setErrors(next);
    const first = next.title ? titleRef : next.start ? startRef : next.end ? endRef : null;
    first?.current?.focus?.();
    return Object.keys(next).length === 0;
  };

  const submitIssue = async (event) => {
    event.preventDefault();
    if (!validate()) return;
    const saved = await onCreateIssue({
      title: form.title,
      body: form.body,
      startLine: form.start,
      endLine: form.end,
    });
    if (saved) {
      setForm(EMPTY_FORM);
      setErrors({});
    }
  };

  return (
    <VStack align="stretch" spacing={2}>
      {room?.issuesState === 'unavailable' && (
        <Box
          p={3}
          borderRadius={borderRadius.md}
          bg={colors.warningSoft}
          border={`1px solid ${colors.warningBorder}`}
        >
          <Text fontSize="11.5px" color={colors.fg[3]}>
            Задачи временно недоступны. Файлы рабочего места по-прежнему видны.
          </Text>
        </Box>
      )}
      {room?.issuesState === 'stale' && (
        <Text fontSize="11px" color={colors.warning} role="status">
          Показаны последние доступные задачи. Обновление временно не удалось.
        </Text>
      )}
      {room?.issuesState === 'loading' && (
        <Text fontSize="11px" color={colors.fg[4]} role="status">
          Загружаю задачи…
        </Text>
      )}
      {file.path ? (
        <Box
          as="form"
          onSubmit={submitIssue}
          noValidate
          p={3}
          borderRadius={borderRadius.md}
          border={`1px solid ${colors.border.subtle}`}
        >
          <FormControl isRequired isInvalid={Boolean(errors.title)}>
            <FormLabel fontSize="11px">Новая задача для файла</FormLabel>
            <Input
              ref={titleRef}
              size="sm"
              value={form.title}
              onChange={(event) => {
                setForm((old) => ({ ...old, title: event.target.value }));
                setErrors((old) => ({ ...old, title: undefined }));
              }}
            />
            <FormErrorMessage>{errors.title}</FormErrorMessage>
          </FormControl>
          <FormControl mt={2}>
            <FormLabel fontSize="11px">Контекст</FormLabel>
            <AppTextarea
              rows={2}
              value={form.body}
              onChange={(event) => setForm((old) => ({ ...old, body: event.target.value }))}
            />
          </FormControl>
          <HStack mt={2} align="start">
            <FormControl isInvalid={Boolean(errors.start)}>
              <Input
                ref={startRef}
                size="sm"
                type="number"
                min="1"
                max="1000000"
                aria-label="Строка от"
                value={form.start}
                onChange={(event) => {
                  setForm((old) => ({ ...old, start: event.target.value }));
                  setErrors((old) => ({ ...old, start: undefined }));
                }}
              />
              <FormErrorMessage>{errors.start}</FormErrorMessage>
            </FormControl>
            <FormControl isInvalid={Boolean(errors.end)}>
              <Input
                ref={endRef}
                size="sm"
                type="number"
                min="1"
                max="1000000"
                aria-label="Строка до"
                value={form.end}
                onChange={(event) => {
                  setForm((old) => ({ ...old, end: event.target.value }));
                  setErrors((old) => ({ ...old, end: undefined }));
                }}
              />
              <FormErrorMessage>{errors.end}</FormErrorMessage>
            </FormControl>
          </HStack>
          <Button
            mt={2}
            size="xs"
            type="submit"
            isLoading={busy === 'issue:create'}
            colorScheme="blue"
          >
            Добавить задачу
          </Button>
        </Box>
      ) : (
        <Text fontSize="12px" color={colors.fg[4]}>
          Откройте файл, чтобы добавить задачу.
        </Text>
      )}
      {(room?.issues || []).map((issue) => (
        <Box
          key={issue.issue_id}
          p={3}
          borderRadius={borderRadius.md}
          border={`1px solid ${colors.border.subtle}`}
        >
          <HStack align="start" justify="space-between">
            <Box minW={0}>
              <Text fontSize="12px" fontWeight="600" color={colors.fg[2]}>
                {issue.title}
              </Text>
              <Text fontSize="10.5px" color={colors.fg[4]} noOfLines={1}>
                {issue.path} · строки {issue.start_line}–{issue.end_line}
              </Text>
            </Box>
            <Badge colorScheme={issueTone(issue.status)}>
              {ISSUE_STATUS_LABELS[issue.status] || 'Статус недоступен'}
            </Badge>
          </HStack>
          {issue.body && (
            <Text mt={2} fontSize="11.5px" color={colors.fg[3]} whiteSpace="pre-wrap">
              {issue.body}
            </Text>
          )}
          {issue.status !== 'resolved' && (
            <Button
              mt={2}
              size="xs"
              variant="outline"
              colorScheme="green"
              onClick={() => onUpdateIssue(issue, 'resolved')}
              isLoading={busy === `issue:${issue.issue_id}`}
            >
              Готово
            </Button>
          )}
        </Box>
      ))}
    </VStack>
  );
}
