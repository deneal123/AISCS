import React, { useMemo } from 'react';
import { Box, IconButton, VisuallyHidden } from '@chakra-ui/react';
import ComposerOption from './app-select/ComposerOption';
import ReactSelect, { components } from 'react-select';
import { FiX } from '@shared/icons';
import { borderRadius, colors, documentControls, layers, shadows, typography } from '@theme/tokens';
import { useListboxKeyboardFocus } from '../hooks/useListboxKeyboardFocus';

const controlHeight = { xs: 30, sm: 34, md: 40, touch: 44 };

const optionValue = (option) => String(option?.value ?? '');

// Keep the library keyboard owner without an empty search box in simple panels.
function QuietControl(props) {
  return <VisuallyHidden><components.Control {...props} /></VisuallyHidden>;
}

/** Product-owned select with a rich, ordered-multi composer presentation.
 * Ordinary form popups are portalled; composer lists stay inside ChoicePanel.
 * react-select owns listbox keyboard and selection semantics in both variants. */
export default function AppSelect({
  value,
  options = [],
  onChange,
  placeholder = 'Выбрать…',
  size = 'sm',
  isDisabled = false,
  isClearable = false,
  ariaLabel,
  inputId,
  name,
  maxW,
  w = '100%',
  menuPlacement = 'auto',
  menuPortalTarget,
  presentation = 'default',
  isMulti = false,
  isSearchable,
  formatOptionLabel,
  isOptionDisabled,
  inputValue,
  onInputChange,
  onClose,
  autoFocus = false,
  showOptionHints = false,
  getOptionHint,
  noOptionsMessage = 'Нет вариантов',
  ...boxProps
}) {
  const iconColumn = presentation === 'composer-icon-column';
  const personaPalette = presentation === 'composer-persona-icons';
  const iconPalette = presentation === 'composer-icons' || iconColumn || personaPalette;
  const keyboardFocus = useListboxKeyboardFocus(iconPalette);
  const densePanel = presentation === 'composer-compact';
  const panel = presentation === 'composer' || densePanel || iconPalette;
  const flatOptions = useMemo(() => options.flatMap((option) => option.options || [option]), [options]);
  const searchable = isSearchable ?? flatOptions.length > 8;
  const quietControl = panel && !searchable;
  const selected = useMemo(
    () => isMulti
      ? (Array.isArray(value) ? value : []).map((id) => flatOptions.find((option) => optionValue(option) === String(id))).filter(Boolean)
      : flatOptions.find((option) => optionValue(option) === String(value ?? '')) || null,
    [flatOptions, value, isMulti],
  );
  const documentDensity = size === 'document';
  const height = documentDensity ? documentControls.desktop : controlHeight[size] || controlHeight.sm;
  // A modal can deliberately keep its short menu inside the focus/stacking
  // owner. Explicit null means inline; omitted still uses the document portal.
  const portalTarget = menuPortalTarget === undefined
    ? (typeof document === 'undefined' ? undefined : document.body) : menuPortalTarget;

  const styles = useMemo(() => ({
    control: (base, state) => ({
      ...base,
      minHeight: height, height,
      ...(documentDensity ? { '@media (max-width: 47.99em)': { minHeight: documentControls.mobile, height: documentControls.mobile } } : {}),
      background: colors.bg.input,
      borderColor: state.isFocused ? colors.border.focus : colors.border.medium,
      borderRadius: borderRadius.sm,
      boxShadow: state.isFocused ? `0 0 0 1px ${colors.border.focus}` : 'none',
      cursor: isDisabled ? 'not-allowed' : 'pointer',
      transition: 'border-color 120ms ease, background 120ms ease',
      ':hover': { borderColor: state.isFocused ? colors.border.focus : colors.border.strong },
    }),
    valueContainer: (base) => ({ ...base, height, padding: '0 10px', paddingRight: panel && inputValue ? 44 : 10, minWidth: 0,
      ...(documentDensity ? { '@media (max-width: 47.99em)': { height: documentControls.mobile, padding: '0 8px' } } : {}) }),
    singleValue: (base) => ({ ...base, color: colors.fg[1], fontSize: documentDensity ? documentControls.desktopFont : '13px',
      ...(documentDensity ? { '@media (max-width: 47.99em)': { fontSize: documentControls.mobileFont } } : {}) }),
    placeholder: (base) => ({ ...base, color: colors.fg[3], fontSize: documentDensity ? documentControls.desktopFont : '13px',
      ...(documentDensity ? { '@media (max-width: 47.99em)': { fontSize: documentControls.mobileFont } } : {}) }),
    input: (base) => ({ ...base, color: colors.fg[1], fontSize: '13px', margin: 0 }),
    indicatorsContainer: (base) => ({ ...base, height,
      ...(documentDensity ? { '@media (max-width: 47.99em)': { height: documentControls.mobile } } : {}) }),
    indicatorSeparator: () => ({ display: 'none' }),
    dropdownIndicator: (base, state) => ({
      ...base,
      padding: '0 8px',
      color: state.isFocused ? colors.blue[300] : colors.fg[4],
    }),
    clearIndicator: (base) => ({ ...base, padding: '0 4px', color: colors.fg[4] }),
    menuPortal: (base) => ({ ...base, zIndex: layers.dropdown }),
    menu: (base) => ({
      ...base,
      ...(panel ? { position: 'relative', top: 'auto' } : {}),
      overflow: 'hidden',
      background: colors.bg.menu,
      border: panel ? 'none' : `1px solid ${colors.border.strong}`,
      borderRadius: borderRadius.md,
      boxShadow: panel ? 'none' : shadows.menu,
      marginTop: quietControl ? 0 : 6,
    }),
    menuList: (base) => ({ ...base, maxHeight: iconColumn || personaPalette ? 'var(--choice-list-height, 264px)' : iconPalette ? 120 : panel ? 'var(--choice-list-height, 320px)' : Math.min(280, base.maxHeight || 280), padding: 4,
      scrollbarGutter: iconPalette ? 'auto' : 'stable',
      ...(iconPalette ? { display: 'grid', gridTemplateColumns: personaPalette ? 'repeat(3, 44px)' : iconColumn ? '44px' : 'repeat(auto-fit, 44px)', justifyContent: 'center', gap: personaPalette ? 8 : 4 } : {}) }),
    option: (base, state) => ({
      ...base,
      background: state.isSelected
        ? colors.accent.subtle
        : state.isFocused && (!iconPalette || keyboardFocus.visible) ? colors.surface.tint3 : 'transparent',
      color: state.isSelected ? colors.blue[100] : colors.fg[1],
      cursor: state.isDisabled ? 'not-allowed' : 'pointer',
      opacity: state.isDisabled ? 0.5 : 1,
      padding: iconPalette ? 0 : densePanel ? '6px 8px' : panel ? '10px 12px' : base.padding,
      ...(densePanel ? { minHeight: 44, display: 'flex', alignItems: 'center' } : {}),
      ...(iconPalette ? { minHeight: 44, display: 'flex', justifyContent: 'center', alignItems: 'center', position: 'relative',
        // The library's active option can outlive pointer hover. Only keyboard
        // navigation gets a focus ring; selection remains value-owned.
        outline: state.isFocused && keyboardFocus.visible ? `2px solid ${colors.border.focus}` : 'none', outlineOffset: -2,
        ':hover': { background: state.isSelected ? colors.accent.subtle : colors.surface.tint3 },
      } : {}),
      borderRadius: borderRadius.sm,
      fontSize: '13px',
      ':active': { background: colors.accent.pressSoft },
    }),
    noOptionsMessage: (base) => ({ ...base, color: colors.fg[3], fontSize: '12px' }),
    group: (base) => ({ ...base, ...(densePanel ? { paddingTop: 2, paddingBottom: 2 } : {}) }),
    groupHeading: (base) => ({ ...base, color: colors.fg[3], fontSize: '11px', fontWeight: 600, textTransform: 'none',
      padding: densePanel ? '4px 8px' : '8px 12px', ...(densePanel ? { marginBottom: 0 } : {}) }),
  }), [height, documentDensity, isDisabled, panel, densePanel, iconPalette, iconColumn, personaPalette, inputValue, quietControl, keyboardFocus.visible]);

  return (
    <Box position="relative" w={w} maxW={maxW} minW={0} fontFamily={typography.fontFamily.primary} {...(iconPalette ? keyboardFocus.props : {})} {...boxProps}>
      <ReactSelect
        inputId={inputId}
        name={name}
        aria-label={ariaLabel}
        value={selected}
        options={options}
        onChange={(option) => onChange?.(isMulti ? (option || []).map((item) => item.value) : option?.value ?? '')}
        placeholder={placeholder}
        isDisabled={isDisabled}
        isClearable={isClearable}
        isSearchable={searchable}
        isMulti={isMulti}
        hideSelectedOptions={false}
        blurInputOnSelect={panel ? false : undefined}
        closeMenuOnSelect={!isMulti && !panel}
        menuIsOpen={panel ? true : undefined}
        controlShouldRenderValue={!panel}
        tabSelectsValue={!panel}
        backspaceRemovesValue={!panel}
        components={panel ? { DropdownIndicator: null, IndicatorSeparator: null, Option: ComposerOption,
          ...(quietControl ? { Control: QuietControl } : {}) } : undefined}
        menuPortalTarget={panel ? undefined : portalTarget}
        menuPosition={panel || !portalTarget ? 'absolute' : 'fixed'}
        menuPlacement={menuPlacement}
        formatOptionLabel={formatOptionLabel}
        iconPalette={iconPalette}
        showOptionHints={showOptionHints || (personaPalette && keyboardFocus.visible)}
        getOptionHint={getOptionHint}
        isOptionDisabled={isOptionDisabled}
        inputValue={inputValue}
        onInputChange={onInputChange}
        autoFocus={autoFocus}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && panel && !event.nativeEvent?.isComposing) {
            event.preventDefault();
            event.stopPropagation();
            onClose?.();
          }
        }}
        noOptionsMessage={() => noOptionsMessage}
        screenReaderStatus={({ count }) => `Доступно вариантов: ${count}`}
        ariaLiveMessages={{
          guidance: () => 'Стрелки вверх и вниз — выбор. Enter — подтвердить. Escape — закрыть.',
          onFilter: ({ resultsMessage }) => resultsMessage,
          onFocus: ({ label, isDisabled: disabled, focused }) => `${label || 'Вариант'}${disabled ? ', недоступен' : ''}${getOptionHint?.(focused) ? `. ${getOptionHint(focused)}` : iconPalette && focused?.hint ? `. ${focused.hint}` : ''}`,
          onChange: ({ label, action }) => action === 'clear' ? 'Выбор очищен'
            : `${label || 'Вариант'}: ${['deselect-option', 'remove-value', 'pop-value'].includes(action) ? 'снят' : 'выбран'}`,
        }}
        styles={styles}
      />
      {panel && inputValue && (
        <IconButton aria-label="Очистить поиск" icon={<FiX />} variant="ghost" position="absolute"
          right={0} top={0} h={`${height}px`} w={`${height}px`} minW={0}
          onClick={() => { onInputChange?.('', { action: 'input-change' }); document.getElementById(inputId)?.focus(); }} />
      )}
    </Box>
  );
}
