import React from 'react';
import { Box, Flex, Text } from '@chakra-ui/react';
import SimulatorScene from './SimulatorScene';
import { SIMULATION_THEME, SIMULATION_TRACES } from './theme';

const stimulus = { none: 'нет воздействия', weak: 'слабое', strong: 'сильное' };
const summary = configuration => `${stimulus[configuration.stimulus]} · seed ${configuration.seed} · возбудимость ${configuration.excitability} · адаптация ${configuration.adaptation}`;
const position = contact => ['x_um', 'y_um', 'z_um'].map(axis => Number(contact[axis]).toFixed(0)).join(', ');

export default function SimulationComparison({ reference, run, issue, sceneIssue, catalog,
  timeMs, opacity, neurons, localWindow, cameraLink, resetCamera, focusLocal }) {
  const different = reference?.run_id !== run?.id;
  const second = different && run?.state === 'completed' && run.result?.preview;
  const models = [
    { id: 'A', preview: reference, configuration: reference.configuration, color: SIMULATION_TRACES.reference },
    { id: 'B', preview: second, configuration: run?.configuration, color: SIMULATION_TRACES.current },
  ];
  if (issue || sceneIssue) return <Flex position="absolute" inset={0} pt="48px" px={6} align="center" justify="center">
    <Text role="status" maxW="520px" color={SIMULATION_THEME.textSecondary} fontSize="13px">
      {sceneIssue || 'Выбранные записи несовместимы для синхронных сцен. Измените пару или откройте одну запись.'}
    </Text>
  </Flex>;
  return <Flex position="absolute" inset={0} pt="48px" direction={{ base: 'column', md: 'row' }}>
    {models.map(({ id, preview, configuration, color }) => <Flex as="section" aria-label={`Опыт ${id}`} key={id}
      direction="column" flex={1} minW={0} minH={0} borderRight={id === 'A' ? '1px solid' : undefined} borderColor={SIMULATION_THEME.panelBorder}>
      <Box px={3} pb={2} h="96px" flexShrink={0} overflow="hidden">
        <Text fontSize="13px" fontWeight="600" color={color}>{id} · {id === 'A' ? 'Закреплённая запись' : 'Выбранный опыт'}</Text>
        {preview && <><Text fontSize="12px" color={SIMULATION_THEME.textSecondary} noOfLines={1} title={summary(configuration)}>{summary(configuration)}</Text>
          <Text fontSize="11px" color={SIMULATION_THEME.textSecondary} noOfLines={2}>E1: ({position(configuration.placement.electrode)}) · REF: ({position(configuration.placement.reference)}), мкм</Text>
          {preview.prediction && <Text fontSize="11px" color={preview.prediction.class === configuration.stimulus ? SIMULATION_THEME.textSecondary : 'orange.200'} noOfLines={2}>
            Распознано: {stimulus[preview.prediction.class]}{preview.prediction.class !== configuration.stimulus ? ' — не совпадает с заданным условием' : ''}
          </Text>}</>}
      </Box>
      <Box flex={1} minH={0} position="relative">
        {preview && !issue && !sceneIssue ? <SimulatorScene sceneLabel={`Синхронная сцена ${id}`} preview={preview} timeMs={timeMs}
          runId={id === 'A' ? reference.run_id : run.id}
          opacity={opacity} neurons={neurons} localWindow={localWindow} placing={false} placement={configuration.placement}
          modelGeometry={catalog.models[0].geometry} modelVisualization={catalog.models[0].visualization}
          sceneContext={configuration.placement.registration} cameraLink={cameraLink} synchronizeCamera
          resetCamera={resetCamera} focusLocal={focusLocal} />
          : <Flex h="full" px={5} align="center" justify="center"><Text role="status" maxW="340px" fontSize="13px" color={SIMULATION_THEME.textSecondary}>
            {issue || sceneIssue || (id === 'B'
              ? different && run && run.state !== 'completed' ? 'Выбранный опыт ещё не завершён. Сравнение появится после сохранения результатов.' : 'Выберите другой завершённый опыт слева. Время и камера будут общими для обеих записей.'
              : 'Запись недоступна.')}
          </Text></Flex>}
      </Box>
    </Flex>)}
  </Flex>;
}
