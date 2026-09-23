import { useCallback, useEffect, useState } from 'react';
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

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    const { getAdminSettings } = await import('@api/admin');
    const data = await getAdminSettings().catch(() => null);
    setSettings(data?.settings || []);
    setError(!data);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onSave = useCallback(
    async (key, value) => {
      const { putAdminSetting } = await import('@api/admin');
      await putAdminSetting(key, value);
      toast({ title: 'Сохранено', status: 'success', duration: 1500 });
      await load();
    },
    [load, toast],
  );

  const onReset = useCallback(
    async (key) => {
      const { resetAdminSetting } = await import('@api/admin');
      await resetAdminSetting(key);
      toast({ title: 'Сброшено к дефолту', status: 'info', duration: 1500 });
      await load();
    },
    [load, toast],
  );

  if (loading) {
    return (
      <VStack align="stretch" spacing={2} aria-busy="true">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} h="48px" radius={borderRadius.sm} />
        ))}
      </VStack>
    );
  }

  if (error) {
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
  );
}
