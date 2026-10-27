import React, { createRef, useState } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import AppSelect from '../../../src/shared/controls/AppSelect';
import { ChoicePanelGroup } from '../../../src/shared/controls/ChoicePanel';
import ComposerModeSelector from '../../../src/features/chat/components/composer/ComposerModeSelector';
import ComposerPersonaSelector from '../../../src/features/chat/components/composer/ComposerPersonaSelector';
import ModelSelector from '../../../src/features/chat/components/ModelSelector';
import ChatComposerPanel from '../../../src/features/chat/components/composer/ChatComposerPanel';

const wrapper = ({ children }) => <ChakraProvider>{children}</ChakraProvider>;
const personas = [
  { id: 'engineer', label: 'Инженер', hint: 'Технические объяснения' },
  { id: 'analyst', label: 'Аналитик', hint: 'Работа с данными' },
  { id: 'scientist', label: 'Учёный', hint: 'Научные источники' },
];

beforeEach(() => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
});

it('matches a compact trigger with an icon palette and only the focused mode explanation', async () => {
  const change = jest.fn();
  render(<ChoicePanelGroup compact><ComposerModeSelector mobileIconOnly onChange={change} /></ChoicePanelGroup>, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Режим: Авто' }));
  const input = await screen.findByRole('combobox', { name: 'Выбор режима' });
  const web = screen.getByRole('option', { name: 'Веб-поиск', exact: true });
  expect(screen.getAllByRole('option')).toHaveLength(5);
  expect(web).not.toHaveTextContent('Актуальные сведения');
  expect(web.querySelectorAll('svg')).toHaveLength(1);
  fireEvent.mouseMove(web);
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  await waitFor(() => expect(screen.getAllByRole('tooltip').some(item => item.textContent.includes('Дольше и дороже'))).toBe(true));
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(change).toHaveBeenCalledWith('deep_research');
});

it('offers touch-accessible descriptions without selecting a mode and compact strategy controls', async () => {
  const change = jest.fn();
  const planning = jest.fn();
  render(<ChoicePanelGroup compact><ComposerModeSelector mobileIconOnly onChange={change}
    onTogglePlanning={planning} onToggleMultiIntent={() => {}} /></ChoicePanelGroup>, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Режим: Авто' }));
  const checkbox = await screen.findByRole('button', { name: 'Планирование', exact: true });
  expect(checkbox).toHaveAttribute('aria-pressed', 'false');
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  fireEvent.focus(checkbox);
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Всегда строить план');
  fireEvent.click(checkbox);
  expect(planning).toHaveBeenCalledTimes(1);
  expect(change).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Показать описания режимов' }));
  expect(screen.queryByRole('note', { name: 'Описание режима' })).not.toBeInTheDocument();
  expect(within(screen.getByRole('option', { name: /Веб-поиск/ })).getByText(/С надбавкой за поиск/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Скрыть описания режимов' }));
  expect(screen.getByRole('option', { name: 'Веб-поиск', exact: true })).not.toHaveTextContent('С надбавкой за поиск');
  expect(change).not.toHaveBeenCalled();
});

it('keeps the ordinary AppSelect single-select contract', async () => {
  const change = jest.fn();
  render(<AppSelect value="a" options={[{ value: 'a', label: 'Один' }, { value: 'b', label: 'Два' }]} ariaLabel="Поле" onChange={change} />, { wrapper });
  const input = screen.getByRole('combobox', { name: 'Поле' });
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: 'Два' }));
  expect(change).toHaveBeenCalledWith('b');
});

it('owns one strategy explanation and dismisses it after activation or blur', async () => {
  render(<ChoicePanelGroup compact><ComposerModeSelector mobileIconOnly
    onTogglePlanning={() => {}} onToggleMultiIntent={() => {}} /></ChoicePanelGroup>, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Режим: Авто' }));
  const multi = await screen.findByRole('button', { name: 'Мульти-интент', exact: true });
  const plan = screen.getByRole('button', { name: 'Планирование', exact: true });
  fireEvent.focus(multi);
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Мульти-интент');
  fireEvent.focus(plan);
  await waitFor(() => expect(screen.getAllByRole('tooltip')).toHaveLength(1));
  expect(screen.getByRole('tooltip')).toHaveTextContent('Планирование');
  fireEvent.click(plan);
  await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument());
  fireEvent.focus(multi);
  expect(await screen.findByRole('tooltip')).toBeInTheDocument();
  fireEvent.blur(multi);
  await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument());
});

