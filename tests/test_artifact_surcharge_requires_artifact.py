"""Надбавка за генерацию файла берётся только когда файл создан.

🔴 ЖИВАЯ ЖАЛОБА. «изобрази Елизавету Смирнову» → картинка сгенерирована, tool=none,
83 кредита. Follow-up «перегенерируй с другим цветом волос» → картинка НЕ вышла
(провайдер image-модальности вернул ответ без изображения, пользователь получил
текстовый промпт-фолбэк), tool=image_gen — и надбавка image_gen 5₽ × маржа 2.5 = 4166
кредитов легла на пользователя за изображение, которого он не получил. Итого 4198.

Полная инверсия: за УСПЕШНУЮ картинку надбавки не взяли, за ПРОВАЛ — взяли. Надбавка
image_gen/pptx_gen берётся по решению роутера, но платой за файл может быть только
когда файл есть. Тот же принцип, что уже применён в image_gen usage и web_search: с
пользователя — только за полученное.
"""

from __future__ import annotations

# ⚠️ Импорт из НАСТОЯЩЕГО места (`pricing_signals`), а не из воркера: раньше функция
# проходила через `chat_worker_tasks` транзитом, и тест зависел от чужого импорта.
from service.services.chat.infrastructure.pricing_signals import _pricing_signals


def _result(tool, *, file_url=None, meta_extra=None):
    metadata = {"model_routing": {"tool": tool}}
    if meta_extra:
        metadata.update(meta_extra)
    return {"file_url": file_url, "metadata": metadata}


def test_image_gen_surcharge_skipped_without_artifact():
    """⚠️ ГЛАВНОЕ. tool=image_gen, но картинки нет → надбавка НЕ начисляется."""
    _, tools = _pricing_signals(_result("image_gen", file_url=None))
    assert "image_gen" not in tools, (
        "надбавка за картинку взята, хотя файла нет — пользователь платит за "
        "неполученное изображение (живой случай: 4166 кредитов)"
    )


def test_image_gen_surcharge_applied_with_artifact():
    """Картинка ЕСТЬ (file_url) → надбавка правомерна."""
    _, tools = _pricing_signals(_result("image_gen", file_url="https://s3/img.png"))
    assert "image_gen" in tools, "за реально созданную картинку надбавка не взята"


def test_artifact_seen_via_metadata_b64():
    """Артефакт может прийти инлайном (b64_json) до сохранения в стор — тоже считается."""
    _, tools = _pricing_signals(_result("image_gen", meta_extra={"b64_json": "iVBOR..."}))
    assert "image_gen" in tools


def test_pptx_gen_also_gated_on_artifact():
    """Тот же принцип для презентаций: нет файла → нет надбавки."""
    _, no = _pricing_signals(_result("pptx_gen", file_url=None))
    assert "pptx_gen" not in no
    _, yes = _pricing_signals(_result("pptx_gen", meta_extra={"pptx_b64": "UEsDB..."}))
    assert "pptx_gen" in yes


def test_non_artifact_tools_are_not_gated():
    """⚠️ web_search/deep_research НЕ трогаем: их надбавка — за работу, не за файл.

    Иначе гейт артефакта молча обнулил бы законные надбавки за поиск/ресёрч, у которых
    файла нет по определению.
    """
    _, tools = _pricing_signals(_result("web_search", file_url=None))
    assert "web_search" in tools, "надбавка за веб-поиск пропала — она не про артефакт"


def test_multi_intent_artifact_unlocks_step_surcharge():
    """Мульти-интент: артефакт под-шага лежит в multi_intent_artifacts."""
    result = {
        "file_url": None,
        "metadata": {
            "model_routing": {"tool": "general"},
            "steps": ["image_gen", "web_search"],
            "multi_intent_artifacts": [{"b64_json": "..."}],
        },
    }
    _, tools = _pricing_signals(result)
    assert "image_gen" in tools and "web_search" in tools


def test_multi_intent_charges_only_produced_artifact_type():
    """⚠️ БАГ-СТЫК (мульти-интент + гейт артефакта). pptx удался, картинка НЕТ →
    надбавка pptx_gen ЕСТЬ, image_gen НЕТ.

    Грубый гейт «есть хоть какой-то артефакт» разрешал обе надбавки: за картинку, которой
    пользователь не получил, тоже брали (тот же класс, что чинили для одиночного пути).
    """
    result = {
        "file_url": None,
        "metadata": {
            "model_routing": {"tool": "general"},
            "steps": ["pptx_gen", "image_gen"],
            # Артефакт ТОЛЬКО презентации — картинка не сгенерировалась.
            "multi_intent_artifacts": [{"pptx_b64": "UEsDB..."}],
        },
    }
    _, tools = _pricing_signals(result)

    assert "pptx_gen" in tools, "презентация создана — надбавка за неё правомерна"
    assert "image_gen" not in tools, (
        "надбавка за картинку, которой нет — пользователь платит за непроизведённое изображение"
    )


def test_multi_intent_both_artifacts_both_billed():
    """Оба артефакта созданы → обе надбавки правомерны."""
    result = {
        "file_url": None,
        "metadata": {
            "model_routing": {"tool": "general"},
            "steps": ["pptx_gen", "image_gen"],
            "multi_intent_artifacts": [{"pptx_b64": "UEs..."}, {"b64_json": "iVBOR..."}],
        },
    }
    _, tools = _pricing_signals(result)

    assert "pptx_gen" in tools and "image_gen" in tools


def test_image_url_extension_distinguishes_type():
    """file_url различается по расширению: .pptx → pptx, .png → image."""
    r_png = {
        "file_url": "https://s3/x.png?sig=1",
        "metadata": {"model_routing": {"tool": "image_gen"}},
    }
    r_pptx = {
        "file_url": "https://s3/x.pptx?sig=1",
        "metadata": {"model_routing": {"tool": "pptx_gen"}},
    }

    assert "image_gen" in _pricing_signals(r_png)[1]
    assert "pptx_gen" not in _pricing_signals(r_png)[1], "png не должен оплачивать pptx_gen"
    assert "pptx_gen" in _pricing_signals(r_pptx)[1]
