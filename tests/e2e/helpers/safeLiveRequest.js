const FAILURE_CODES = Object.freeze({
  create_thread: 'live_thread_create_unavailable',
  delete_thread: 'live_thread_cleanup_unavailable',
  delete_file: 'live_file_cleanup_unavailable',
  read_file: 'live_file_read_unavailable',
  write_response: 'live_write_response_unavailable',
});

// Playwright API transport exceptions include cookie headers in their call log.
// A live test must fail without copying its authentication capability to output.
async function safeLiveRequest(operation, invoke) {
  try {
    return await invoke();
  } catch {
    throw new Error(FAILURE_CODES[operation] || 'live_request_unavailable');
  }
}

module.exports = { safeLiveRequest };
