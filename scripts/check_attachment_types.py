"""Гейт: файл, который backend УМЕЕТ разобрать, обязан быть выбираемым во фронте.

🔴 Живая жалоба: «.py вообще нельзя прикрепить». Причина оказалась не в отказе загрузки —
backend кодовые файлы давно принимает (`_CODE_EXTENSIONS` → `file_type="code"`), — а в том,
что в `<input accept="…">` кодовых расширений не было вовсе. Способность есть, двери к ней
нет, и никакой тест этого увидеть не мог: у каждой стороны свой список, и они разошлись
молча.

⚠️ ПАРСИМ ОБА ФАЙЛА, а не заводим третью копию. Заводить общий источник значило бы связать
фронт с питоновским модулем рантайм-зависимостью ради константы; гейт даёт то же
соответствие бесплатно — тот же приём, которым `check_sidecar_env.py` разбирает
`settings.py` через AST.

Проверяется ОДНОСТОРОННЕЕ включение: всё, что backend разбирает как код, обязано быть в
`accept`. Обратное неверно намеренно — фронт предлагает и то, чего в кодовом списке нет
(документы, таблицы, картинки), и это не расхождение.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend/service/services/chat/application/use_cases/upload_file_use_case.py"
COMPOSER = ROOT / "frontend/src/features/chat/components/composer/ChatComposerPanel.jsx"


def backend_code_extensions() -> set[str]:
    """`_CODE_EXTENSIONS` из исходника backend — через AST, а не регуляркой по тексту."""
    tree = ast.parse(BACKEND.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "_CODE_EXTENSIONS" not in names:
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            break
        return {
            e.value.lower()
            for e in node.value.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        }
    raise SystemExit(f"НЕ НАЙДЕН `_CODE_EXTENSIONS` в {BACKEND.relative_to(ROOT)}")


def composer_accepts() -> set[str]:
    """Содержимое `accept="…"` у поля выбора файла."""
    match = re.search(r'accept="([^"]+)"', COMPOSER.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"НЕ НАЙДЕН `accept` в {COMPOSER.relative_to(ROOT)}")
    return {part.strip().lower() for part in match.group(1).split(",") if part.strip()}


def main() -> int:
    missing = sorted(backend_code_extensions() - composer_accepts())
    if missing:
        print("Backend разбирает эти расширения, а выбрать их во фронте НЕЛЬЗЯ:")
        for ext in missing:
            print(f"  {ext}")
        print(f"\nДобавьте их в `accept` у {COMPOSER.relative_to(ROOT)}.")
        return 1
    print("типы вложений: фронт предлагает всё, что backend разбирает как код")
    return 0


if __name__ == "__main__":
    sys.exit(main())
