import { act, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import ChatPageSurfaceShell from '@features/chat/components/ChatPageSurfaceShell';
import { WorkHub } from '@features/workspace-room';

jest.mock('@features/workspace-room', () => ({
  WorkHub: jest.fn(() => <div data-testid="library-owner">Library/PDF owner</div>),
  IdeStudio: () => <div data-testid="ide-owner">IDE owner</div>,
}));
jest.mock('@features/chat/components/ChatHeaderBar', () => () => <div>Header</div>);
jest.mock('@features/chat/components/ChatMessagesArea', () => () => <div>Messages</div>);
jest.mock('@features/chat/components/composer/ChatComposerPanel', () => () => <div>Composer</div>);

it('opening IDE never mounts the legacy snapshot/Library controller until it is needed', async () => {
  const props = { sidebar: { collapsed: true, render: () => null }, header: { surface: 'work' }, work: { mounted: true, active: true, props: { threadId: 'thread' } }, chat: { messages: {}, composer: {} } };
  let view;
  await act(async () => { view = render(<ChakraProvider><ChatPageSurfaceShell {...props} /></ChakraProvider>); });
  expect(screen.getByTestId('ide-owner')).toBeInTheDocument();
  expect(WorkHub).not.toHaveBeenCalled();
  await act(async () => view.rerender(<ChakraProvider><ChatPageSurfaceShell {...props} work={{ ...props.work, props: { threadId: 'thread', libraryOpen: true } }} /></ChakraProvider>));
  expect(screen.getByTestId('library-owner')).toBeInTheDocument();
  expect(WorkHub.mock.calls.at(-1)[0]).toMatchObject({ active: false, surface: 'hidden', libraryOpen: true });
});

it.each(['disabled', 'isStreaming', 'isFileUploading', 'isRecording', 'isRequestingPermission', 'isVoiceTranscribing', 'compacting'])(
  'pauses peer hints while the composer is %s', async flag => {
    const props = { sidebar: { render: () => null }, header: { surface: 'chat' },
      work: { mounted: false, active: false, props: {} }, chat: { messages: {}, composer: {} } };
    let view;
    await act(async () => { view = render(<ChakraProvider><ChatPageSurfaceShell {...props} /></ChakraProvider>); });
    expect(view.container.querySelector('[data-action-hints-paused]')).toHaveAttribute('data-action-hints-paused', 'false');
    await act(async () => view.rerender(<ChakraProvider><ChatPageSurfaceShell {...props}
      chat={{ ...props.chat, composer: { [flag]: true } }} /></ChakraProvider>));
    expect(view.container.querySelector('[data-action-hints-paused]')).toHaveAttribute('data-action-hints-paused', 'true');
  },
);
