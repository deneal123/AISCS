import React from 'react';
import { ChakraProvider } from '@chakra-ui/react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import PricingPanel from '../../../src/features/admin/components/PricingPanel';
import {
  deleteAdminPricing,
  getAdminPricing,
  getAdminReconcile,
  putAdminPricing,
} from '../../../src/shared/api/admin';

jest.mock('../../../src/shared/api/admin', () => ({
  deleteAdminPricing: jest.fn(),
  getAdminPricing: jest.fn(),
  getAdminReconcile: jest.fn(),
  putAdminPricing: jest.fn(),
}));

const MODEL_ID = 'shared/model';
const PRICING = [
  {
    provider: 'openrouter', model_id: MODEL_ID, priced: true,
    price_in_rub_per_1k: 0.1, price_out_rub_per_1k: 0.2,
  },
  {
    provider: 'routerai', model_id: MODEL_ID, priced: true,
    price_in_rub_per_1k: 0.3, price_out_rub_per_1k: 0.4,
  },
];

const renderPanel = () => render(<ChakraProvider><PricingPanel /></ChakraProvider>);

beforeEach(() => {
  Element.prototype.scrollIntoView = jest.fn();
  getAdminPricing.mockResolvedValue({
    pricing: PRICING,
    pricing_sync: {
      providers: [
        {
          provider: 'openrouter', level: 'warning', freshness_seconds: 90000,
          synced_models: 378, next_action: 'Запланируйте обновление каталога в ближайшее время.',
        },
      ],
    },
  });
  getAdminReconcile.mockResolvedValue(null);
  putAdminPricing.mockResolvedValue({});
  deleteAdminPricing.mockResolvedValue({});
});

afterEach(() => jest.clearAllMocks());

describe('provider-aware pricing rows', () => {
  it('shows actionable pricing freshness without changing the provider rows', async () => {
    renderPanel();

    const region = await screen.findByRole('region', { name: 'Статус свежести тарифов' });
    expect(region).toHaveTextContent('openrouter');
    expect(region).toHaveTextContent('warning');
    expect(region).toHaveTextContent('378 моделей');
    expect(region).toHaveTextContent('Запланируйте обновление каталога');
  });

  it('keeps pricing usable and exposes a retry when reconciliation is unavailable', async () => {
    getAdminReconcile.mockRejectedValueOnce(new Error('service unavailable'));
    renderPanel();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Не удалось загрузить сверку себестоимости');
    expect(screen.getAllByRole('button', { name: 'Изменить' })).toHaveLength(2);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    });
    await waitFor(() => expect(getAdminReconcile).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });

  it('edits a duplicate model_id using its selected provider', async () => {
    renderPanel();

    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Изменить' })).toHaveLength(2));
    fireEvent.click(screen.getAllByRole('button', { name: 'Изменить' })[1]);

    expect(screen.getByRole('combobox', { name: 'Провайдер' }))
      .toHaveAttribute('aria-expanded', 'false');
    expect(screen.getAllByText('routerai').length).toBeGreaterThan(0);
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Вход, ₽ за 1K' }), { target: { value: '0.35' } });
    fireEvent.click(screen.getByRole('button', { name: 'Обновить' }));

    await waitFor(() => expect(putAdminPricing).toHaveBeenCalledWith({
      provider: 'routerai',
      model_id: MODEL_ID,
      price_in_rub_per_1k: 0.35,
      price_out_rub_per_1k: 0.4,
    }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить' })).toBeInTheDocument());
  });

  it('deletes only the matching provider/model pair', async () => {
    renderPanel();

    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Удалить' })).toHaveLength(2));
    fireEvent.click(screen.getAllByRole('button', { name: 'Удалить' })[1]);
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить' }));

    await waitFor(() => expect(deleteAdminPricing).toHaveBeenCalledWith(MODEL_ID, 'routerai'));
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Удалить' })).toHaveLength(2));
  });
});