it('compacts persona and model descriptions with the same explicit detail control', async () => {
  const view = render(<ChoicePanelGroup compact><ComposerPersonaSelector mobileIconOnly personas={personas} /></ChoicePanelGroup>, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Личность: Без личности' }));
  await screen.findByRole('combobox', { name: 'Выбор личностей' });
  expect(screen.queryByText('Технические объяснения')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Без личности', exact: true })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Показать описания личностей' }));
  expect(screen.getByText('Технические объяснения')).toBeInTheDocument();
  view.unmount();
  render(<ChoicePanelGroup compact><ModelSelector mobileIconOnly availableModels={['GigaChat-2-Max']}
    catalog={{ 'GigaChat-2-Max': { context_window: 131072, cost_tier: 2, capabilities: ['tools'] } }} /></ChoicePanelGroup>, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Модель: Авто' }));
  await screen.findByRole('combobox', { name: 'Поиск модели' });
  expect(screen.queryByText('Инструменты')).not.toBeInTheDocument();
  expect(screen.queryByText('Повышенная стоимость')).not.toBeInTheDocument();
  expect(screen.getByRole('img', { name: 'Повышенная стоимость' })).toBeInTheDocument();
  expect(screen.getByRole('img', { name: 'Инструменты' })).toBeInTheDocument();
  expect(screen.getByRole('img', { name: /токенов/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Показать описания моделей' }));
  expect(screen.getByText('Инструменты')).toBeInTheDocument();
  expect(screen.queryByRole('img', { name: 'Повышенная стоимость' })).not.toBeInTheDocument();
});

it('dismisses a choice hint on wheel or scroll without reopening a stale anchor', async () => {
  render(<ChoicePanelGroup compact><ComposerModeSelector mobileIconOnly
    onTogglePlanning={() => {}} onToggleMultiIntent={() => {}} /></ChoicePanelGroup>, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Режим: Авто' }));
  const multi = await screen.findByRole('button', { name: 'Мульти-интент', exact: true });
  const planning = screen.getByRole('button', { name: 'Планирование', exact: true });
  fireEvent.focus(multi);
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Мульти-интент');
  fireEvent.wheel(multi, { deltaY: 120 });
  await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument());
  fireEvent.focus(planning);
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Планирование');
  fireEvent.scroll(window);
  await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument());
});

it('keeps compact model metadata icon-only and explains the keyboard-focused row', async () => {
  const change = jest.fn();
  render(<ChoicePanelGroup compact><ModelSelector mobileIconOnly onChange={change}
    availableModels={['GigaChat-2-Max']}
    catalog={{ 'GigaChat-2-Max': { cost_tier: 2, capabilities: ['vision', 'audio', 'files', 'image_out', 'tools', 'tools', 'unknown', {}] } }} />
  </ChoicePanelGroup>, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Модель: Авто' }));
  const input = await screen.findByRole('combobox', { name: 'Поиск модели' });
  const row = screen.getByRole('option', { name: /GigaChat-2-Max/ });
  expect(within(row).getAllByRole('img')).toHaveLength(6);
  expect(row).toHaveTextContent(/^GigaChat-2-Max$/);
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Повышенная стоимость');
  expect(screen.getByRole('tooltip')).toHaveTextContent('Изображения на входе');
  expect(row).toHaveAttribute('aria-describedby', screen.getByRole('tooltip').id);
  expect(input).toHaveAttribute('aria-activedescendant', row.id);
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(change).toHaveBeenCalledWith('GigaChat-2-Max');
  await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument());
});

it('keeps the library keyboard input without visible dummy search chrome in simple panels', async () => {
  const change = jest.fn();
  render(<AppSelect presentation="composer" isSearchable={false} ariaLabel="Простой выбор"
    value="a" options={[{ value: 'a', label: 'Один' }, { value: 'b', label: 'Два' }]}
    onChange={change} />, { wrapper });
  const input = screen.getByRole('combobox', { name: 'Простой выбор' });
  // VisuallyHidden clips the control, not its accessibility tree or library input.
  expect(input.closest('[class]')).not.toHaveAttribute('aria-hidden', 'true');
  act(() => input.focus());
  expect(input).toHaveFocus();
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(change).toHaveBeenCalledWith('b');
});

it('preserves leading-persona order and disables only unselected options at the cap', async () => {
  const change = jest.fn();
  render(<ComposerPersonaSelector personas={personas} value={['analyst', 'engineer']} onChange={change} />, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Личность: Аналитик + Инженер' }));
  const blocked = await screen.findByRole('option', { name: /Учёный/ });
  expect(blocked).toHaveAttribute('aria-disabled', 'true');
  fireEvent.click(blocked);
  expect(change).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('option', { name: /Инженер/ }));
  expect(change).toHaveBeenCalledWith(['analyst']);
});

it('offers explicit persona clearing and one shared open panel', async () => {
  const clear = jest.fn();
  render(<ChoicePanelGroup><ComposerModeSelector /><ComposerPersonaSelector personas={personas} value={['engineer']} onChange={clear} /></ChoicePanelGroup>, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Режим: Авто' }));
  expect(await screen.findByRole('combobox', { name: 'Выбор режима' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Личность: Инженер' }));
  expect(await screen.findByRole('combobox', { name: 'Выбор личностей' })).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole('combobox', { name: 'Выбор режима' })).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: 'Без личности', exact: true }));
  expect(clear).toHaveBeenCalledWith([]);
});

it('uses a modal bottom sheet with explicit close on mobile', async () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 393 });
  render(<ComposerModeSelector />, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Режим: Авто' }));
  const dialog = await screen.findByRole('dialog');
  expect(dialog).toHaveAttribute('aria-modal', 'true');
  expect(screen.getByRole('button', { name: 'Закрыть: Режим ответа' })).toBeInTheDocument();
});

