const THREAD = 'library-contract-thread';

/** Current shared Library on Chat, not the retired Work page or a real account. */
async function installLibraryApi(page) {
  const state = {
    items: [{ file_id: 'file-opaque-1', name: 'brief.txt', file_type: 'text/plain', availability: 'ready' }],
    nextCursor: null, mutations: [], pages: [],
  };
  await page.addInitScript(() => {
    localStorage.setItem('telerag:isAuthenticated', 'true');
    localStorage.setItem('auth_token', 'synthetic-library-test-token');
  });
  await page.routeWebSocket('**/api/**', () => {});
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    let json = {};
    if (!['GET', 'HEAD'].includes(request.method())) state.mutations.push(path);
    if (path === '/api/profile/me') json = { id: 'library-user', email: 'library@example.test', permissions: [] };
    if (path === '/api/chats/') json = { chats: [{ thread_id: THREAD, title: 'Проверка библиотеки' }] };
    if (path === `/api/chats/${THREAD}`) json = { messages: [] };
    if (path.endsWith('/trace')) json = { traces: {} };
    if (path === '/api/chats/personas') json = { personas: [] };
    if (path === '/api/chats/transcription/config') json = { enabled: false };
    if (path.startsWith('/api/chats/models')) json = path.endsWith('/catalog')
      ? { models: [{ id: 'GigaChat-2', capabilities: ['tools'], context_window: 131072 }], providers: [] }
      : { models: ['GigaChat-2'] };
    if (path === '/api/billing/balance') json = { total: 10000 };
    if (path.endsWith('/work')) json = {
      contract_version: 2,
      workspace: { state: 'absent', entries: [], history: [], revision: '' },
      room: { state: 'absent', leases: [], activity: [] },
      library: { state: 'ready', items: state.items, next_cursor: state.nextCursor, next_offset: null },
    };
    if (path === '/api/chats/work-library') {
      const params = { offset: Number(url.searchParams.get('offset') || 0),
        limit: Number(url.searchParams.get('limit') || 10), q: url.searchParams.get('q') || '' };
      state.pages.push(params);
      const matches = state.items.filter(item => item.name.toLocaleLowerCase('ru').includes(params.q.toLocaleLowerCase('ru')));
      const page = state.readPage ? await state.readPage(params) : {
        json: { state: 'ready', items: matches.slice(params.offset, params.offset + params.limit),
          next_cursor: null, next_offset: matches.length > params.offset + params.limit ? params.offset + params.limit : null },
      };
      await route.fulfill(page);
      return;
    }
    await route.fulfill({ json });
  });
  await page.goto(`/chat/${THREAD}`, { waitUntil: 'domcontentloaded' });
  await page.getByRole('textbox', { name: 'Сообщение', exact: true }).waitFor();
  return state;
}

module.exports = { installLibraryApi, THREAD };
