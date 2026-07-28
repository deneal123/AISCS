"""История обязана начинаться ДО того, как агент что-либо тронул.

🔴 НАЙДЕНО ЗАМЕРОМ. `git init` сам по себе коммита не делает. Репозиторий заводился при
создании песочницы, а ПЕРВАЯ ЗАПИСЬ появлялась только после первого хода — и содержала
вперемешку файлы человека и правки агента. Значит ревизии «как было до агента» не
существовало ни одной, и `ws_revert` вместе с кнопкой «вернуть к снимку» умели откатывать
куда угодно, кроме единственного состояния, ради которого их заводили.

Живой замер: свежая песочница отвечает `versioned: true`, а `history` — пустым списком.

Точек теперь две, и они РАЗНЫЕ:
* «песочница создана» — пустая, ставится при `init`. Для песочницы, где всё создал агент,
  «верни как было» означает «убери всё созданное», и откатываться надо именно сюда.
* «файлы пользователя» — после импорта. Импорт идёт ПОСЛЕ создания, поэтому первая точка
  его не застаёт; без второй нельзя вернуть свои файлы к тому виду, в котором прислал.
"""

from __future__ import annotations

from service import files


def test_init_leaves_a_revision_behind_not_just_a_repository():
    """⚠️ ГЛАВНОЕ. `git init` создаёт репозиторий БЕЗ единого коммита — откатываться некуда."""
    command = files.git_init_command("/workspace", "A <a@b.c>")

    assert "git commit" in command, "после инициализации не остаётся ни одной ревизии"
    assert "--allow-empty" in command, (
        "коммит при создании ПУСТ по содержанию — без этого флага git его не сделает"
    )
    assert files.BASELINE_MESSAGE in command


def test_the_first_point_is_placed_only_once():
    """Идемпотентность: повторный `init` не должен плодить пустые записи в истории."""
    command = files.git_init_command("/workspace", "A <a@b.c>")

    assert "git rev-parse HEAD" in command, (
        "нет проверки «коммиты уже есть» — каждый вызов добавлял бы пустую запись"
    )


def test_success_is_reported_only_after_the_point_exists():
    """🔴 Маркер `__OK__` читается вызывающим как «история заведена» и уезжает в
    `versioned`. Напечатанный ДО коммита, он обещает откат, которого нет, — а поверить в
    такое обещание некому, кроме человека, который потом не найдёт куда возвращаться.

    ⚠️ Считаем маркеры, а не ищем последний: `echo __OK__` раньше по строке и второй в
    конце оставили бы проверку «последний идёт после коммита» зелёной. Именно так и вышло
    при первой мутации.
    """
    command = files.git_init_command("/workspace", "A <a@b.c>")

    assert command.count("echo __OK__") == 1, (
        "успех печатается больше чем в одном месте — хотя бы одно из них не про коммит"
    )
    assert command.index("git config user.email") < command.index("git commit"), (
        "коммит идёт раньше настройки личности — git его отвергнет"
    )
    assert command.index("git commit") < command.index("echo __OK__"), (
        "маркер успеха печатается раньше, чем сделан первый коммит"
    )


def test_the_import_point_is_named_by_what_it_is():
    """Сообщение точки видит человек в панели — «commit 1» ему ничего не скажет."""
    assert files.IMPORT_MESSAGE
    assert files.IMPORT_MESSAGE != files.BASELINE_MESSAGE, (
        "обе точки называются одинаково — в истории их не различить"
    )


def test_the_import_point_goes_through_the_same_commit_command():
    """⚠️ Второй способ коммитить рядом с первым разошёлся бы с ним молча."""
    command = files.git_commit_command("/workspace", files.IMPORT_MESSAGE)

    assert "git add -A" in command, "точка импорта не забрала бы новые файлы в индекс"
    assert files.IMPORT_MESSAGE in command
    assert "__NO_CHANGES__" in command, "повторный импорт без изменений сделал бы пустую запись"


def test_the_import_point_is_wired_into_the_import_handler():
    """🔴 ТОЧКА ВЫЗОВА. Правила выше остаются зелёными, если снимок после импорта не звать.

    В этом проекте промах ловили уже трижды: тест держит ФУНКЦИЮ, а поломка живёт в МЕСТЕ
    ВЫЗОВА. Здесь цена промаха ровно та, ради которой всё и делалось, — ревизии «мои файлы
    до того, как их тронули» снова не будет ни одной.
    """
    import inspect

    import app

    src = inspect.getsource(app.import_files)
    assert "IMPORT_MESSAGE" in src, "импорт не оставляет за собой точки истории"
    assert "_snapshot(" in src, "точка ставится не общей командой коммита"
    assert "if imported" in src, (
        "точка ставится и когда не импортировалось НИЧЕГО — история засорится пустыми записями"
    )


def test_both_points_are_placed_by_the_one_commit_helper():
    """⚠️ Ход и импорт — две точки, но способ их поставить обязан остаться один."""
    import inspect

    import app

    assert "git_commit_command(" in inspect.getsource(app._snapshot)
    for handler in (app.import_files, app.snapshot_workspace):
        src = inspect.getsource(handler)
        assert "git_commit_command(" not in src, (
            f"{handler.__name__} коммитит в обход общего помощника — расходиться они начнут молча"
        )
