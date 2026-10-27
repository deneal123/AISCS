import { useCallback, useEffect, useRef, useState } from 'react';
import { Accordion, AccordionButton, AccordionIcon, AccordionItem, AccordionPanel, Box, Text, VStack } from '@chakra-ui/react';
import { useAppToast } from '@shared/hooks/useAppToast';
import { CHAT_THEME } from '../../chat/constants/theme';
import { borderRadius } from '@theme/tokens';
import { Skeleton } from '@shared/feedback/Skeleton';
import StateCard from '@shared/feedback/StateCard';
import SettingControl from './SettingControl';

export default function SettingsPanel() {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const toast = useAppToast();
  const requestRef = useRef(0);
  const controllerRef = useRef(null);
  const mountedRef = useRef(false);

  const load = useCallback(async () => {
    const generation = ++requestRef.current;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError(false);
    const { getAdminSettings } = await import('@api/admin');
    const data = await getAdminSettings({ signal: controller.signal }).catch(() => null);
    if (controller.signal.aborted || generation !== requestRef.current) return;
    if (data) setSettings(data.settings || []);
    setError(!data);
    setLoading(false);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    load();
    return () => {
      mountedRef.current = false;
      requestRef.current += 1;
      controllerRef.current?.abort();
    };
  }, [load]);

  const onSave = useCallback(
    async (key, value) => {
      const { putAdminSetting } = await import('@api/admin');
      const result = await putAdminSetting(key, value);
      const effective = result && Object.hasOwn(result, 'value') ? result.value : value;
      if (!mountedRef.current) return { value: effective };
      setSettings((current) => current?.map((spec) => spec.key === key ? { ...spec, value: effective, overridden: true } : spec));
      toast({ title: 'Сохранено', status: 'success', duration: 1500 });
      await load();
      return { value: effective };
    },
    [load, toast],
  );

  const onReset = useCallback(
    async (key) => {
      const { resetAdminSetting } = await import('@api/admin');
      await resetAdminSetting(key);
      const effective = settings?.find((spec) => spec.key === key)?.default;
      if (!mountedRef.current) return { value: effective };
      setSettings((current) => current?.map((spec) => spec.key === key ? { ...spec, value: effective, overridden: false } : spec));
      toast({ title: 'Сброшено к дефолту', status: 'info', duration: 1500 });
      await load();
      return { value: effective };
    },
    [load, settings, toast],
  );

  if (loading && settings === null) {
    return (
      <VStack align="stretch" spacing={2} aria-busy="true">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} h="48px" radius={borderRadius.sm} />
        ))}
      </VStack>
    );
  }

  if (error && settings === null) {
    return <StateCard variant="error" message="Не удалось загрузить настройки" onRetry={load} />;
  }

  if (!settings || settings.length === 0) {
    return <StateCard message="Нет редактируемых настроек" />;
  }

  const groups = (settings || []).reduce((acc, s) => {
    (acc[s.group] = acc[s.group] || []).push(s);
    return acc;
  }, {});

  return (
    <Box aria-busy={loading}>
      {error && <StateCard variant="error" message="Не удалось обновить настройки. Показаны последние доступные значения." onRetry={load} />}
      <Accordion allowMultiple defaultIndex={[0]}>
      {Object.entries(groups).map(([group, specs]) => (
        <AccordionItem key={group} border="none" mb={2}>
          <AccordionButton
            bg={CHAT_THEME.panelHover}
            borderRadius={borderRadius.sm}
            _hover={{ bg: CHAT_THEME.panelActive }}
          >
            <Box flex="1" textAlign="left" color={CHAT_THEME.textPrimary} fontWeight="600">
              {group}
              <Text as="span" ml={2} fontSize="11px" color={CHAT_THEME.textTertiary}>
                ({specs.length})
              </Text>
            </Box>
            <AccordionIcon color={CHAT_THEME.textSecondary} />
          </AccordionButton>
          <AccordionPanel px={0} pt={2}>
            <VStack align="stretch" spacing={2}>
              {specs.map((spec) => (
                <SettingControl key={spec.key} spec={spec} onSave={onSave} onReset={onReset} />
              ))}
            </VStack>
          </AccordionPanel>
        </AccordionItem>
      ))}
      </Accordion>
    </Box>
  );
}
