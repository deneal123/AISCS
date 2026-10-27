"""Принятые инструкции из того же журнала: только свой проект, generation и модель."""

from sqlalchemy import text

from service.shared.harness_refinement import RefinementAttempt
from service.shared.task_contract import TaskResultV2


async def read_lessons(db, row, current):
    binding = current.continuation.provider
    if binding is None or current.state is None:
        return []
    rows = (
        await db.execute(
            text(
                "SELECT t.continuation->'refinement' AS refinement, "
                "j.payload#>'{metadata,task_result}' AS task_result "
                "FROM profile.harness_task t "
                "JOIN profile.user_launch j ON j.id=t.active_job_id AND j.status='SUCCESS' "
                "WHERE t.user_id=:user AND t.task_id<>:task "
                "AND t.admission->>'project_id'=:project "
                "AND t.admission->>'generation'=:generation AND t.admission->>'surface'=:surface "
                "AND t.admission->>'goal'=:goal "
                "AND t.checkpoint->'state'->'contract'->>'kind'=:kind "
                "AND t.continuation->'provider'->>'provider'=:provider "
                "AND t.continuation->'provider'->>'model'=:model "
                "AND t.continuation->'refinement'->>'adopted'='true' "
                "AND j.payload#>>'{metadata,task_result,status}'='completed' "
                "AND j.payload#>>'{metadata,task_result,schema_version}'='2' "
                "AND j.payload#>>'{metadata,task_result,verified}'='true' "
                "AND COALESCE(j.payload->'_cancel_requested_v1','false'::jsonb)<>'true'::jsonb "
                "ORDER BY t.updated_at DESC,t.task_id LIMIT 3"
            ),
            {
                "user": row["user_id"],
                "task": row["task_id"],
                "project": current.admission.project_id,
                "generation": current.admission.generation,
                "surface": current.admission.surface,
                "goal": current.admission.goal,
                "kind": current.state.contract.kind,
                "provider": binding.provider,
                "model": binding.model,
            },
        )
    ).mappings()
    lessons = []
    for saved in rows:
        try:
            attempt = RefinementAttempt.model_validate(saved["refinement"])
            terminal = TaskResultV2.model_validate(saved.get("task_result"))
        except ValueError:
            continue
        # adopted может быть подтверждён промежуточным чтением result до Stop,
        # конфликта версии или ошибки финализации. SUCCESS — только транспорт.
        if attempt.adopted and terminal.status == "completed":
            lessons.append(attempt.proposal.model_dump(mode="json"))
    return lessons
