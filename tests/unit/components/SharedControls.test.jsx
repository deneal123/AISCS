import React from 'react';
import { ChakraProvider } from '@chakra-ui/react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ActionLink from '../../../src/shared/controls/ActionLink';
import AppSelect from '../../../src/shared/controls/AppSelect';
import AppTextarea from '../../../src/shared/controls/AppTextarea';

function renderUi(node) {
  return render(
    <ChakraProvider>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        {node}
      </MemoryRouter>
    </ChakraProvider>,
  );
}

describe('canonical shared controls', () => {
  it('keeps navigation as a semantic link with button styling', () => {
    renderUi(<ActionLink to="/chat/thread?surface=work">Открыть работу</ActionLink>);

    const link = screen.getByRole('link', { name: 'Открыть работу' });
    expect(link).toHaveAttribute('href', '/chat/thread?surface=work');
    expect(screen.queryByRole('button', { name: 'Открыть работу' })).not.toBeInTheDocument();
  });

  it('owns the non-resizable textarea contract', () => {
    renderUi(<AppTextarea aria-label="Описание" defaultValue="draft" />);

    const textarea = screen.getByRole('textbox', { name: 'Описание' });
    expect(textarea).toHaveClass('resize-none');
    expect(textarea).toHaveStyle({ resize: 'none' });
  });

  it('exposes an authored keyboard listbox and returns the option value', () => {
    const onChange = jest.fn();
    renderUi(
      <AppSelect
        ariaLabel="Провайдер"
        value=""
        onChange={onChange}
        options={[
          { value: 'openrouter', label: 'OpenRouter' },
          { value: 'gigachat', label: 'GigaChat' },
        ]}
      />,
    );

    const combobox = screen.getByRole('combobox', { name: 'Провайдер' });
    fireEvent.focus(combobox);
    fireEvent.keyDown(combobox, { key: 'ArrowDown' });
    expect(combobox).toHaveFocus();
    fireEvent.keyDown(combobox, { key: 'Enter' });

    expect(onChange).toHaveBeenCalledWith('openrouter');
  });
});
