import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Avatar,
  Badge,
  Box,
  Button,
  Divider,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerHeader,
  DrawerOverlay,
  HStack,
  Icon,
  Input,
  SimpleGrid,
  Spinner,
  Switch,
  Text,
  VStack,
} from '@chakra-ui/react';
import { FiCalendar, FiCheck, FiCpu, FiLogOut, FiMail, FiMessageSquare, FiSettings, FiShield, FiSliders, FiTag } from '@shared/icons';
import { useNavigate } from 'react-router-dom';
import { updateNotificationPrefs, updateProfile } from '@api/profile';
import { useAuth } from '@app/providers';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE, GLASS_CARD_BASE, CARD_HOVER_SOFT, CARD_TRANSITION, INPUT_BASE } from '@theme/glass';
import { GHOST_BUTTON_BLUE_SX } from '@theme/styles';
import Eyebrow from '@shared/brand/Eyebrow';
import { useAppToast } from '@shared/hooks/useAppToast';
import { DRAWER_CLOSE_BUTTON_PROPS, DRAWER_OVERLAY_PROPS, DRAWER_RADIAL_BG, DRAWER_CONTENT_BG } from '@theme/drawer';
import { CHAT_SCROLLBAR_SX, CHAT_THEME } from '../../chat/constants/theme';
import ModelSelector from '../../chat/components/ModelSelector';
import CreditSummary from '../../billing/components/CreditSummary';
import { useBillingContext } from '../../billing/context/BillingContext';

const NAME_MAX = 50;
const TZ_MAX = 50;

/** «Регистрация» из ISO-даты created_at → «июль 2026» (ru). Пусто при отсутствии/ошибке. */
function formatMemberSince(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  try {
    return new Intl.DateTimeFormat('ru-RU', { month: 'long', year: 'numeric' }).format(date);
  } catch {
    return '';
  }
}

/** Заголовок секции: Eyebrow-лейбл (mono + анимированная линия на .in Reveal). */
function SectionLabel({ children }) {
  return <Eyebrow>{children}</Eyebrow>;
}

/** Строка почтового согласия: иконка + пояснение + тумблер. */
function EmailPrefRow({ icon, title, description, isChecked, isDisabled, onToggle }) {
  return (
    <HStack spacing={3} align="center">
      <Box
        w="32px"
        h="32px"
        borderRadius={borderRadius.sm}
        display="flex"
        alignItems="center"
        justifyContent="center"
        bg={CHAT_THEME.accentSoft}
        border={`1px solid ${colors.accent.subtleBorder}`}
        flexShrink={0}
      >
        <Icon as={icon} boxSize={3.5} color={colors.iris[300]} />
      </Box>
      <VStack align="start" spacing={0} minW="0" flex="1">
        <Text fontSize="13px" fontWeight="600" color={CHAT_THEME.textPrimary} letterSpacing="-0.005em">
          {title}
        </Text>
        <Text fontSize="11.5px" fontWeight="500" color={CHAT_THEME.textSecondary}>
          {description}
        </Text>
      </VStack>
      <Switch
        size="sm"
        colorScheme="blue"
        aria-label={title}
        isChecked={isChecked}
        isDisabled={isDisabled}
        onChange={(e) => onToggle(e.target.checked)}
        flexShrink={0}
      />
    </HStack>
  );
}

