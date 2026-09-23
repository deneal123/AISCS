import { describe, expect, it } from '@jest/globals';

import { resolveArtifactUrl } from '../../../src/features/chat/utils/artifactUrl';


describe('generated chat artifacts', () => {
  it('downloads durable generated files through the authenticated file-id route', () => {
    const url = resolveArtifactUrl(null, 'document.pdf', 'opaque file/id');

    expect(url).toMatch(/\/api\/service\/files\/v1\/opaque%20file%2Fid\/download$/);
    expect(url).not.toContain('file_key');
  });

  it('keeps the legacy storage-key proxy for old messages', () => {
    const url = resolveArtifactUrl('CHAT/generated/document.pdf', 'document.pdf');

    expect(url).toContain('/api/chats/files/download?');
    expect(url).toContain('file_key=CHAT%2Fgenerated%2Fdocument.pdf');
  });
});
