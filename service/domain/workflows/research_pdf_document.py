"""Evidence-backed research followed by an audited PDF article or report."""

from service.domain.capabilities.agent_spec import COST_EXPENSIVE
from service.domain.capabilities.workflow_spec import WorkflowSpec, WorkflowStep

SPEC = WorkflowSpec(
    name="research_pdf_document",
    label_ru="исследование и PDF-документ",
    cost_class=COST_EXPENSIVE,
    confirm_by_default=True,
    prompt_hint=(
        "просят подготовить статью или отчёт в PDF по проверяемым внешним источникам; "
        "сначала требуется research evidence, затем типизированный Document Forge"
    ),
    steps=(
        WorkflowStep(
            agent="deep_research",
            instruction="Собери проверяемые источники и evidence registry по теме: {user_input}",
        ),
        WorkflowStep(
            agent="pdf_gen",
            instruction=(
                "Создай PDF-статью или отчёт только по зарегистрированным источникам. "
                "Исходная просьба: {user_input}"
            ),
        ),
    ),
)
