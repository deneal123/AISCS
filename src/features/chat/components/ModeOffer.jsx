import { useEffect, useState } from 'react';
import { Box, Button, Icon, Stack, Text } from '@chakra-ui/react';
import { FiZap } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import { CHAT_THEME } from '../constants/theme';
import { autoModeReasonLabel } from '../utils/autoModeReason';

/**
 * Предложение дорогого режима: «Авто» решил, что он подошёл бы, но запускать сам не стал.
 *
 * 🔴 Глубокое исследование и презентация стоят тысячи кредитов. Ошибка решателя там — не
 * «ответ вышел хуже», а списанные деньги, которых человек не просил. Поэтому ответ даётся
 * обычным режимом, а дорогой предлагается кнопкой: решает человек.
 *
 * 🔴 ЖИВЁТ ОГРАНИЧЕННОЕ ВРЕМЯ, И ОТСЧЁТ — СЕРВЕРНЫЙ. Здесь только ОТОБРАЖЕНИЕ остатка:
 * срок задан парой `offered_at`/`expires_in_sec`, выданной сервером, а «просрочено»
 * решает он же на отдаче истории (`domain/mode_offer.py`). Таймер, живущий в браузере,
 * переживают перезагрузкой, второй вкладкой и сменой системного времени — решение о
 * тысячах кредитов от этого зависеть не может.
 *
 * ⚠️ Молчание = ОТКАЗ. Автозапуск по таймауту списал бы тысячи кредитов у человека,
 * который отошёл от экрана. Отказ при этом ВИДЕН: карточка не исчезает, а превращается в
 * строку «отклонён по таймауту» — исчезнувшая неотличима от «предложения не было».
 */
const DEFAULT_TTL_SEC = 30;

function secondsLeftOf(offer, now) {
  const startedAt = Date.parse(offer?.offered_at || '');
  // Без серверной метки живым не считаем: иначе «бессрочная кнопка» вернулась бы через
  // любую запись без срока.
  if (!Number.isFinite(startedAt)) return 0;
  const ttl = Number(offer?.expires_in_sec) > 0 ? Number(offer.expires_in_sec) : DEFAULT_TTL_SEC;
  return Math.max(0, Math.ceil((startedAt + ttl * 1000 - now) / 1000));
}

function ModeOffer({ offer, onRun, disabled }) {
  const expiredByServer = Boolean(offer?.expired);
  const [submittedLocally, setSubmittedLocally] = useState(false);
  const [left, setLeft] = useState(() => (expiredByServer ? 0 : secondsLeftOf(offer, Date.now())));
  const accepted = offer?.status === 'accepted';

  useEffect(() => {
    if (expiredByServer || accepted || submittedLocally) {
      setLeft(0);
      return undefined;
    }
    setLeft(secondsLeftOf(offer, Date.now()));
    const timer = setInterval(() => setLeft(secondsLeftOf(offer, Date.now())), 1000);
    return () => clearInterval(timer);
  }, [offer, expiredByServer, accepted, submittedLocally]);

  if (!offer?.mode) return null;

  const label = offer.label || offer.mode;
  const estimatedCredits = Number(offer.estimated_credits);
  const hasExactEstimate = Number.isFinite(estimatedCredits) && estimatedCredits > 0;
  const formattedEstimate = hasExactEstimate
    ? Math.round(estimatedCredits).toLocaleString('ru-RU')
    : '';
  // ⚠️ Слово подбираем по РОДУ предложения. «Режим „просмотр видео“» неверно дважды: это
  // не режим, и ответ без него дан не «обычным путём», а просто без просмотра ролика.
  // Формулировка, не совпадающая с тем, что произошло, читается как поломка.
  const isTool = offer.offer_kind === 'tool';
  if (accepted) {
    return (
      <Text fontSize="11.5px" color={colors.text.secondary} mt={1}>
        Подтверждено, запуск начат.
      </Text>
    );
  }
  if (submittedLocally) {
    return (
      <Text fontSize="11.5px" color={colors.text.secondary} mt={1}>
        Подтверждение отправлено. Ожидаю запуск.
      </Text>
    );
  }
  if (expiredByServer || left <= 0) {
    return (
      <Text fontSize="11.5px" color={colors.text.tertiary} mt={1}>
        {offer.mode === 'expensive_run'
          ? 'Срок подтверждения истёк, запуск не выполнялся.'
          : isTool
            ? `«${label}» отклонён по таймауту — ответ дан без него.`
            : `Режим «${label}» отклонён по таймауту — ответ дан обычным путём.`}
      </Text>
    );
  }

  return (
    <Box
      mt={2}
      px={3}
      py={2.5}
      borderRadius={borderRadius.md}
      bg={CHAT_THEME.panelBg}
      border={`1px solid ${colors.accent.subtleBorder}`}
    >
      <Stack direction={{ base: 'column', sm: 'row' }} spacing={2} align="flex-start">
        <Icon as={FiZap} boxSize="14px" color={colors.iris[300]} mt="2px" flexShrink={0} />
        <Box flex="1" minW={0}>
          <Text fontSize="12.5px" fontWeight="600" color={colors.text.primary}>
            {isTool ? `Могу включить: ${label}` : `Подошёл бы режим «${label}»`}
          </Text>
          {offer.reason_code && (
            <Text fontSize="11.5px" color={colors.text.tertiary} mt={0.5} lineHeight="1.4">
              {autoModeReasonLabel(offer.reason_code)}
            </Text>
          )}
          <Text fontSize="11px" color={colors.text.tertiary} mt={1}>
            {hasExactEstimate
              ? `Максимальная оценка — ${formattedEstimate} кредитов. На решение — ${left} с.`
              : isTool
                ? `Это платная операция, заметно дороже обычного ответа. На решение — ${left} с.`
                : `Это платный режим, заметно дороже обычного ответа. На решение — ${left} с.`}
          </Text>
        </Box>
        <Button
          size="sm"
          flexShrink={0}
          minH="44px"
          w={{ base: '100%', sm: 'auto' }}
          bg={CHAT_THEME.accent}
          color="white"
          _hover={{ bg: CHAT_THEME.accentHover }}
          isDisabled={disabled || !onRun}
          onClick={() => {
            setSubmittedLocally(true);
            onRun?.(offer);
          }}
        >
          {hasExactEstimate ? `Запустить за ~${formattedEstimate}` : `Запустить (${left})`}
        </Button>
      </Stack>
    </Box>
  );
}

export default ModeOffer;