it('bounds the mobile model sheet and keeps descriptions opt-in without a duplicate close shelf', async () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 393 });
  const change = jest.fn();
  render(<ModelSelector mobileIconOnly availableModels={['GigaChat-2-Max']} onChange={change}
    catalog={{ 'GigaChat-2-Max': { capabilities: ['tools'] } }} />, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Модель: Авто' }));
  const dialog = await screen.findByRole('dialog', { name: 'Модель ответа' });
  expect(dialog).toHaveStyle({ width: '280px' });
  expect(dialog.style.maxWidth).toBe('calc(100vw - 24px)');
  expect(screen.queryByRole('button', { name: 'Закрыть', exact: true })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Закрыть: Модель ответа', exact: true })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Показать описания моделей' }));
  expect(dialog).toHaveStyle({ width: '320px' });
  await act(async () => fireEvent.click(screen.getByRole('option', { name: /GigaChat-2-Max/ })));
  expect(change).toHaveBeenCalledWith('GigaChat-2-Max');
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Модель ответа' })).not.toBeInTheDocument());
});

it('uses icon-only mobile choices with full accessible names and an independent context slot', () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 });
  render(<ChatComposerPanel fileInputRef={createRef()} personas={personas} isAuthenticated
    contextInfo={{ hasWindow: true, pct: 0, tokens: 0, windowTokens: 100000 }} />, { wrapper });
  for (const name of ['Режим: Авто', 'Личность: Без личности', 'Модель: Авто']) {
    const trigger = screen.getByRole('button', { name });
    expect(trigger.textContent).toBe('');
    expect(trigger.querySelectorAll('svg')).toHaveLength(1);
    expect(trigger).toHaveAttribute('title', name);
  }
  expect(screen.getByRole('textbox', { name: 'Сообщение' })).toHaveAttribute('placeholder', 'Сообщение…');
  const gauge = screen.getByRole('button', { name: /Контекст заполнен на 0%/ });
  expect(gauge.parentElement).toHaveAttribute('data-composer-context');
  expect(gauge).toHaveTextContent('0');
  expect(gauge.querySelector('svg')).toHaveAttribute('viewBox', '0 0 30 30');
  expect(gauge.querySelector('.ctx-gauge-ring')).toHaveStyle({ opacity: 0 });
  expect(gauge).toHaveAttribute('title', 'Контекст: 0%');
  const controls = Array.from(screen.getByRole('group', { name: 'Настройки сообщения' }).querySelectorAll('button'));
  expect(controls.map((button) => button.getAttribute('aria-label'))).toEqual([
    'Режим: Авто', 'Личность: Без личности', 'Модель: Авто',
    'Контекст заполнен на 0%. Сжать в долговременную память',
    'Доступность ИИ неизвестна',
  ]);
});

