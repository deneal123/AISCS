import React from "react";
import { Button } from "@chakra-ui/react";
import { useMagnetic } from "@hooks/useMagnetic";
import ActionLink from "./ActionLink";

/**
 * Chakra Button с магнитным притяжением к курсору. У эталона магнитятся ВСЕ
 * кнопки (useMagnetic(5) прямо в их Button), у нас это было только на hero/CTA
 * через ручной ref — отсюда «кнопки ощущаются иначе».
 *
 * Хук сам no-op под prefers-reduced-motion и на тач-устройствах.
 * Живёт в shared/controls (не в shared/ui) — фичам запрещён импорт из `ui`.
 */
export default function MagneticButton({
  strength = 5,
  to,
  href,
  as: _legacyAs,
  onClick,
  type = "button",
  ...props
}) {
  void _legacyAs;
  const magneticRef = useMagnetic(strength);
  if (to || href) {
    return (
      <ActionLink
        ref={magneticRef}
        to={to}
        href={href}
        onClick={onClick}
        {...props}
      />
    );
  }
  return <Button ref={magneticRef} type={type} onClick={onClick} {...props} />;
}
