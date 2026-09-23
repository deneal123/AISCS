import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChakraProvider } from '@chakra-ui/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import LoginPage from '@pages/login';

const mockLogin = jest.fn();
const mockVerify = jest.fn();
const mockNavigateState = { refreshSession: jest.fn(), setAuthenticated: jest.fn() };

jest.mock('@api', () => ({
  ...jest.requireActual('@api'),
  login: (...args) => mockLogin(...args),
  verifyEmailCode: (...args) => mockVerify(...args),
}));
// Мокаем useAuth на уровне исходного модуля, а не барреля @features/auth —
// мок барреля ломает его циклические внутренние экспорты (AUTH_THEME и т.п.).
jest.mock('@features/auth/model/AuthContext', () => ({
  ...jest.requireActual('@features/auth/model/AuthContext'),
  useAuth: () => mockNavigateState,
}));

function renderLogin() {
  return render(
    <MemoryRouter
      initialEntries={['/login']}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <ChakraProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          {/* Логин ведёт на /chat (см. LoginWidget: from ?? "/chat"), а не на корень. */}
          <Route path="/chat" element={<div>CHAT</div>} />
          <Route path="/" element={<div>HOME</div>} />
        </Routes>
      </ChakraProvider>
    </MemoryRouter>
  );
}

async function submitCredentials() {
  await act(async () => {
    await userEvent.type(screen.getByLabelText(/e-mail/i), 'user@test.dev');
    await userEvent.type(screen.getByLabelText(/пароль/i, { selector: 'input' }), 'secret123');
    await userEvent.click(screen.getByRole('button', { name: /войти/i }));
  });
}

describe('Auth integration', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  // Логин двухшаговый: пароль → код на почту → verify. Куку ставит только verify,
  // поэтому после первого шага пользователь ещё НЕ авторизован и редиректа нет.
  it('после пароля просит код из письма, а не пускает сразу', async () => {
    mockLogin.mockResolvedValue({ status: 'code_sent', email: 'user@test.dev' });

    renderLogin();
    await submitCredentials();

    await waitFor(() =>
      expect(mockLogin).toHaveBeenCalledWith({ email: 'user@test.dev', password: 'secret123' })
    );
    // Экран ввода кода показан, на главную не пустили.
    await waitFor(() => expect(screen.getAllByRole('textbox').length).toBeGreaterThanOrEqual(6));
    expect(screen.queryByText('CHAT')).not.toBeInTheDocument();
    expect(mockNavigateState.refreshSession).not.toHaveBeenCalled();
  }, 10_000);

  it('подтверждение кода открывает сессию и уводит в чат', async () => {
    mockLogin.mockResolvedValue({ status: 'code_sent', email: 'user@test.dev' });
    mockVerify.mockResolvedValue({ jwt: 'token-123' });
    mockNavigateState.refreshSession.mockResolvedValue();

    renderLogin();
    await submitCredentials();

    // Ждём именно ШЕСТЬ полей: на форме логина textbox уже есть (email), поэтому
    // findAllByRole вернулся бы мгновенно — до того, как отрисуется экран кода.
    await waitFor(() => expect(screen.getAllByRole('textbox')).toHaveLength(6));

    // PinInput контролируемый: каждая цифра меняет state и перерисовывает поля,
    // поэтому ячейки перезапрашиваем на каждом шаге. На шестой срабатывает onComplete.
    for (let i = 0; i < 6; i += 1) {
      await act(async () => {
        await userEvent.type(screen.getAllByRole('textbox')[i], String(i + 1));
      });
    }

    await waitFor(() =>
      expect(mockVerify).toHaveBeenCalledWith({ email: 'user@test.dev', code: '123456' })
    );
    await waitFor(() => expect(screen.getByText('CHAT')).toBeInTheDocument());
  }, 10_000);
});
