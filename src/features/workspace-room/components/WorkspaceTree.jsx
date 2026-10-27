import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Box, HStack, Icon, Text, VStack } from '@chakra-ui/react';
import { FiChevronDown, FiChevronRight, FiFileText, FiFolder } from '@shared/icons';
import { borderRadius, colors } from '@theme/tokens';
import { WORK_HUB_THEME, WORK_SCROLLBAR_SX } from '../model/theme';
import { buildWorkspaceTree, workspaceAncestors } from '../model/workspaceTree';

const size = (value) => {
  const number = Number(value || 0);
  if (!number) return '';
  return number < 1024 ? `${number} Б` : `${Math.round(number / 1024)} КБ`;
};

/** Button disclosures in nested lists: native Tab/Enter/Space, not a partial ARIA tree. */
export function WorkspaceTree({ entries = [], selected, onSelect, disabled, canSelect = () => true,
  basePath = '', scrollable = true, label = 'Файлы рабочего места', onMove, onInspect, moveDisabled = false }) {
  const id = useId();
  const nodes = useMemo(() => buildWorkspaceTree(entries, basePath), [entries, basePath]);
  const [expanded, setExpanded] = useState(() => new Set(workspaceAncestors(selected, basePath)));
  const [inspected, setInspected] = useState('');
  const source = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [dropTarget, setDropTarget] = useState(null);
  const movable = Boolean(onMove) && !disabled && !moveDisabled;
  const clearDrag = () => { source.current = null; setDragging(false); setDropTarget(null); };
  useEffect(() => { source.current = null; setDragging(false); setDropTarget(null); }, [entries, basePath, movable]);
  const destinationFor = folder => {
    const item = source.current;
    if (!movable || !item || folder === item.path || folder.startsWith(`${item.path}/`)) return null;
    const destination = [folder, item.path.split('/').pop()].filter(Boolean).join('/');
    return destination !== item.path ? destination : null;
  };
  const over = (event, folder) => {
    event.stopPropagation();
    if (!source.current) return;
    const valid = destinationFor(folder) !== null;
    if (valid) event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = valid ? 'move' : 'none';
    setDropTarget(valid ? folder : null);
  };
  const drop = (event, folder) => {
    event.stopPropagation();
    const destination = destinationFor(folder);
    const item = source.current;
    if (destination !== null) event.preventDefault();
    clearDrag();
    if (item && destination !== null) onMove?.(item, destination);
  };
  const belongs = (path) => path && (!basePath || path.startsWith(`${basePath}/`))
    && entries.some((item) => item.path === path || item.path?.startsWith(`${path}/`));
  const inspectedPath = belongs(inspected) ? inspected : belongs(selected) ? selected : '';
  useEffect(() => {
    setExpanded((current) => new Set([...current, ...workspaceAncestors(selected, basePath)]));
  }, [selected, basePath]);
  const rows = (items, depth = 0) => <Box as="ul" listStyleType="none" m={0} p={0}>
      {items.map((item) => {
        const isFile = item.type === 'file';
        const selectable = isFile && canSelect(item);
        const open = expanded.has(item.path);
        const childrenId = `${id}-${encodeURIComponent(item.path)}`;
        return <Box as="li" key={item.path}>
          <HStack as="button" type="button" w="full" data-testid={isFile ? 'workspace-file' : 'workspace-directory'}
            data-workspace-path={item.path} aria-label={item.path}
            aria-expanded={!isFile ? open : undefined} aria-controls={!isFile ? childrenId : undefined}
            disabled={isFile && (disabled || !selectable)} aria-pressed={isFile ? selected === item.path : undefined}
            title={isFile && !selectable ? `${item.path} · Материал, не текстовый исходник` : item.path}
            onFocus={() => { setInspected(item.path); onInspect?.({ path: item.path, type: isFile ? 'file' : 'dir' }); }}
            draggable={movable}
            onDragStart={event => {
              if (!movable) { event.preventDefault(); return; }
              source.current = { path: item.path, type: isFile ? 'file' : 'dir' };
              setDragging(true);
              if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('application/x-gpthub-tree-path', item.path);
              }
            }}
            onDragEnd={clearDrag}
            onDragOver={event => over(event, isFile ? item.path.split('/').slice(0, -1).join('/') : item.path)}
            onDrop={event => drop(event, isFile ? item.path.split('/').slice(0, -1).join('/') : item.path)}
            onClick={() => {
              setInspected(item.path); onInspect?.({ path: item.path, type: isFile ? 'file' : 'dir' });
              if (isFile) { if (selectable && !disabled) onSelect?.(item.path); }
              else setExpanded((current) => {
                const next = new Set(current);
                if (next.has(item.path)) next.delete(item.path); else next.add(item.path);
                return next;
              });
            }}
            pl={`${8 + Math.min(depth, 8) * 14}px`} pr={2} py={1} spacing={2} minH="30px" minW={0}
            textAlign="left" borderRadius={borderRadius.sm}
            bg={selected === item.path ? WORK_HUB_THEME.accentSoft : 'transparent'}
            outline={dropTarget === item.path ? `2px solid ${colors.border.focus}` : undefined}
            outlineOffset="-2px"
            cursor={isFile && (disabled || !selectable) ? 'default' : 'pointer'}
            _hover={{ bg: WORK_HUB_THEME.panelHover }} _active={{ bg: WORK_HUB_THEME.accentSoft }}
            _disabled={{ cursor: 'default', _hover: { bg: 'transparent' } }}
            _focusVisible={{ outline: `2px solid ${colors.border.focus}`, outlineOffset: '-2px' }}>
            <Icon as={isFile ? FiFileText : open ? FiChevronDown : FiChevronRight} boxSize="12px" flexShrink={0}
              color={isFile ? colors.fg[4] : colors.fg[3]} />
            {!isFile && <Icon as={FiFolder} boxSize="14px" color={colors.iris[300]} flexShrink={0} />}
            <Text as="span" flex="1" minW={0} overflowWrap="anywhere" fontSize="12px" lineHeight={1.45} color={colors.fg[2]}>{item.name}</Text>
            {isFile && <Text as="span" flexShrink={0} fontSize="10px" color={colors.fg[3]}>{size(item.size)}</Text>}
          </HStack>
          {!isFile && <Box id={childrenId} hidden={!open}>
            {open && (item.children.length ? rows(item.children, depth + 1)
              : <Text pl={`${36 + Math.min(depth, 8) * 14}px`} py={1} fontSize="11px" color={colors.fg[4]}>{item.incomplete ? 'Содержимое загружено не полностью' : 'Папка пуста'}</Text>)}
          </Box>}
        </Box>;
      })}
  </Box>;
  return <VStack align="stretch" spacing={1} minW={0} h={scrollable ? 'full' : undefined}>
    <Box role="region" aria-label={label} overflowY={scrollable ? 'auto' : undefined}
      position="relative" onDragOver={event => over(event, basePath)} onDrop={event => drop(event, basePath)}
      onDragLeave={event => { if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setDropTarget(null); }}
      outline={dropTarget === basePath ? `2px solid ${colors.border.focus}` : undefined} outlineOffset="-2px"
      flex={scrollable ? '1' : undefined} minH={0} sx={WORK_SCROLLBAR_SX}>
      {nodes.length ? rows(nodes) : <Text px={3} py={4} fontSize="12px" color={colors.fg[4]}>Каталог пока пуст.</Text>}
      {dragging && <Text role="status" position="sticky" bottom={0} px={3} py={2}
        pointerEvents="none" bg={colors.bg.menu} color={colors.fg[3]} fontSize="11px">В папку — на её строку; в корень — на свободное место.</Text>}
    </Box>
    {inspectedPath && <Text px={2} pt={1} fontSize="10px" lineHeight={1.4} color={colors.fg[4]}
      data-testid="workspace-inspected-path" overflowWrap="anywhere">{inspectedPath}</Text>}
  </VStack>;
}