export function ProfileDrawer({
  isOpen,
  onClose,
  profileData,
  setProfileData,
  profileMemoryCount,
  isLoading,
  user,
  threadCount = 0,
  memoryFallbackCount = 0,
  availableModels = [],
  modelCatalog = {},
  preferredModel = '',
  onPreferredModelChange,
  onOpenSettings,
  onLogout,
}) {
  const { balance } = useBillingContext();
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const toast = useAppToast();

  const [nameDraft, setNameDraft] = useState('');
  const [tzDraft, setTzDraft] = useState('');
  const [saving, setSaving] = useState(false);

  // Обновляем черновик из профиля, ТОЛЬКО если пользователь ещё не отклонился от
  // ранее засинканного значения. Иначе фоновой рефетч профиля (пока юзер печатает)
  // затирал бы правки — раньше эффект синкал на КАЖДОЕ изменение profileData.
  // При этом серверные апдейты (загрузка, канонизация после сохранения) принимаются.
  const syncedNameRef = useRef('');
  const syncedTzRef = useRef('');
  useEffect(() => {
    const nextName = profileData?.first_name || '';
    const nextTz = profileData?.timezone || '';
    setNameDraft((cur) => (cur === syncedNameRef.current ? nextName : cur));
    setTzDraft((cur) => (cur === syncedTzRef.current ? nextTz : cur));
    syncedNameRef.current = nextName;
    syncedTzRef.current = nextTz;
  }, [profileData]);

  const savedName = profileData?.first_name || '';
  const savedTz = profileData?.timezone || '';
  const isDirty = nameDraft.trim() !== savedName || tzDraft.trim() !== savedTz;

  const handleSaveProfile = useCallback(async () => {
    const nextName = nameDraft.trim();
    const nextTz = tzDraft.trim();

    if (nextName.length < 1 || nextName.length > NAME_MAX) {
      toast({ title: 'Проверьте имя', description: `Имя должно быть от 1 до ${NAME_MAX} символов.`, status: 'error' });
      return;
    }
    if (nextTz.length > TZ_MAX) {
      toast({ title: 'Проверьте часовой пояс', description: `Не длиннее ${TZ_MAX} символов.`, status: 'error' });
      return;
    }

    // Только изменённые поля — пустой PATCH возвращает 422. Пустой timezone не шлём
    // (backend требует min_length=1 при наличии поля).
    const payload = {};
    if (nextName !== savedName) payload.first_name = nextName;
    if (nextTz && nextTz !== savedTz) payload.timezone = nextTz;
    if (Object.keys(payload).length === 0) return;

    setSaving(true);
    try {
      const updated = await updateProfile(payload);
      setProfileData?.(updated);
      toast({ title: 'Профиль обновлён', status: 'success' });
    } catch {
      toast({ title: 'Не удалось сохранить', description: 'Попробуйте ещё раз.', status: 'error' });
    } finally {
      setSaving(false);
    }
  }, [nameDraft, tzDraft, savedName, savedTz, setProfileData, toast]);

  // Согласия на письма. Тумблер отражает СЕРВЕРНОЕ состояние (без оптимистичного
  // обновления): врать про согласие нельзя, а при упавшем запросе оптимистичный тумблер
  // остался бы включённым, пока писем не приходит.
  const [savingPref, setSavingPref] = useState(null);
  const serviceEmailsOn = profileData?.service_emails !== false;
  const marketingEmailsOn = !!profileData?.marketing_emails;

  const handleTogglePref = useCallback(
    async (field, next) => {
      setSavingPref(field);
      try {
        // Шлём ТОЛЬКО тронутое поле: непереданное бэкенд оставляет как есть.
        const updated = await updateNotificationPrefs({ [field]: next });
        setProfileData?.(updated);
      } catch {
        toast({ title: 'Не удалось изменить настройку', description: 'Попробуйте ещё раз.', status: 'error' });
      } finally {
        setSavingPref(null);
      }
    },
    [setProfileData, toast],
  );

  const memberSince = formatMemberSince(profileData?.created_at);
  const fieldLabelSx = {
    fontSize: '10.5px',
    fontWeight: '600',
    color: CHAT_THEME.textTertiary,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
    mb: 1.5,
  };

  return (
    <Drawer isOpen={isOpen} placement="right" onClose={onClose} size="md">
      <DrawerOverlay {...DRAWER_OVERLAY_PROPS} />
      <DrawerContent
        bg={DRAWER_CONTENT_BG}
        borderLeft={`1px solid ${CHAT_THEME.panelBorder}`}
        sx={{
          willChange: 'transform',
          backgroundImage: DRAWER_RADIAL_BG,
        }}
      >
        <DrawerCloseButton aria-label="Закрыть профиль" mt={2} color={CHAT_THEME.textSecondary} _hover={{ color: CHAT_THEME.textPrimary }} {...DRAWER_CLOSE_BUTTON_PROPS} />
        <DrawerHeader py={3} borderBottomWidth="1px" borderColor={colors.border.subtle} fontWeight="700" letterSpacing="-0.01em">
          Профиль
        </DrawerHeader>
        <DrawerBody pt={4} sx={CHAT_SCROLLBAR_SX}>
          {/* Без Reveal/IntersectionObserver: контент дравера монтируется за
              кадром (translateX) и «въезжает» трансформом — observer гонялся с
              анимацией и иногда не срабатывал, оставляя тело на opacity:0
              (виден только заголовок). Само выезжание дравера даёт движение. */}
          <VStack spacing={4} align="stretch">
            {/* ===== Аккаунт (identity + inline edit) ===== */}
            <VStack align="stretch" spacing={2}>
              <SectionLabel>Аккаунт</SectionLabel>
              <Box p={4} {...GLASS_CARD_BASE} borderRadius={borderRadius.lg}>
                <Box
                  position="absolute"
                  top="-30%"
                  right="-10%"
                  w="50%"
                  h="120%"
                  background={`radial-gradient(circle, ${colors.accent.subtle} 0%, transparent 65%)`}
                  filter="blur(30px)"
                  pointerEvents="none"
                />
                <VStack align="stretch" spacing={3} position="relative">
                  <HStack spacing={3.5} align="center">
                    <Box p="2px" borderRadius="full" bg="linear-gradient(135deg, rgba(45, 91, 255,0.95), rgba(255,255,255,0.35))">
                      <Avatar
                        size="md"
                        name={profileData?.first_name || user?.first_name || profileData?.email || user?.email}
                        bg={colors.bg.menu}
                        color={CHAT_THEME.textPrimary}
                        fontWeight="700"
                      />
                    </Box>
                    <VStack align="flex-start" spacing={0.5} flex="1" minW="0">
                      <Text fontSize="18px" fontWeight="700" color={CHAT_THEME.textPrimary} letterSpacing="-0.01em" noOfLines={1}>
                        {profileData?.first_name || user?.first_name || 'Пользователь'}
                      </Text>
                      <Text fontSize="12.5px" fontWeight="500" color={CHAT_THEME.textSecondary} noOfLines={1}>
                        {profileData?.email || user?.email || '—'}
                      </Text>
                      <HStack spacing={2} mt={1.5} flexWrap="wrap">
                        <Badge
                          display="inline-flex" alignItems="center" gap={1.5}
                          px={2} py={0.5} borderRadius="full" fontSize="10px" fontWeight="600" textTransform="none"
                          bg={colors.successSoft} color={colors.success} border={`1px solid ${colors.successBorder}`}
                        >
                          <Box as="span" w="6px" h="6px" borderRadius="full" bg={colors.success} />
                          Активен
                        </Badge>
                        {memberSince && (
                          <HStack spacing={1} color={CHAT_THEME.textTertiary} title="Дата регистрации">
                            <Icon as={FiCalendar} boxSize={3} />
                            <Text fontSize="10.5px" fontWeight="500" textTransform="capitalize">{memberSince}</Text>
                          </HStack>
                        )}
                      </HStack>
                    </VStack>
                  </HStack>

                  <Divider borderColor={colors.border.subtle} />

                  <VStack align="stretch" spacing={3}>
                    <SimpleGrid columns={2} spacing={3}>
                      <Box>
                        <Text {...fieldLabelSx}>Отображаемое имя</Text>
                        <Input
                          {...INPUT_BASE}
                          aria-label="Отображаемое имя"
                          value={nameDraft}
                          onChange={(e) => setNameDraft(e.target.value)}
                          maxLength={NAME_MAX}
                          placeholder="Ваше имя"
                          h="36px"
                          fontSize="13px"
                          px="12px"
                        />
                      </Box>
                      <Box>
                        <Text {...fieldLabelSx}>Часовой пояс</Text>
                        <Input
                          {...INPUT_BASE}
                          aria-label="Часовой пояс"
                          value={tzDraft}
                          onChange={(e) => setTzDraft(e.target.value)}
                          maxLength={TZ_MAX}
                          placeholder="Europe/Moscow"
                          h="36px"
                          fontSize="13px"
                          px="12px"
                        />
                      </Box>
                    </SimpleGrid>
                    <Button
                      leftIcon={saving ? <Spinner size="xs" /> : <Icon as={FiCheck} />}
                      onClick={handleSaveProfile}
                      isDisabled={!isDirty || saving}
                      h="36px"
                      borderRadius={borderRadius.sm}
                      fontSize="13px"
                      fontWeight="600"
                      border={`1px solid ${colors.accent.subtleBorder}`}
                      {...GHOST_BUTTON_BLUE_SX}
                      _disabled={{ opacity: 0.45, cursor: 'not-allowed' }}
                    >
                      Сохранить изменения
                    </Button>
                  </VStack>
                </VStack>
              </Box>
            </VStack>

            {/* ===== Активность (stats) ===== */}
            <VStack align="stretch" spacing={2}>
              <SectionLabel>Активность</SectionLabel>
              <SimpleGrid columns={2} spacing={3}>
                {[
                  { label: 'Чатов', value: threadCount, icon: FiMessageSquare },
                  { label: 'Память', value: profileMemoryCount ?? memoryFallbackCount, icon: FiSliders },
                ].map(({ label, value, icon: StatIcon }) => (
                  <Box
                    key={label}
                    p={3}
                    {...GLASS_SURFACE}
                    borderRadius={borderRadius.md}
                    transition={CARD_TRANSITION}
                    _hover={CARD_HOVER_SOFT}
                  >
                    <HStack spacing={2} mb={1}>
                      <Icon as={StatIcon} boxSize={3.5} color={colors.blue[300]} />
                      <Text fontSize="10.5px" fontWeight="600" color={CHAT_THEME.textTertiary} letterSpacing="0.04em" textTransform="uppercase">
                        {label}
                      </Text>
                    </HStack>
                    <Text fontSize="20px" fontWeight="700" color={CHAT_THEME.textPrimary} letterSpacing="-0.02em" lineHeight="1.1">
                      {value}
                    </Text>
                  </Box>
                ))}
              </SimpleGrid>
            </VStack>

            {/* ===== Настройки (preferred model + ссылка на настройки чата) ===== */}
            <VStack align="stretch" spacing={2}>
              <SectionLabel>Настройки</SectionLabel>
              <Box p={3} {...GLASS_SURFACE} borderRadius={borderRadius.md}>
                <VStack align="stretch" spacing={2.5}>
                  <HStack spacing={3} align="center">
                    <Box
                      w="32px"
                      h="32px"
                      borderRadius={borderRadius.sm}
                      display="flex"
                      alignItems="center"
                      justifyContent="center"
                      bg={CHAT_THEME.accentSoft}
                      border={`1px solid ${colors.accent.subtleBorder}`}
                      flexShrink={0}
                    >
                      <Icon as={FiCpu} boxSize={3.5} color={colors.iris[300]} />
                    </Box>
                    <VStack align="start" spacing={0} minW="0">
                      <Text fontSize="13px" fontWeight="600" color={CHAT_THEME.textPrimary} letterSpacing="-0.005em">
                        Модель по умолчанию
                      </Text>
                      <Text fontSize="11.5px" fontWeight="500" color={CHAT_THEME.textSecondary}>
                        Композер будет открываться с этой моделью
                      </Text>
                    </VStack>
                  </HStack>
                  <Box pl="44px">
                    <ModelSelector
                      size="compact"
                      placement="bottom-start"
                      selectedModel={preferredModel}
                      availableModels={availableModels}
                      catalog={modelCatalog}
                      onChange={onPreferredModelChange}
                    />
                  </Box>

                  <Divider borderColor={colors.border.subtle} />

                  <Button
                    leftIcon={<Icon as={FiSettings} />}
                    variant="ghost"
                    justifyContent="flex-start"
                    onClick={() => { onClose(); onOpenSettings?.(); }}
                    h="36px"
                    borderRadius={borderRadius.sm}
                    fontSize="12.5px"
                    fontWeight="600"
                    color={CHAT_THEME.textSecondary}
                    bg={colors.surface.tint2}
                    border={`1px solid ${CHAT_THEME.panelBorder}`}
                    _hover={{ bg: CHAT_THEME.panelHover, color: CHAT_THEME.textPrimary, borderColor: CHAT_THEME.panelBorderStrong }}
                  >
                    Веб-поиск, Deep Research и интерфейс
                  </Button>
                </VStack>
              </Box>
            </VStack>

            {/* ===== Письма ===== */}
            <VStack align="stretch" spacing={2}>
              <SectionLabel>Письма</SectionLabel>
              <Box p={3} {...GLASS_SURFACE} borderRadius={borderRadius.md}>
                <VStack align="stretch" spacing={3}>
                  <EmailPrefRow
                    icon={FiMail}
                    title="О состоянии аккаунта"
                    description="Подписка заканчивается, кредиты на исходе, платёж не прошёл"
                    isChecked={serviceEmailsOn}
                    isDisabled={savingPref !== null}
                    onToggle={(next) => handleTogglePref('service_emails', next)}
                  />
                  <Divider borderColor={colors.border.subtle} />
                  {/* Выключенные письма гасят и рекламу — тумблер не должен обещать
                      то, чего рассылка всё равно не отправит. */}
                  <EmailPrefRow
                    icon={FiTag}
                    title="Новости и предложения"
                    description={
                      serviceEmailsOn
                        ? 'Новые возможности и специальные предложения'
                        : 'Недоступно, пока все письма выключены'
                    }
                    isChecked={marketingEmailsOn}
                    isDisabled={savingPref !== null || !serviceEmailsOn}
                    onToggle={(next) => handleTogglePref('marketing_emails', next)}
                  />
                </VStack>
              </Box>
            </VStack>

            {/* ===== Баланс (shared CreditSummary, без рестайла) ===== */}
            <VStack align="stretch" spacing={2}>
              <SectionLabel>Баланс</SectionLabel>
              <CreditSummary balance={balance} />
            </VStack>

            {/* ===== Действия ===== */}
            <VStack align="stretch" spacing={2}>
              <SectionLabel>Действия</SectionLabel>
              <HStack spacing={3} align="stretch">
                {isAdmin && (
                  <Button
                    flex="1"
                    leftIcon={<FiShield />}
                    onClick={() => {
                      onClose();
                      navigate('/admin');
                    }}
                    h="38px"
                    borderRadius={borderRadius.sm}
                    fontSize="13px"
                    fontWeight="600"
                    border={`1px solid ${colors.accent.subtleBorder}`}
                    {...GHOST_BUTTON_BLUE_SX}
                  >
                    Админ-панель
                  </Button>
                )}

                <Button
                  flex="1"
                  leftIcon={<FiLogOut />}
                  onClick={() => { onClose(); onLogout?.(); }}
                  h="38px"
                  borderRadius={borderRadius.sm}
                  fontSize="13px"
                  fontWeight="600"
                  border={`1px solid ${colors.accent.subtleBorder}`}
                  {...GHOST_BUTTON_BLUE_SX}
                >
                  Выйти
                </Button>
              </HStack>
            </VStack>

            {isLoading && (
              <HStack spacing={2} justify="center" color={CHAT_THEME.textTertiary}>
                <Spinner size="xs" />
                <Text fontSize="11px">Загружаем данные…</Text>
              </HStack>
            )}
          </VStack>
        </DrawerBody>
      </DrawerContent>
    </Drawer>
  );
}
