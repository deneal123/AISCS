import { useEffect, useState } from 'react';
import { Accordion, AccordionButton, AccordionIcon, AccordionItem, AccordionPanel, Box, Button, HStack, Icon, IconButton,
  Popover, PopoverBody, PopoverCloseButton, PopoverContent, PopoverHeader, PopoverTrigger, Portal, Text, VStack, useDisclosure } from '@chakra-ui/react';
import { FiInfo, FiRefreshCw } from '@shared/icons';
import { borderRadius, colors, layers } from '@theme/tokens';
import { WorkspaceTree } from './WorkspaceTree';
import { groupPdfMaterials, materialCount } from '../model/pdfMaterials';

const TEXT_SOURCE = /\.(?:tex|bib|toml|json|md|txt|csv|tsv|yaml|yml|sty|cls|bst|cfg)$/i;
const canEdit = (item) => TEXT_SOURCE.test(item.path);

/** Project material inspection is separate from the single account Library. */
export function PdfMaterialsPanel({ work, onOpenFile, blocked, error }) {
  const path = work.document.project?.path;
  const entries = work.hub.workspace.entries || [];
  const grouped = groupPdfMaterials(entries, path);
  const sections = [
    { key: 'builds', label: 'Результаты сборки', base: path ? `${path}/artifacts` : '' },
    { key: 'service', label: 'Служебные файлы', base: path },
    { key: 'shared', label: 'Общие файлы чата', base: '' },
  ].filter(section => section.key === 'shared' || grouped[section.key].length);
  const selectedGroup = sections.find(section => grouped[section.key].some(item => item.path === work.file.path))?.key;
  const [disclosures, setDisclosures] = useState({ path, keys: [] });
  const { isOpen, onOpen, onClose } = useDisclosure();
  useEffect(() => {
    setDisclosures(old => {
      const keys = old.path === path ? old.keys : [];
      return { path, keys: selectedGroup && !keys.includes(selectedGroup) ? [...keys, selectedGroup] : keys };
    });
  }, [path, selectedGroup, work.file.path]);
  const fileList = (items, basePath = '', label = 'Исходники текущего проекта') => <Box><WorkspaceTree key={basePath || 'shared'} entries={items} basePath={basePath} scrollable={false}
    label={label}
    selected={work.file.path} onSelect={onOpenFile} disabled={work.file.loading || !path || work.hub.workspace.state !== 'ready'}
    canSelect={canEdit} /></Box>;
  return <VStack align="stretch" h="full" minH={0} spacing={3} data-testid="pdf-materials-panel">
    <HStack spacing={1}><Text flex="1" fontSize="12px" fontWeight={600}>Файлы проекта</Text>
      <Popover placement="bottom-end" isLazy isOpen={isOpen} onOpen={onOpen} onClose={onClose}>
        <PopoverTrigger><Button size="document" variant="ghost" px={1} minW="30px" aria-label="О материалах проекта" title="О материалах проекта" onClick={onOpen}><Icon as={FiInfo} boxSize={3.5} /></Button></PopoverTrigger>
        <Portal><PopoverContent bg={colors.bg.menu} borderColor={colors.border.strong} borderRadius={borderRadius.md} w="280px" maxW="calc(100vw - 24px)" zIndex={layers.drawer}>
          <PopoverHeader fontSize="13px" fontWeight={600} pr={12} border={0}>Материалы проекта</PopoverHeader>
          <PopoverCloseButton aria-label="Закрыть справку о материалах" />
          <PopoverBody pt={1} pb={3} fontSize="12px" color={colors.fg[2]}>
            <Text mb={2}>Добавление файлов — в Библиотеке слева. Здесь открываются текстовые исходники проекта и общие файлы чата.</Text>
            <Text>PDF, изображения и архивы не редактируются как текст. Добавление файла не вставляет его автоматически в документ или список источников.</Text>
          </PopoverBody>
        </PopoverContent></Portal>
      </Popover>
      <IconButton aria-label="Обновить материалы" title="Обновить материалы" icon={<FiRefreshCw />}
      variant="ghost" size="document" px={0}
      isLoading={work.hub.refreshing} onClick={() => work.load({ background: true })} /></HStack>
    {blocked && <Text role="status" fontSize="12px" color={colors.warning}>
      Изменение материалов пока недоступно. Просмотр доступен.
    </Text>}
    {error && <Text role="alert" fontSize="12px" color={colors.warning}>{error}</Text>}
    <VStack spacing={2} align="stretch" flex="1" minH={0} overflowY="auto" sx={{ scrollbarGutter: 'stable' }}>
      {path ? fileList(grouped.sources, path) : <Text fontSize="12px" color={colors.fg[3]}>Выберите PDF-проект.</Text>}
      <Accordion allowMultiple reduceMotion index={sections.flatMap((section, index) => disclosures.path === path && disclosures.keys.includes(section.key) ? [index] : [])}
        onChange={indexes => setDisclosures({ path, keys: indexes.map(index => sections[index].key) })}>
        {sections.map(section => <AccordionItem key={section.key} border={0} isDisabled={!grouped[section.key].length}>
          <AccordionButton px={1} py={2} minH="30px" gap={2} borderRadius={borderRadius.control} _hover={{ bg: colors.surface.tint3 }}>
            <Text flex="1" textAlign="left" fontSize="12px" fontWeight={600}>{section.label}</Text>
            <Text fontSize="11px" color={colors.fg[3]}>{materialCount(grouped[section.key])}</Text><AccordionIcon boxSize={4} />
          </AccordionButton>
          <AccordionPanel px={0} pt={0} pb={2}>{fileList(grouped[section.key], section.base, section.label)}</AccordionPanel>
        </AccordionItem>)}
      </Accordion>
    </VStack>
  </VStack>;
}