it('retains desktop composer labels and labelled mobile model controls outside the composer', () => {
  const desktop = render(<ChatComposerPanel fileInputRef={createRef()} personas={personas} isAuthenticated />, { wrapper });
  expect(screen.getByRole('button', { name: 'Режим: Авто' })).toHaveTextContent('Режим: Авто');
  expect(screen.getByRole('button', { name: 'Личность: Без личности' })).toHaveTextContent('Личность: Без личности');
  expect(screen.getByRole('button', { name: 'Модель: Авто' })).toHaveTextContent('Модель: Авто');
  desktop.unmount();
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 393 });
  render(<ModelSelector selectedModel="GigaChat-2" availableModels={['GigaChat-2']} />, { wrapper });
  expect(screen.getByRole('button', { name: 'Модель: GigaChat-2' })).toHaveTextContent('Модель: GigaChat-2');
});

it('ignores unconfirmed or malformed model metadata', async () => {
  render(<ModelSelector availableModels={['GigaChat-2']} catalog={{ 'GigaChat-2': {
    context_window: 'unknown', capabilities: ['unknown', 'constructor', {}, 'tools'],
  } }} />, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Модель: Авто' }));
  const model = await screen.findByRole('option', { name: /GigaChat-2/ });
  expect(model).toHaveTextContent('Инструменты');
  expect(model).not.toHaveTextContent('unknown');
  expect(model).not.toHaveTextContent('NaN');
});

it('filters, clears and expands the model catalog without changing the current selection', async () => {
  const models = Array.from({ length: 65 }, (_, index) => `openai/model-${String(index).padStart(3, '0')}`);
  const change = jest.fn();
  render(<ModelSelector availableModels={models} selectedModel="openai/model-064" onChange={change} />, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Модель: model-064' }));
  const search = await screen.findByRole('combobox', { name: 'Поиск модели' });
  fireEvent.click(await screen.findByRole('button', { name: /Показать ещё/ }));
  expect(await screen.findByRole('option', { name: 'model-064' })).toBeInTheDocument();
  fireEvent.change(search, { target: { value: 'missing' } });
  expect(await screen.findByText(/Ничего не найдено\. Измените/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Очистить поиск' }));
  expect(search).toHaveValue('');
  expect(change).not.toHaveBeenCalled();
});

it('keeps unavailable selections and exposes catalog retry', async () => {
  const retry = jest.fn();
  const change = jest.fn();
  render(<ModelSelector selectedModel="GigaChat-2" modelStatus="error" onRetry={retry} onChange={change} />, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Модель: GigaChat-2' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить загрузку' }));
  expect(retry).toHaveBeenCalledTimes(1);
  expect(change).not.toHaveBeenCalled();
});

it('retains the message through choices and protects IME and streaming Escape', async () => {
  const submit = jest.fn();
  const stop = jest.fn();
  const composer = createRef();
  const base = { onSubmit: submit, onStop: stop, fileInputRef: createRef(), attachments: [], availableModels: [], isAuthenticated: true };
  const rendered = render(<ChatComposerPanel ref={composer} {...base} />, { wrapper });
  const input = screen.getByRole('textbox', { name: 'Сообщение' });
  fireEvent.input(input, { target: { value: 'Сохранённый текст' } });
  fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
  expect(submit).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
  expect(submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Режим: Авто' }));
  const modes = await screen.findByRole('combobox', { name: 'Выбор режима' });
  fireEvent.keyDown(modes, { key: 'Escape' });
  expect(input).toHaveValue('Сохранённый текст');
  rendered.rerender(<ChatComposerPanel ref={composer} {...base} isStreaming />);
  fireEvent.click(screen.getByRole('button', { name: 'Режим: Авто' }));
  fireEvent.keyDown(await screen.findByRole('combobox', { name: 'Выбор режима' }), { key: 'Escape' });
  expect(stop).not.toHaveBeenCalled();
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(stop).toHaveBeenCalledTimes(1));
  expect(composer.current.getInputValue()).toBe('Сохранённый текст');
});

it('blocks both click and Enter for a confirmed unavailable model without erasing text', () => {
  const submit = jest.fn();
  render(<ChatComposerPanel onSubmit={submit} fileInputRef={createRef()} selectedModel="GigaChat-2" availableModels={['GigaChat-2-Pro']} />, { wrapper });
  const input = screen.getByRole('textbox', { name: 'Сообщение' });
  fireEvent.input(input, { target: { value: 'Запрос' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(screen.getByRole('button', { name: 'Отправить' })).toBeDisabled();
  expect(submit).not.toHaveBeenCalled();
  expect(input).toHaveValue('Запрос');
});

it('keeps attachments, voice preview and typed text through picker selection and resize', async () => {
  const discard = jest.fn();
  const remove = jest.fn();
  function Harness() {
    const [model, setModel] = useState('');
    return <ChatComposerPanel fileInputRef={createRef()} isAuthenticated
      availableModels={['GigaChat-2']} selectedModel={model} onModelChange={setModel}
      attachments={[{ file_id: 'fixture-file', filename: 'fixture.txt', file_type: 'text' }]}
      onRemoveAttachment={remove} voiceText="Синтетический голосовой текст" onDiscardVoice={discard} />;
  }
  render(<Harness />, { wrapper });
  const input = screen.getByRole('textbox', { name: 'Сообщение' });
  fireEvent.input(input, { target: { value: 'Сохранённый ввод' } });
  fireEvent.click(screen.getByRole('button', { name: 'Модель: Авто' }));
  fireEvent.click(await screen.findByRole('option', { name: 'GigaChat-2' }));
  await act(async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 393 });
    window.dispatchEvent(new Event('resize'));
  });
  expect(input).toHaveValue('Сохранённый ввод');
  expect(screen.getByText('fixture.txt (text)')).toBeInTheDocument();
  expect(screen.getByText('Синтетический голосовой текст')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Модель: GigaChat-2' })).toBeInTheDocument();
  expect(discard).not.toHaveBeenCalled();
  expect(remove).not.toHaveBeenCalled();
});

it('announces strategy checkboxes and preserves immediate selection', async () => {
  function Modes() {
    const [value, setValue] = useState(null);
    return <ComposerModeSelector value={value} onChange={setValue} onTogglePlanning={() => {}} onToggleMultiIntent={() => {}} />;
  }
  render(<Modes />, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Режим: Авто' }));
  expect(await screen.findByRole('checkbox', { name: /Планирование/ })).toBeInTheDocument();
  expect(screen.queryByRole('option', { name: /Презентация/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('option', { name: /Обычный/ }));
  expect(screen.getByRole('button', { name: 'Режим: Обычный' })).toBeInTheDocument();
});
