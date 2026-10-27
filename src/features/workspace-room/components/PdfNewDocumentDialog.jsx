import { useEffect, useId, useRef, useState } from 'react';
import { Box, Button, Modal, ModalBody, ModalCloseButton, ModalContent, ModalFooter,
  ModalHeader, ModalOverlay, Text } from '@chakra-ui/react';
import AppSelect from '@shared/controls/AppSelect';
import { colors } from '@theme/tokens';
import { DRAWER_CLOSE_BUTTON_PROPS } from '@theme/drawer';

const EMPTY_PROFILES = [];

/** Local choices never modify the currently open document's formatting. */
export function PdfNewDocumentDialog({ document, onClose, blocked, newWorkspace = false, finalFocusRef }) {
  const profiles = document.profiles || EMPTY_PROFILES;
  const id = useId();
  const [profile, setProfile] = useState(() => profiles.some(item => item.profile_id === 'generic_document')
    ? 'generic_document' : profiles[0]?.profile_id || '');
  const [locale, setLocale] = useState('ru-RU');
  const [path] = useState(() => `documents/document-${globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`}`);
  const [pending, setPending] = useState(false);
  const [menuOwner, setMenuOwner] = useState(null);
  const [error, setError] = useState('');
  const inFlight = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const busy = pending || Boolean(document.busy);
  const formatsPending = document.profilesState === 'loading';
  const formatsUnavailable = document.profilesState === 'unavailable' || (!profiles.length && !formatsPending);
  const validProfile = profiles.some(item => item.profile_id === profile);
  useEffect(() => {
    if (!profile && profiles.length) setProfile(profiles.some(item => item.profile_id === 'generic_document')
      ? 'generic_document' : profiles[0].profile_id);
  }, [profile, profiles]);
  const create = async event => {
    event.preventDefault();
    if (inFlight.current || busy || blocked || !validProfile || formatsPending) return;
    inFlight.current = true; setPending(true); setError('');
    try {
      const result = await document.createProject({ path, profileId: profile, locale, mode: 'draft', initializeContent: true });
      if (!mounted.current) return;
      if (result) onClose();
      else setError('Создание не подтверждено. Проверьте список проектов перед повтором.');
    } catch {
      if (mounted.current) setError('Не удалось создать документ. Открытый проект не изменён.');
    } finally {
      inFlight.current = false;
      if (mounted.current) setPending(false);
    }
  };
  return <Modal isOpen onClose={busy ? () => {} : onClose} finalFocusRef={finalFocusRef} size="sm" scrollBehavior="inside" motionPreset="none">
    <ModalOverlay /><ModalContent ref={setMenuOwner} bg={colors.bg.menu} color={colors.fg[1]} mx={3} my={4}>
      <Box as="form" noValidate onSubmit={create} display="flex" flexDirection="column" minH={0} flex={1} overflow="hidden">
        <ModalHeader fontSize="md" pr={12} flexShrink={0}>Новый документ</ModalHeader>
        <ModalCloseButton {...DRAWER_CLOSE_BUTTON_PROPS} aria-label="Закрыть новый документ" isDisabled={busy} />
        <ModalBody minH={0} overflowY="auto" overscrollBehavior="contain">
          {newWorkspace && <Text mb={3} fontSize="xs" color={colors.warning}>
            Будет создана новая среда. Документ из завершённой среды не восстановится.
          </Text>}
          <Text as="label" htmlFor={`${id}-profile`} fontSize="xs" color={colors.fg[3]}>Формат</Text>
          <AppSelect inputId={`${id}-profile`} ariaLabel="Формат нового документа" menuPortalTarget={menuOwner}
            size="document" mt={1} value={profile} isDisabled={busy || formatsPending || !profiles.length} isSearchable={false}
            options={profiles.map(item => ({ value: item.profile_id, label: item.label }))} onChange={setProfile} />
          {formatsPending && <Text mt={2} role="status" fontSize="xs" color={colors.fg[3]}>Загружаю форматы…</Text>}
          {formatsUnavailable && <Box mt={2}>
            <Text role="alert" fontSize="xs" color={colors.warning}>Не удалось загрузить форматы документов.</Text>
            <Button mt={1} size="document" variant="ghost" isDisabled={busy} onClick={() => document.loadProfiles?.()}>
              Повторить загрузку форматов
            </Button>
          </Box>}
          <Text as="label" display="block" mt={3} htmlFor={`${id}-locale`} fontSize="xs" color={colors.fg[3]}>Язык</Text>
          <AppSelect inputId={`${id}-locale`} ariaLabel="Язык нового документа" menuPortalTarget={menuOwner}
            size="document" mt={1} value={locale} isDisabled={busy} isSearchable={false}
            options={[{ value: 'ru-RU', label: 'Русский' }, { value: 'en-US', label: 'English' }]} onChange={setLocale} />
          <Text mt={3} fontSize="xs" color={colors.fg[3]}>Открытый документ сохранится. ИИ и сборка не запускаются.</Text>
          {error && <Text mt={3} role="alert" fontSize="xs" color={colors.warning}>{error}</Text>}
        </ModalBody>
        <ModalFooter gap={2} flexShrink={0}>
          <Button size="document" variant="ghost" isDisabled={busy} onClick={onClose}>Отмена</Button>
          <Button size="document" variant="workbenchPrimary" type="submit" isLoading={pending}
            isDisabled={Boolean(document.busy || blocked || !validProfile || formatsPending)}>Создать документ</Button>
        </ModalFooter>
      </Box>
    </ModalContent>
  </Modal>;
}
