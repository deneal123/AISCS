"""An admitted UI mutation invalidates prior verification before touching source."""

from uuid import uuid4

from sqlalchemy import text

from service.services.chat.persistence.harness.state import save_checkpoint, snapshot


async def invalidate_external_write(connector, workspace_id):
    # Called only by the signed UI preflight while workspace's operation lock is
    # held. A failed/unknown subsequent write conservatively requires rechecking.
    async with connector.get_session_context() as db:
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT t.*,j.payload AS job_payload FROM profile.harness_task t "
                        "JOIN profile.user_launch j ON j.id=t.active_job_id "
                        "WHERE (t.admission->>'workspace_id'=:workspace OR "
                        "EXISTS(SELECT 1 FROM profile.harness_operation c "
                        "WHERE c.task_id=t.task_id AND c.command_workspace_id=:workspace)) "
                        "AND t.admission->>'surface'='ide' "
                        "AND t.checkpoint IS NOT NULL AND (j.status='PROCESSING' OR "
                        "(j.status='SUCCESS' AND "
                        "j.payload->'metadata'->'task_result'->>'status'='waiting_user' AND "
                        "EXISTS(SELECT 1 FROM profile.human_question q "
                        "LEFT JOIN profile.user_launch child ON child.id=q.resume_job_id "
                        "WHERE q.source_job_id=t.active_job_id AND q.user_id=t.user_id "
                        "AND q.thread_id=t.thread_id AND q.surface='ide' "
                        "AND CAST(q.project_id AS text)=t.admission->>'project_id' "
                        "AND ((q.state='pending' AND q.expires_at>clock_timestamp()) OR "
                        "(q.state='accepted' AND child.user_id=t.user_id AND child.type='CHAT' "
                        "AND child.status IN ('NEW','PROCESSING')))))) FOR UPDATE OF t"
                    ),
                    {"workspace": workspace_id},
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            current = await snapshot(db, row)
            if current.state is not None:
                await save_checkpoint(
                    db,
                    row,
                    state=current.state.advance(source_revision="external:" + str(uuid4())),
                    continuation=current.continuation,
                )
        await db.commit()
