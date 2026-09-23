import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerHeader,
  DrawerOverlay,
  Flex,
  HStack,
  Icon,
  Input,
  InputGroup,
  InputRightElement,
  IconButton,
  Spinner,
  Text,
  VStack,
} from '@chakra-ui/react';
import { FiExternalLink, FiFileText, FiGitMerge, FiSearch, FiShare2, FiTrash2, FiZap } from '@shared/icons';
import { colors, borderRadius, typography } from '@theme/tokens';
import { DRAWER_CLOSE_BUTTON_PROPS, DRAWER_OVERLAY_PROPS, DRAWER_RADIAL_BG, DRAWER_CONTENT_BG } from '@theme/drawer';
import { CHAT_SCROLLBAR_SX, CHAT_THEME } from '../../constants/theme';

/** Русская плюрализация: forms = [ед., 2–4, много]. */
function pluralize(n, forms) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return forms[0];
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return forms[1];
  return forms[2];
}

/** Показатель графа — крупное число + подпись. Три в ряд дают картину одним взглядом. */
function Stat({ icon, value, label }) {
  return (
    <VStack
      flex="1"
      spacing={0.5}
      py={3}
      borderRadius={borderRadius.lg}
      bg={colors.border.faint}
      border={`1px solid ${colors.border.subtle}`}
    >
      <Icon as={icon} boxSize="14px" color={colors.fg[4]} />
      <Text fontSize="18px" fontWeight="700" fontFamily={typography.fontFamily.mono} color={colors.fg[1]}>
        {Number(value || 0).toLocaleString('ru-RU')}
      </Text>
      <Text fontSize="11px" color={colors.fg[4]}>
        {label}
      </Text>
    </VStack>
  );
}

/**
 * Панель графа знаний: что в личном корпусе пользователя и как он связан.
 *
 * Граф копится МЕЖДУ тредами (в отличие от файла в контексте треда, который жил один
 * на тред и умирал по TTL), поэтому пользователь обязан видеть, что о нём накопили,
 * и уметь это стереть.
 */
