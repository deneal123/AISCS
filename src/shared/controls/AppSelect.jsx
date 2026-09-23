import React, { useMemo } from 'react';
import { Box } from '@chakra-ui/react';
import ReactSelect from 'react-select';
import { borderRadius, colors, layers, shadows, typography } from '@theme/tokens';

const controlHeight = { xs: 30, sm: 34, md: 40 };

const optionValue = (option) => String(option?.value ?? '');

/** Product-owned single select. The popup is portalled so drawers and clipped
 * workbench panels cannot cut it off; react-select owns listbox keyboard logic. */
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
  ...boxProps
}) {
  const selected = useMemo(
    () => options.find((option) => optionValue(option) === String(value ?? '')) || null,
    [options, value],
  );
  const height = controlHeight[size] || controlHeight.sm;
  const portalTarget = typeof document === 'undefined' ? undefined : document.body;

  const styles = useMemo(() => ({
    control: (base, state) => ({
      ...base,
      minHeight: height,
      height,
      background: colors.bg.input,
      borderColor: state.isFocused ? colors.border.focus : colors.border.medium,
      borderRadius: borderRadius.sm,
      boxShadow: state.isFocused ? `0 0 0 1px ${colors.border.focus}` : 'none',
      cursor: isDisabled ? 'not-allowed' : 'pointer',
      transition: 'border-color 120ms ease, background 120ms ease',
      ':hover': { borderColor: state.isFocused ? colors.border.focus : colors.border.strong },
    }),
    valueContainer: (base) => ({ ...base, height, padding: '0 10px', minWidth: 0 }),
    singleValue: (base) => ({ ...base, color: colors.fg[1], fontSize: '13px' }),
    placeholder: (base) => ({ ...base, color: colors.fg[3], fontSize: '13px' }),
    input: (base) => ({ ...base, color: colors.fg[1], fontSize: '13px', margin: 0 }),
    indicatorsContainer: (base) => ({ ...base, height }),
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
      overflow: 'hidden',
      background: colors.bg.menu,
      border: `1px solid ${colors.border.strong}`,
      borderRadius: borderRadius.md,
      boxShadow: shadows.menu,
      marginTop: 6,
    }),
    menuList: (base) => ({ ...base, maxHeight: 280, padding: 4 }),
    option: (base, state) => ({
      ...base,
      background: state.isSelected
        ? colors.accent.subtle
        : state.isFocused ? colors.surface.tint3 : 'transparent',
      color: state.isSelected ? colors.blue[100] : colors.fg[1],
      cursor: 'pointer',
      borderRadius: borderRadius.sm,
      fontSize: '13px',
      ':active': { background: colors.accent.pressSoft },
    }),
    noOptionsMessage: (base) => ({ ...base, color: colors.fg[3], fontSize: '12px' }),
  }), [height, isDisabled]);

  return (
    <Box w={w} maxW={maxW} minW={0} fontFamily={typography.fontFamily.primary} {...boxProps}>
      <ReactSelect
        inputId={inputId}
        name={name}
        aria-label={ariaLabel}
        value={selected}
        options={options}
        onChange={(option) => onChange?.(option?.value ?? '')}
        placeholder={placeholder}
        isDisabled={isDisabled}
        isClearable={isClearable}
        isSearchable={options.length > 8}
        menuPortalTarget={portalTarget}
        menuPosition="fixed"
        menuPlacement={menuPlacement}
        noOptionsMessage={() => 'Нет вариантов'}
        styles={styles}
      />
    </Box>
  );
}
