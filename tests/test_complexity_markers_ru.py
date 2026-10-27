from service.domain.routing.complexity import has_complex_markers


def test_comparison_requests_are_recognized_in_common_russian_forms() -> None:
    assert has_complex_markers("Сравни варианты PostgreSQL и MySQL")
    assert has_complex_markers("Сравните PostgreSQL с MySQL")
    assert has_complex_markers("Сравнение PostgreSQL и MySQL")


def test_analysis_requests_are_recognized_with_imperative_verb() -> None:
    assert has_complex_markers("Проанализируй рынок")
    assert has_complex_markers("Проведи анализ рынка")


def test_unrelated_short_request_does_not_trigger_complexity_marker() -> None:
    assert not has_complex_markers("Какая погода сегодня?")
