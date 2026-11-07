import React from 'react';
import { render, screen } from '@testing-library/react';
import DiscretizationNotice from '../../../src/features/simulator/recording/DiscretizationNotice';

test('shows checked geometry without claiming numerical convergence', () => {
  render(<DiscretizationNotice geometry={{ checked_events: 623, relocated_endpoints: 8,
    max_shift_um: 0.2344 }} />);
  expect(screen.getByText(/проверено событий — 623/)).toHaveTextContent('0.234 мкм');
  expect(screen.getByText(/Численная сходимость не подтверждена/)).toBeInTheDocument();
});

test('old or malformed records retain the uncertainty warning', () => {
  const { rerender } = render(<DiscretizationNotice />);
  expect(screen.getByText(/могут передаваться некорректно/)).toBeInTheDocument();
  rerender(<DiscretizationNotice geometry={{ checked_events: 1, relocated_endpoints: 2 }} />);
  expect(screen.getByText(/могут передаваться некорректно/)).toBeInTheDocument();
});
