import React from 'react';
import { Box, Stack, Text } from '@chakra-ui/react';
import { SIMULATION_THEME } from './theme';

const labels = { none: 'Нет воздействия', weak: 'Слабое воздействие', strong: 'Сильное воздействие' };
const percent = value => (value * 100).toFixed(1);

export default function RecognitionSummary({ preview, stimulus, regionName }) {
  const prediction = preview?.prediction, evaluation = prediction?.evaluation;
  const full = Boolean(preview?.connectome), overall = prediction?.overall_evaluation;
  return <Stack spacing={3} maxW="900px">
    <Text>Заданное условие: {labels[stimulus]}. Распознано: {prediction ? labels[prediction.class] : 'предсказание недоступно'}.</Text>
    {!prediction && preview?.prediction_status?.reason && <Text role="status" color={SIMULATION_THEME.textSecondary}>{preview.prediction_status.reason}</Text>}
    {evaluation && <Box fontSize="13px">
      <Text mb={2}>{full ? `Проверка области «${regionName || prediction.region}»` : 'Отложенная проверка'}: {percent(evaluation.test_balanced_accuracy)}% сбалансированной точности,
        {' '}{evaluation.test_realizations} {full ? `записей из ${evaluation.test_groups} конфигураций` : 'реализаций'}. Постоянный ответ: 33,3%.</Text>
      {evaluation.sizes && <Text color={SIMULATION_THEME.textSecondary}>
        Обучение / валидация / тест: {evaluation.sizes.train} / {evaluation.sizes.validation} / {evaluation.sizes.test} записей.
        {' '}Все условия одной конфигурации и seed находятся в одном разделе.
      </Text>}
      {full && overall && <Text mt={2} color={SIMULATION_THEME.textSecondary}>
        Сводно по восьми областям: {percent(overall.test_balanced_accuracy)}% на {overall.test_realizations} записях из {overall.test_groups} конфигураций.
        {overall.group_bootstrap_95_interval && ` Интервал при повторной выборке конфигураций: ${overall.group_bootstrap_95_interval.map(percent).join('–')}%.`}
      </Text>}
      <Text mt={2} color={SIMULATION_THEME.textSecondary}>{full
        ? 'Распознаётся условие входа синтетической модели при известной области. Выборка небольшая; слабые воздействия различаются менее устойчиво. Это не распознавание боли.'
        : 'Проверка относится к синтетической локальной модели.'}</Text>
      <Box as="table" mt={4} w="full" sx={{ 'th,td': { borderBottom: '1px solid rgba(138,144,162,.2)', padding: '8px', textAlign: 'left' }, 'td[data-error="true"]': { color: 'orange.200' } }}>
        <caption style={{ textAlign: 'left', marginBottom: 8 }}>Матрица ошибок: строки — истинный класс, столбцы — предсказанный</caption>
        <thead><tr><th>Условие</th>{evaluation.classes.map(name => <th key={name}>{labels[name]}</th>)}</tr></thead>
        <tbody>{evaluation.confusion_matrix.map((row, i) => <tr key={i}><th>{labels[evaluation.classes[i]]}</th>{row.map((value, j) => <td key={j} data-error={i !== j && value > 0}>{value}</td>)}</tr>)}</tbody>
      </Box>
    </Box>}
  </Stack>;
}
