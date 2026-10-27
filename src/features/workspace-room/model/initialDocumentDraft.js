/** Shared deterministic starter for the editor and explicit new-document flow. */
export function initialDocumentDraft(presentation = false) {
  return presentation ? {
    schema_version: 1, version: 1, title: 'Новая презентация',
    blocks: [{ block_id: 'slide_1', kind: 'slide', title: 'Первый слайд', text: 'Добавьте содержание слайда.' }],
  } : { title: 'Новый документ', text: 'Начните редактирование документа здесь.' };
}
