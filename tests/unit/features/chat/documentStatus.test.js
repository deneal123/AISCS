import { presentDocumentStatus } from '../../../../src/features/chat/model/documentStatus';


describe('document status presentation', () => {
  it('shows an honest authoring failure before compilation', () => {
    const result = presentDocumentStatus({
      stage: 'section_authoring',
      status: 'failed',
      outcome: 'failed',
      failure_code: 'draft_protocol',
    });

    expect(result.kind).toBe('error');
    expect(result.title).toMatch(/Написание разделов/);
    expect(result.detail).toMatch(/структуру документа/);
    expect(result.detail).not.toMatch(/техническую проверку/);
  });

  it('does not render unknown raw codes', () => {
    const marker = 'PRIVATE_FAILURE_MARKER';
    const result = presentDocumentStatus({
      stage: marker,
      status: marker,
      failure_code: marker,
      retryable: true,
    });

    expect(JSON.stringify(result)).not.toContain(marker);
    expect(result.title).toBe('Подготовка документа: состояние обновлено');
    expect(result.detail).toMatch(/повторить/);
  });
});
