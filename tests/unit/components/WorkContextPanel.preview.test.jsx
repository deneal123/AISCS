import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { WorkContextPanel } from '@features/workspace-room/components/WorkContextPanel';

jest.mock('@features/workspace-room/components/WorkIssuesPanel', () => ({
  WorkIssuesPanel: () => <input aria-label="Текст задачи" defaultValue="" />,
}));
jest.mock('@features/workspace-room/components/WorkHistoryPanel', () => ({
  WorkHistoryPanel: () => null,
}));
jest.mock('@features/workspace-room/components/AgentActivityPanel', () => ({
  AgentActivityPanel: () => null,
}));
jest.mock('@features/workspace-room/components/DocumentForgePanel', () => ({
  DocumentForgePanel: ({ previewVisible }) => (
    <>
      <input aria-label="Путь проекта" defaultValue="documents/paper" />
      {previewVisible && <iframe title="Предпросмотр PDF" src="about:blank" />}
    </>
  ),
}));

it('keeps Work issue drafts and leaves PDF preview to the dedicated surface', () => {
  const view = render(<ChakraProvider><WorkContextPanel previewVisible /></ChakraProvider>);
  const issue = screen.getByLabelText('Текст задачи');
  fireEvent.change(issue, { target: { value: 'Несохранённая задача' } });
  expect(screen.queryByTitle('Предпросмотр PDF')).not.toBeInTheDocument();
  expect(screen.queryByRole('tab', { name: 'PDF' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'История' }));
  view.rerender(<ChakraProvider><WorkContextPanel previewVisible={false} /></ChakraProvider>);
  expect(screen.queryByTitle('Предпросмотр PDF')).not.toBeInTheDocument();
  view.rerender(<ChakraProvider><WorkContextPanel previewVisible /></ChakraProvider>);
  expect(screen.queryByTitle('Предпросмотр PDF')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'Задачи' }));
  expect(screen.queryByTitle('Предпросмотр PDF')).not.toBeInTheDocument();
  expect(issue).toBe(screen.getByLabelText('Текст задачи'));
  expect(issue).toHaveValue('Несохранённая задача');
});

it('uses its owning Work selection when a responsive panel is replaced', () => {
  const changeTab = jest.fn();
  const view = render(
    <ChakraProvider>
      <WorkContextPanel key="rail" selectedTab={2} onTabChange={changeTab} />
    </ChakraProvider>,
  );
  expect(screen.getByRole('tab', { name: 'Агент' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.queryByTitle('Предпросмотр PDF')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'История' }));
  expect(changeTab).toHaveBeenCalledWith(1);
  view.rerender(
    <ChakraProvider>
      <WorkContextPanel key="drawer" selectedTab={1} onTabChange={changeTab} />
    </ChakraProvider>,
  );
  expect(screen.getByRole('tab', { name: 'История' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.queryByTitle('Предпросмотр PDF')).not.toBeInTheDocument();
});
