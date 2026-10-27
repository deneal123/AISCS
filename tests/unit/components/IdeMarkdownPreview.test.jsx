import { fireEvent, render, screen } from '@testing-library/react';
import IdeMarkdownPreview from '@features/workspace-room/components/IdeMarkdownPreview';

jest.mock('@features/chat', () => ({
  MessageRenderer: require('@features/chat/components/MessageRenderer').default,
  PROSE_SX: require('@features/chat/page/proseStyles').PROSE_SX,
}));

it('renders headings, lists and GFM tables without changing repository text', () => {
  render(<IdeMarkdownPreview file={{ path: 'README.md', content: '# Проект\n\n- Исходники\n- Тесты\n\n| Имя | Роль |\n| --- | --- |\n| src | Код |\n\n`<think>literal</think>`' }} onOpen={jest.fn()} />);
  expect(screen.getByRole('heading', { name: 'Проект' })).toBeVisible();
  expect(screen.getByRole('list')).toHaveTextContent('Исходники');
  expect(screen.getByRole('table')).toHaveTextContent('src');
  expect(screen.getByText('<think>literal</think>')).toBeInTheDocument();
});

it('does not execute HTML, auto-load images or navigate unsafe links', () => {
  const onOpen = jest.fn();
  render(<IdeMarkdownPreview file={{ path: 'docs/README.md', content: '[Источник](../src/main.py)\n\n[Сайт](https://example.test/)\n\n[Небезопасно](javascript:alert%281%29)\n\n![Картинка](https://example.test/track.png)\n\n<img src=x onerror=alert(1)>' }} onOpen={onOpen} />);
  fireEvent.click(screen.getByRole('link', { name: 'Источник' }));
  expect(onOpen).toHaveBeenCalledWith('src/main.py');
  expect(screen.getByRole('link', { name: 'Сайт' })).toHaveAttribute('rel', 'noopener noreferrer');
  expect(screen.queryByRole('link', { name: 'Небезопасно' })).not.toBeInTheDocument();
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});

it('navigates Unicode and duplicate heading anchors locally with keyboard focus', () => {
  const onOpen = jest.fn();
  const content = '[Второй](#%D1%80%D0%B0%D0%B7%D0%B4%D0%B5%D0%BB-1)\n\n## Раздел\n\n## Раздел';
  render(<IdeMarkdownPreview file={{ path: 'README.md', content }} onOpen={onOpen} />);
  const headings = screen.getAllByRole('heading', { name: 'Раздел' });
  expect(headings[0]).toHaveAttribute('data-repository-anchor', 'раздел');
  expect(headings[1]).toHaveAttribute('data-repository-anchor', 'раздел-1');
  fireEvent.click(screen.getByRole('link', { name: 'Второй' }));
  expect(headings[1]).toHaveFocus();
  expect(onOpen).not.toHaveBeenCalled();
});

it('scopes user-derived anchors to this preview and never changes the route for missing fragments', () => {
  const onOpen = jest.fn();
  const location = window.location.href;
  const content = '[Локально](#main)\n\n[Нет раздела](#missing)\n\n[Неверный](#%ZZ)\n\n## main';
  const view = render(<><IdeMarkdownPreview file={{ path: 'other.md', content: '## main' }} onOpen={onOpen} />
    <IdeMarkdownPreview file={{ path: 'README.md', content }} onOpen={onOpen} /></>);
  const headings = screen.getAllByRole('heading', { name: 'main' });
  expect(headings[0].id).not.toBe(headings[1].id);
  expect(view.container.querySelector('#main')).toBeNull();
  fireEvent.click(screen.getByRole('link', { name: 'Локально' }));
  expect(headings[1]).toHaveFocus();
  fireEvent.click(screen.getByRole('link', { name: 'Нет раздела' }));
  fireEvent.click(screen.getByRole('link', { name: 'Неверный' }));
  expect(window.location.href).toBe(location);
  expect(onOpen).not.toHaveBeenCalled();
});