export default function ChatGraphDrawer({ isOpen, onClose, loadSummary, onSearch, onDelete, onOpenHtml }) {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  // Результат гибридный: passages — дословные фрагменты (эмбеддинги), relations — связи
  // (граф). Показываем ровно то, что получает модель, а не половину.
  const [result, setResult] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setSummary(await loadSummary());
    } finally {
      setLoading(false);
    }
  }, [loadSummary]);

  useEffect(() => {
    if (isOpen) refresh();
  }, [isOpen, refresh]);

  const handleSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    try {
      setResult(await onSearch(q));
    } finally {
      setSearching(false);
    }
  }, [query, onSearch]);

  const handleDelete = useCallback(async () => {
    await onDelete();
    setResult(null);
    await refresh();
  }, [onDelete, refresh]);

  const documents = useMemo(() => summary?.documents || [], [summary]);
  const topNodes = useMemo(() => summary?.top_nodes || [], [summary]);

  const disabled = summary && summary.enabled === false;
  const empty = summary && summary.enabled !== false && !summary.exists;

  return (
    <Drawer isOpen={isOpen} placement="right" onClose={onClose} size="md">
      <DrawerOverlay {...DRAWER_OVERLAY_PROPS} />
      <DrawerContent
        bg={DRAWER_CONTENT_BG}
        borderLeft={`1px solid ${CHAT_THEME.panelBorder}`}
        sx={{ willChange: 'transform', backgroundImage: DRAWER_RADIAL_BG }}
      >
        <DrawerCloseButton aria-label="Закрыть граф знаний" {...DRAWER_CLOSE_BUTTON_PROPS} />
        <DrawerHeader
          borderBottomWidth="1px"
          borderColor={colors.border.subtle}
          display="flex"
          alignItems="center"
          gap={2}
        >
          <Icon as={FiShare2} color={colors.fg[3]} />
          <Text>Граф знаний</Text>
        </DrawerHeader>

        <DrawerBody pt={4} sx={CHAT_SCROLLBAR_SX}>
          {loading && !summary ? (
            <Flex justify="center" py={10}>
              <Spinner size="sm" color={colors.fg[4]} />
            </Flex>
          ) : disabled ? (
            <Text fontSize="sm" color={colors.fg[4]}>
              Граф знаний выключен в настройках сервиса.
            </Text>
          ) : empty ? (
            <VStack align="start" spacing={2} py={6}>
              <Text fontSize="sm" color={colors.fg[3]}>
                Граф пока пуст.
              </Text>
              <Text fontSize="xs" color={colors.fg[4]} lineHeight="1.6">
                Загрузите документ — он попадёт сюда автоматически и будет доступен во всех
                диалогах, а не только в текущем. Архив с кодом (zip) превратится в карту
                архитектуры.
              </Text>
            </VStack>
          ) : (
            <VStack align="stretch" spacing={5}>
              <HStack spacing={2}>
                <Stat icon={FiZap} value={summary?.nodes} label="узлов" />
                <Stat icon={FiGitMerge} value={summary?.edges} label="связей" />
                <Stat icon={FiFileText} value={documents.length} label="источников" />
              </HStack>

              {/* Поиск — тот же обход графа, который модель зовёт инструментом. */}
              <Box>
                <InputGroup size="sm">
                  <Input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                    placeholder="Как связаны…?"
                    borderRadius={borderRadius.md}
                    bg={colors.border.faint}
                    borderColor={colors.border.subtle}
                  />
                  <InputRightElement>
                    <IconButton
                      aria-label="Искать в графе"
                      icon={searching ? <Spinner size="xs" /> : <FiSearch />}
                      size="xs"
                      variant="ghost"
                      onClick={handleSearch}
                      isDisabled={searching || !query.trim()}
                    />
                  </InputRightElement>
                </InputGroup>
                {result && (
                  <VStack align="stretch" spacing={2} mt={2}>
                    {result.passages?.length > 0 && (
                      <Box>
                        <Text fontSize="10px" color={colors.fg[4]} mb={1}>
                          Фрагменты документов — дословно
                        </Text>
                        <VStack align="stretch" spacing={1}>
                          {result.passages.map((hit, i) => (
                            <Box
                              key={`${hit.filename}-${i}`}
                              p={2.5}
                              borderRadius={borderRadius.md}
                              bg={colors.border.faint}
                              border={`1px solid ${colors.border.subtle}`}
                            >
                              <Text fontSize="10px" color={colors.fg[4]} mb={1}>
                                {hit.filename}
                              </Text>
                              <Text fontSize="12px" color={colors.fg[2]} noOfLines={4}>
                                {hit.text}
                              </Text>
                            </Box>
                          ))}
                        </VStack>
                      </Box>
                    )}
                    {result.relations && (
                      <Box>
                        <Text fontSize="10px" color={colors.fg[4]} mb={1}>
                          Связи из графа
                        </Text>
                        <Box
                          p={3}
                          maxH="200px"
                          overflowY="auto"
                          borderRadius={borderRadius.md}
                          bg={colors.border.faint}
                          border={`1px solid ${colors.border.subtle}`}
                          sx={CHAT_SCROLLBAR_SX}
                        >
                          <Text
                            fontSize="11px"
                            fontFamily={typography.fontFamily.mono}
                            color={colors.fg[3]}
                            whiteSpace="pre-wrap"
                          >
                            {result.relations}
                          </Text>
                        </Box>
                      </Box>
                    )}
                    {!result.passages?.length && !result.relations && (
                      <Text fontSize="xs" color={colors.fg[4]}>
                        Ничего не найдено по этому запросу.
                      </Text>
                    )}
                  </VStack>
                )}
              </Box>

              {topNodes.length > 0 && (
                <Box>
                  <Text fontSize="xs" color={colors.fg[4]} mb={2}>
                    Ключевые узлы — вокруг них в корпусе всё и вертится
                  </Text>
                  <Flex wrap="wrap" gap={1.5}>
                    {topNodes.map((node) => (
                      <HStack
                        key={node.label}
                        spacing={1.5}
                        px={2.5}
                        py={1}
                        borderRadius={borderRadius.full}
                        bg={colors.accent.subtle}
                        border={`1px solid ${colors.accent.subtleBorder}`}
                      >
                        <Text fontSize="11px" color={colors.fg[2]} noOfLines={1} maxW="180px">
                          {node.label}
                        </Text>
                        <Text
                          fontSize="10px"
                          fontFamily={typography.fontFamily.mono}
                          color={colors.fg[4]}
                        >
                          {node.links}
                        </Text>
                      </HStack>
                    ))}
                  </Flex>
                </Box>
              )}

              {documents.length > 0 && (
                <Box>
                  <Text fontSize="xs" color={colors.fg[4]} mb={2}>
                    {documents.length}{' '}
                    {pluralize(documents.length, ['источник', 'источника', 'источников'])} в графе
                  </Text>
                  <VStack align="stretch" spacing={1}>
                    {documents.slice(0, 30).map((doc) => (
                      <HStack
                        key={doc.source}
                        justify="space-between"
                        px={3}
                        py={2}
                        borderRadius={borderRadius.md}
                        bg={colors.border.faint}
                        border={`1px solid ${colors.border.subtle}`}
                      >
                        <HStack spacing={2} minW={0}>
                          <Icon as={FiFileText} boxSize="12px" color={colors.fg[4]} />
                          <Text fontSize="12px" color={colors.fg[2]} noOfLines={1}>
                            {doc.source}
                          </Text>
                        </HStack>
                        <Text
                          fontSize="10px"
                          fontFamily={typography.fontFamily.mono}
                          color={colors.fg[4]}
                          flexShrink={0}
                        >
                          {doc.nodes}
                        </Text>
                      </HStack>
                    ))}
                  </VStack>
                </Box>
              )}

              <HStack spacing={2} pt={2}>
                <Button
                  size="sm"
                  variant="outline"
                  leftIcon={<FiExternalLink />}
                  flex="1"
                  onClick={onOpenHtml}
                >
                  Открыть граф
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  leftIcon={<FiTrash2 />}
                  color={colors.fg[4]}
                  onClick={handleDelete}
                >
                  Очистить
                </Button>
              </HStack>
            </VStack>
          )}
        </DrawerBody>
      </DrawerContent>
    </Drawer>
  );
}
