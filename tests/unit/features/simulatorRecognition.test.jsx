import React from 'react';
import { render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import RecognitionSummary from '../../../src/features/simulator/RecognitionSummary';

const evaluation = { test_balanced_accuracy: .5, test_realizations: 12, test_groups: 4,
  sizes: { train: 36, validation: 12, test: 12 }, classes: ['none', 'strong', 'weak'],
  confusion_matrix: [[3, 1, 0], [0, 3, 1], [2, 2, 0]] };
const show = preview => render(<ChakraProvider><RecognitionSummary preview={preview} stimulus="weak" regionName="Голова" /></ChakraProvider>);

test('whole-CNS report separates region groups, pooled coverage and recorded errors', () => {
  show({ connectome: {}, prediction: { class: 'none', region: 'head', evaluation,
    overall_evaluation: { test_balanced_accuracy: .71875, test_realizations: 96, test_groups: 32, group_bootstrap_95_interval: [.61458, .8125] } } });
  expect(screen.getByText(/12 записей из 4 конфигураций/)).toBeInTheDocument();
  expect(screen.getByText(/96 записях из 32 конфигураций/)).toBeInTheDocument();
  expect(screen.getByRole('table')).toHaveTextContent('Матрица ошибок');
  expect(screen.getByText(/Это не распознавание боли/)).toBeInTheDocument();
  expect(screen.queryByText(/54 \/ 18 \/ 18/)).not.toBeInTheDocument();
});

test('an out-of-domain recording remains readable without a fabricated prediction', () => {
  show({ connectome: {}, prediction: null, prediction_status: { state: 'outside_checked_domain', reason: 'Положение REF выходит за проверенные условия.' } });
  expect(screen.getByRole('status')).toHaveTextContent('Положение REF');
  expect(screen.getByText(/предсказание недоступно/)).toBeInTheDocument();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});

test('historical local report keeps its own saved sizes', () => {
  show({ prediction: { class: 'weak', evaluation: { ...evaluation, test_realizations: 18, sizes: { train: 54, validation: 18, test: 18 } } } });
  expect(screen.getByText(/54 \/ 18 \/ 18/)).toBeInTheDocument();
  expect(screen.queryByText(/Сводно по восьми областям/)).not.toBeInTheDocument();
});
