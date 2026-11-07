import React from 'react';
import { Box, Button, HStack, IconButton, Stack, Text } from '@chakra-ui/react';
import { FiDownload, FiFile } from 'react-icons/fi';
import { useAppToast } from '@shared/hooks/useAppToast';
import { simulationApi } from '../api';
import { SIMULATION_THEME } from '../theme';
import useSimulationArtifacts from './useSimulationArtifacts';
import { targetTimeline } from './targetTimeline';

// Each calculation owns its files; never attribute child artifacts to the scene.
export function simulationFileGroups(scene, playback, target, sourceForFiles) {
  if (!scene?.id) return [];
  const groups = [], seen = new Set();
  const add = (run, title) => {
    if (run?.id && run.state === 'completed' && !seen.has(run.id)) {
      seen.add(run.id); groups.push({ run, title });
    }
  };
  const graph = scene.result?.preview?.connectome?.manifest_sha256;
  if (scene.state === 'completed' && playback?.sceneRunId === scene.id && graph) {
    if (playback.direct) {
      if (playback.run?.parent_run_id === scene.id
          && playback.run.configuration?.graph_manifest_sha256 === graph)
        add(playback.run, 'Сетевой расчёт');
    } else {
      const source = playback.source;
      if (source?.id && source.state === 'completed' && source.parent_run_id === scene.id
          && source.configuration?.graph_manifest_sha256 === graph) {
        if (playback.run?.parent_run_id === source.id
            && playback.run.configuration?.graph_manifest_sha256 === graph) {
          if (targetTimeline(playback.run, target)) add(target, 'Дополнительная запись');
          add(playback.run, 'Запись и обратная связь');
        }
        if (playback.proxy?.parent_run_id === source.id
            && playback.proxy.configuration?.graph_manifest_sha256 === graph)
          add(playback.proxy, 'Сетевой расчёт');
        add(source, 'Исходные клетки');
      }
    }
  }
  const source = sourceForFiles?.source;
  if (!(playback?.direct && playback.sceneRunId === scene.id)
      && sourceForFiles?.sceneRunId === scene.id && source?.parent_run_id === scene.id
      && source.configuration?.graph_manifest_sha256 === graph) add(source, 'Последний расчёт клеток');
  add(scene, groups.length ? 'Сцена' : 'Выбранный опыт');
  return groups;
}

function ArtifactGroup({ run, title }) {
  const artifacts = useSimulationArtifacts(run.id, run.state, true);
  const toast = useAppToast();
  return <Box as="section" aria-label={title} mb={6}>
    <HStack justify="space-between" mb={3}>
      <Text fontWeight="600">{title}</Text>
      <Button size="sm" variant="outline" leftIcon={<FiDownload />} onClick={async () => {
        try { await simulationApi.downloadManifest(run.id); }
        catch { toast({ status: 'error', title: 'Манифест недоступен. Повторите скачивание.' }); }
      }}>Манифест</Button>
    </HStack>
    {artifacts.loading && <Text role="status">Загрузка файлов…</Text>}
    {artifacts.error && <Stack><Text role="alert">{artifacts.error}</Text>
      <Button alignSelf="start" variant="outline" size="sm" onClick={artifacts.retry}>Повторить загрузку файлов</Button></Stack>}
    {!artifacts.loading && !artifacts.error && !artifacts.files.length
      && <Text color={SIMULATION_THEME.textSecondary}>Файлы не зарегистрированы.</Text>}
    {artifacts.files.map(file => <HStack key={file.id} borderBottom="1px solid" borderColor={SIMULATION_THEME.panelBorder} py={3}>
      <FiFile /><Box flex={1}><Text fontSize="13px">{file.name}</Text>
        <Text fontSize="11px" color={SIMULATION_THEME.textSecondary}>{Math.ceil(file.bytes / 1024)} КБ · SHA-256 {file.sha256?.slice(0, 12)}…</Text></Box>
      <IconButton size="sm" aria-label={`Скачать ${file.name}`} icon={<FiDownload />} onClick={async () => {
        try { await simulationApi.download(run.id, file); }
        catch { toast({ status: 'error', title: 'Файл недоступен. Повторите скачивание.' }); }
      }} />
    </HStack>)}
  </Box>;
}

export default function SimulationFiles({ scene, playback, target, sourceForFiles, busy }) {
  const groups = simulationFileGroups(scene, playback, target, sourceForFiles);
  return <Box as="section" aria-labelledby="simulation-files-title" flex={1} overflowY="auto" p={6}>
    <Text id="simulation-files-title" fontWeight="600" mb={4}>Файлы выбранного опыта</Text>
    {!scene && <Text color={SIMULATION_THEME.textSecondary}>Выберите опыт в списке слева.</Text>}
    {scene && !groups.length && <Text color={SIMULATION_THEME.textSecondary}>{busy
      ? 'Расчёт ещё не сохранён. Файлы появятся после завершения.'
      : 'У этого опыта нет опубликованных результатов.'}</Text>}
    {groups.map(({ run, title }) => <ArtifactGroup key={run.id} run={run} title={title} />)}
  </Box>;
}
