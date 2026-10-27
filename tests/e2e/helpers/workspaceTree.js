/** Reveal existing snapshot folders; no API mutation or file-opening side effect. */
async function revealWorkspaceFile(scope, path, basePath = '') {
  const parts = path.split('/');
  const first = basePath ? basePath.split('/').length + 1 : 1;
  for (let count = first; count < parts.length; count += 1) {
    const folder = scope.locator(`[data-workspace-path="${parts.slice(0, count).join('/')}"]`);
    if (await folder.getAttribute('aria-expanded') === 'false') await folder.click();
  }
  return scope.locator(`[data-testid="workspace-file"][data-workspace-path="${path}"]`);
}

module.exports = { revealWorkspaceFile };
