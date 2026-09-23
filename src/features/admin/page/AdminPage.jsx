import { useEffect, useState } from 'react';
import { Box, Heading, Text, VStack } from '@chakra-ui/react';
import { Reveal } from '@shared/motion/Reveal';
import Eyebrow from '@shared/brand/Eyebrow';
import SegmentedControl from '@shared/controls/SegmentedControl';
import { useLayoutControls } from '@app/providers';
import { CHAT_THEME } from '../../chat/constants/theme';
import SettingsPanel from '../components/SettingsPanel';
import UsersPanel from '../components/UsersPanel';
import PricingPanel from '../components/PricingPanel';
import AnalyticsPanel from '../components/AnalyticsPanel';

const TABS = [
  { key: 'analytics', label: 'Аналитика' },
  { key: 'settings', label: 'Настройки' },
  { key: 'pricing', label: 'Тарифы и цены' },
  { key: 'users', label: 'Пользователи' },
];

export default function AdminPage() {
  // Как /chat и /billing: полная ширина layout (иначе ProtectedLayout зажимает
  // контент в узкую колонку maxW="6xl" по центру — на широком экране пустые поля).
  const { setVariant } = useLayoutControls();
  useEffect(() => {
    setVariant('full');
    return () => setVariant('container');
  }, [setVariant]);

  const [tab, setTab] = useState('analytics');

  return (
    <Box flex="1 0 auto" w="100%" minH="100svh" display="flex" flexDirection="column">
      <Box
        flex="1"
        w="100%"
        maxW="1520px"
        mx="auto"
        px={{ base: 4, md: 8, lg: 12 }}
        py={{ base: 8, md: 10 }}
      >
        <Reveal as={VStack} variant="soft" align="start" spacing={1.5} mb={6}>
          <Eyebrow>Администрирование</Eyebrow>
          <Heading as="h1" size="lg" color={CHAT_THEME.textPrimary} letterSpacing="-0.01em">
            Админ-панель
          </Heading>
          <Text fontSize="13px" color={CHAT_THEME.textSecondary}>
            Аналитика, runtime-настройки, цены моделей и управление пользователями.
          </Text>
        </Reveal>

        <VStack align="stretch" spacing={6}>
          <Box overflowX="auto" role="region" aria-label="Разделы админ-панели" tabIndex={0} sx={{ '&::-webkit-scrollbar': { display: 'none' } }}>
            <SegmentedControl size="md" options={TABS} value={tab} onChange={setTab} w="max-content" ariaLabel="Разделы админки" />
          </Box>

          {tab === 'analytics' && (
            <Reveal key="analytics" variant="soft">
              <AnalyticsPanel />
            </Reveal>
          )}
          {tab === 'settings' && (
            <Reveal key="settings" variant="soft">
              <SettingsPanel />
            </Reveal>
          )}
          {tab === 'pricing' && (
            <Reveal key="pricing" variant="soft">
              <PricingPanel />
            </Reveal>
          )}
          {tab === 'users' && (
            <Reveal key="users" variant="soft">
              <UsersPanel />
            </Reveal>
          )}
        </VStack>
      </Box>
    </Box>
  );
}
