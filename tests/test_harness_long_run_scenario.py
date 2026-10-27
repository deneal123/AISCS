"""Корпус действительно содержит16 раундов и проверяемую многомодульную задачу."""

from scripts.harness_live.long_run import criteria, files
from scripts.harness_live.scenarios import next_step, steps


def test_long_scenario_has_six_distinct_writes_and_real_check_inside_limit():
    plan = steps("long")
    assert len(plan) == 16 and plan[-1][0] == "ide_finish_task"
    assert len(files()) == len(criteria()) == 6
    written = [args["path"] for name, args in plan if name == "ide_write_file"]
    assert len(set(written)) == 6
    command = [args for name, args in plan if name == "ide_run_command"]
    assert len(command) == 1 and command[0]["expected_stdout"] == "hello world\n"
    assert all(item["kind"] == "file" for item in criteria())
    completed = []
    for item in plan:
        assert next_step("long", completed) == item
        completed.append(item[0])
    assert next_step("long", completed) is None
