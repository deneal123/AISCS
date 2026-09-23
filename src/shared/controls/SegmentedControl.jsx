import { useCallback, useRef } from 'react';
import { HStack, Button } from '@chakra-ui/react';
import { colors, typography } from '@theme/tokens';

// Тинт стеклянной панели-контейнера (раньше брался из CHAT_THEME.panelHover).
// Держим значение здесь, чтобы shared-примитив не зависел от feature-темы чата.
const PANEL_HOVER = colors.glass.hover;

// Размерные пресеты: pill-вкладки (md), диапазон/фильтр (sm).
const SIZES = {
  sm: { h: '26px', px: 3, fontSize: '12px' },
  md: { h: '32px', px: 4, fontSize: '13px' },
};

/**
 * Сегментированный pill-контрол — единый «язык переключателей» приложения:
 * стеклянный full-radius контейнер, активный сегмент подсвечен accent-пилюлей.
 * Годится для вкладок страницы, селектора диапазона, фильтров.
 *
 * Доступность: это настоящий tablist — roving tabIndex (в таб-порядке только
 * активный сегмент) + переключение стрелками/Home/End, как требует паттерн WAI-ARIA.
 * Если контрол управляет не панелями, а выборкой (фильтр, диапазон), передайте
 * `as="group"` — тогда сегменты объявляются кнопками с aria-pressed.
 *
 * @param {{ key: string, label: string }[]} options
 * @param {string} value  ключ активного сегмента
 * @param {(key: string) => void} onChange
 * @param {boolean} [disabled]
 * @param {'sm'|'md'} [size]
 * @param {'tabs'|'group'} [as]  семантика: вкладки (по умолчанию) или группа кнопок
 * @param {string} [ariaLabel]  имя набора вкладок для скринридера
 */
export default function SegmentedControl({
  options = [],
  value,
  onChange,
  disabled = false,
  size = 'sm',
  as = 'tabs',
  ariaLabel,
  ...rest
}) {
  const s = SIZES[size] || SIZES.sm;
  const isTabs = as === 'tabs';
  const listRef = useRef(null);

  // Стрелки/Home/End двигают фокус и выбор по сегментам — без этого клавиатурный
  // пользователь может дойти табом только до активной вкладки и застрять.
  const onKeyDown = useCallback(
    (event) => {
      if (!isTabs || disabled) return;
      const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
      const index = options.findIndex((o) => o.key === value);
      let next = null;
      if (event.key in keys) next = (index + keys[event.key] + options.length) % options.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = options.length - 1;
      if (next === null || !options[next]) return;
      event.preventDefault();
      onChange?.(options[next].key);
      listRef.current?.querySelectorAll('[role="tab"]')[next]?.focus();
    },
    [isTabs, disabled, options, value, onChange],
  );

  return (
    <HStack
      ref={listRef}
      spacing={1}
      p={1}
      bg={PANEL_HOVER}
      borderRadius="full"
      border={`1px solid ${colors.border.subtle}`}
      w="auto"
      role={isTabs ? 'tablist' : 'group'}
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      {...rest}
    >
      {options.map((opt) => {
        const active = opt.key === value;
        return (
          <Button
            key={opt.key}
            variant="unstyled"
            px={s.px}
            h={s.h}
            minW="auto"
            borderRadius="full"
            fontSize={s.fontSize}
            fontWeight="600"
            fontFamily={typography.fontFamily.mono}
            letterSpacing="0.01em"
            display="inline-flex"
            alignItems="center"
            justifyContent="center"
            // Неактивные подписи были на fg[4] (3.5:1) — для интерактивного
            // контрола это ниже нормы читаемости; берём fg[3] (6.6:1).
            color={active ? colors.accent.subtleText : colors.fg[3]}
            bg={active ? colors.accent.subtle : 'transparent'}
            transition="color 160ms ease, background 160ms ease"
            _hover={{ color: active ? colors.accent.subtleText : colors.fg[2] }}
            onClick={() => onChange?.(opt.key)}
            isDisabled={disabled}
            role={isTabs ? 'tab' : undefined}
            aria-selected={isTabs ? active : undefined}
            aria-pressed={isTabs ? undefined : active}
            tabIndex={isTabs && !active ? -1 : 0}
          >
            {opt.label}
          </Button>
        );
      })}
    </HStack>
  );
}
