/** Bounded, linear-time comparison of in-memory text; never a Git/write receipt. */
function section(before, after, title) {
  if (before === after) return `${title}\nОтличий нет.`;
  const left = before.split('\n');
  const right = after.split('\n');
  let start = 0;
  let end = 0;
  while (start < Math.min(left.length, right.length) && left[start] === right[start]) start += 1;
  while (end < Math.min(left.length, right.length) - start
    && left[left.length - end - 1] === right[right.length - end - 1]) end += 1;
  const render = (lines, sign) => {
    const changed = lines.slice(start, lines.length - end);
    const bounded = changed.length > 40
      ? [...changed.slice(0, 20), '… строки пропущены …', ...changed.slice(-20)] : changed;
    return bounded.map(line => `${sign} ${line.length > 400 ? `${line.slice(0, 400)} … строка сокращена` : line}`).join('\n');
  };
  return `${title}\nСо строки ${start + 1}; −${left.length - start - end} / +${right.length - start - end}\n${render(left, '−')}\n${render(right, '+')}`;
}

export function ideDraftComparison(file, actual) {
  const text = [section(file.original ?? file.content, file.content, 'Основа → ваш черновик'),
    section(file.original ?? file.content, actual, 'Основа → файл в среде')].join('\n\n');
  return text.length > 12000 ? `${text.slice(0, 12000)}\n… сравнение сокращено …` : text;
}

export function ideReviewedConflict(file, actual, generation) {
  const full = actual.kind === 'text' && !actual.truncated;
  return { path: file.path, generation, actual, actualContent: full ? actual.content : null,
    diff: full ? ideDraftComparison(file, actual.content) : '',
    notice: !full ? 'Файл в среде двоичный или показан не полностью. Замена черновика недоступна.'
      : actual.content === file.content ? 'Сейчас файл в среде совпадает с вашим текстом. Повторная запись не требуется.'
        : 'Сверка ничего не записывает. Загрузка проверенной версии заменит ваш черновик в редакторе.' };
}
