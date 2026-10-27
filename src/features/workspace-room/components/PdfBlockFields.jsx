import { useState } from 'react';
import { Box, Button, HStack, Input, Text, VStack } from '@chakra-ui/react';
import AppTextarea from '@shared/controls/AppTextarea';
import AppSelect from '@shared/controls/AppSelect';
import { colors } from '@theme/tokens';
import { PdfCitationSource } from './PdfCitationSource';

const prose = {
  variant: 'unstyled', borderRadius: 0, minH: '28px', px: 0, py: 1,
  fontSize: '15px', fontWeight: 400, lineHeight: 1.65, color: colors.fg[2],
  _focusVisible: { boxShadow: `0 1px 0 ${colors.border.focus}` },
  _placeholder: { color: colors.fg[4] },
};

export function PdfBlockFields({ block, onChange, images = [], sources }) {
  const patch = (field, value) => onChange({ ...block, [field]: value });
  const [sectionBody, setSectionBody] = useState(Boolean(block.text));
  const showSectionBody = sectionBody || Boolean(block.text);
  const heading = block.kind === 'section';
  const text = (label, placeholder, fontFamily) => <AppTextarea {...prose} autoGrow maxAutoHeight={320}
    aria-label={label} value={block.text || ''} placeholder={placeholder} fontFamily={fontFamily}
    onChange={(event) => patch('text', event.target.value)} />;
  return <VStack align="stretch" spacing={2} minW={0}>
    {['section', 'slide', 'figure', 'table'].includes(block.kind) && <AppTextarea {...prose} autoGrow
      aria-label={`Заголовок блока ${block.block_id}`} value={block.title || ''}
      placeholder={heading ? 'Заголовок раздела' : 'Название или подпись'}
      color={heading ? colors.fg[1] : colors.fg[2]}
      fontSize={heading ? block.level === 1 ? '21px' : '18px' : '15px'} fontWeight={600} lineHeight={1.4}
      onChange={(event) => patch('title', event.target.value)} />}
    {heading && !showSectionBody && <Button alignSelf="start" size="document" variant="ghost" px={0}
      fontWeight={400} color={colors.fg[3]} onClick={() => setSectionBody(true)}>Добавить текст раздела</Button>}
    {block.kind === 'table' ? <><Box overflowX="auto"><Box as="table" w="full" fontSize="13px">
      <thead><tr>{(block.columns || []).map((column, index) => <th key={index}><Input size="sm"
        aria-label={`Название столбца ${index + 1}`} value={column} onChange={(event) => {
          const columns = [...block.columns]; columns[index] = event.target.value; patch('columns', columns);
        }} /></th>)}</tr></thead>
      <tbody>{(block.rows || []).map((row, r) => <tr key={r}>{row.map((cell, c) => <td key={c}>
        <Input size="sm" aria-label={`Ячейка ${r + 1}, ${c + 1}`} value={cell} onChange={(event) => {
          const rows = block.rows.map((item) => [...item]); rows[r][c] = event.target.value; patch('rows', rows);
        }} /></td>)}</tr>)}</tbody>
    </Box></Box><HStack spacing={2}>
      <Button size="document" variant="ghost" isDisabled={(block.rows || []).length >= 200}
        onClick={() => patch('rows', [...(block.rows || []), (block.columns || []).map(() => '')])}>Добавить строку</Button>
      <Button size="document" variant="ghost" isDisabled={(block.columns || []).length >= 24}
        onClick={() => onChange({ ...block, columns: [...(block.columns || []), `Столбец ${(block.columns || []).length + 1}`],
          rows: (block.rows || []).map((row) => [...row, '']) })}>Добавить столбец</Button>
    </HStack></> : block.kind === 'signature' ? <HStack align="start" flexWrap="wrap">
      {[0, 1].map((index) => <Input key={index} flex="1" minW="120px" size="sm"
        aria-label={`Сторона подписи ${index + 1}`} value={block.items?.[index] || ''} placeholder={`Сторона ${index + 1}`}
        onChange={(event) => { const items = [...(block.items || ['', ''])]; items[index] = event.target.value; patch('items', items); }} />)}
    </HStack> : block.kind === 'list' ? <AppTextarea {...prose} autoGrow aria-label={`Элементы списка ${block.block_id}`}
      placeholder="Каждый пункт — с новой строки" value={(block.items || []).join('\n')}
      onChange={(event) => patch('items', event.target.value.split('\n'))} />
      : block.kind === 'figure' ? <>
        <ProjectImage block={block} images={images} onChange={(value) => patch('asset_path', value)} />
      </> : block.kind === 'citation' ? <>
        {sources ? <PdfCitationSource inventory={sources} value={block.source_id}
          label="Источник цитаты" ariaLabel={`Источник блока ${block.block_id}`} onChange={(value) => patch('source_id', Number(value))} />
          : <Text fontSize="12px" color={colors.fg[3]}>Источник проекта: {block.source_id}</Text>}
        {text(`Текст блока ${block.block_id}`, 'Текст перед ссылкой')}
      </> : !heading || showSectionBody ? text(`Текст блока ${block.block_id}`, block.kind === 'equation' ? 'Формула LaTeX' : 'Начните писать…', block.kind === 'equation' ? 'mono' : undefined) : null}
    {block.kind === 'slide' && <AppTextarea {...prose} autoGrow aria-label={`Тезисы слайда ${block.block_id}`}
      placeholder="Тезисы слайда: каждый с новой строки" value={(block.items || []).join('\n')}
      onChange={(event) => patch('items', event.target.value.split('\n'))} />}
    {block.kind === 'slide' && <ProjectImage block={block} images={images} onChange={(value) => patch('asset_path', value)} />}
  </VStack>;
}

function ProjectImage({ block, images, onChange }) {
  const unavailable = block.asset_path && !images.some((item) => item.value === block.asset_path);
  const options = unavailable ? [...images, { value: block.asset_path, label: `${block.asset_path} · нет в списке`, isDisabled: true }] : images;
  return <Box minW={0}>
    <Text fontSize="11px" color={colors.fg[3]} mb={1}>Изображение проекта</Text>
    <AppSelect size="document" ariaLabel={`Изображение блока ${block.block_id}`} options={options}
      value={block.asset_path || ''} isClearable placeholder="Без изображения" onChange={(value) => onChange(value || '')} />
    {unavailable && <Text role="status" fontSize="11px" color={colors.warning} mt={1}>
      Файл не найден в текущем списке. Ссылка сохранена; проверьте «Материалы».
    </Text>}
    {!images.length && <Text fontSize="11px" color={colors.fg[3]} mt={1}>
      Добавьте PNG, JPEG или PDF через Библиотеку в левой панели, выбрав текущий PDF-проект.
    </Text>}
  </Box>;
}
