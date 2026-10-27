import asyncio
import logging

logger = logging.getLogger(__name__)


class BackgroundTaskManager:
    """Manages background tasks with automatic restart on failure."""

    def __init__(self):
        self.tasks: list[asyncio.Task] = []
        self.running = False

    async def start_task_with_restart(self, coro_func, task_name: str, restart_delay: int = 5):
        # Registration has no await: callers on this loop cannot race between
        # checking ownership and publishing the newly created task.
        self.tasks[:] = [task for task in self.tasks if not task.done()]
        for task in self.tasks:
            if task.get_name() == task_name:
                return task

        component = {
            "file-scan-loop": "file_scan",
            "new-jobs-processor": "job_processor",
        }.get(task_name, "background_task")

        async def task_wrapper():
            restart_count = 0
            while self.running:
                try:
                    logger.info("Background task starting", extra={"component": component})
                    await coro_func()
                except asyncio.CancelledError:
                    logger.info("Background task cancelled", extra={"component": component})
                    break
                except Exception:
                    restart_count += 1
                    logger.warning(
                        "Background task unavailable",
                        extra={
                            "component": component,
                            "failure_code": "unavailable",
                            "attempt": restart_count,
                        },
                    )
                # Returning is also a stopped loop, not permission to spin. Both
                # successful exits and failures yield before the next attempt.
                if self.running:
                    try:
                        await asyncio.sleep(restart_delay)
                    except asyncio.CancelledError:
                        break

            logger.info("Background task stopped", extra={"component": component})

        task = asyncio.create_task(task_wrapper())
        task.set_name(task_name)
        self.tasks.append(task)
        return task

    async def start(self):
        self.running = True

    async def stop(self):
        self.running = False

        logger.info("Stopping all background tasks...")
        for task in self.tasks:
            task.cancel()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

        self.tasks.clear()
        logger.info("All background tasks stopped")
