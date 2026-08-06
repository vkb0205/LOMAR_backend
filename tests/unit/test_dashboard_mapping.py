"""Dashboard mapper unit tests — T030."""

from app.schemas.dashboard import TaskStatus
from app.services.dashboard import map_dashboard_tasks, map_dashboard_vouchers


def test_task_mapper_matches_frontend_defaults_and_normalization():
    mapped = map_dashboard_tasks(
        [
            {"id": "task-1", "name": None, "is_mandatory": None},
            {"id": "task-2", "name": "Task", "is_mandatory": True},
        ],
        [{"task_id": "task-1", "status": "COMPLETED"}],
    )
    assert [task.model_dump() for task in mapped] == [
        {"taskId": "task-1", "name": "Nhiệm vụ", "isMandatory": False, "status": TaskStatus.completed},
        {"taskId": "task-2", "name": "Task", "isMandatory": True, "status": TaskStatus.pending},
    ]


def test_voucher_mapper_matches_frontend_defaults():
    assert map_dashboard_vouchers(
        [{"id": "voucher-1", "title": None, "discount_value": 25, "required_task_id": None}],
        [],
    )[0].model_dump() == {
        "voucherId": "voucher-1",
        "title": "Voucher",
        "discountValue": "25",
        "status": "locked",
        "requiredTaskId": None,
    }
