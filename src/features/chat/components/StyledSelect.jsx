import AppSelect from '@shared/controls/AppSelect';

/**
 * Стилизованный выпадающий список в дизайне чата (Chakra Menu) — замена нативному
 * нативному браузерному select, который рендерит OS-дропдаун. Единый вид с
 * остальными меню (ComposerModeSelector, ModelSelector). options: [{ value, label }].
 */
export default function StyledSelect({ value, options = [], onChange, placeholder = 'Выбрать…', size = 'sm' }) {
  return (
    <AppSelect
      value={value}
      options={options}
      onChange={onChange}
      placeholder={placeholder}
      size={size}
      ariaLabel={placeholder}
    />
  );
}
