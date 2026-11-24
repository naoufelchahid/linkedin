from types import SimpleNamespace
from unittest.mock import Mock

from linkedin_applications.worker import Worker


def test_group_approval_only_resumes_displayed_versions(tmp_path):
    telegram = Mock(chat=12)
    telegram.buttons.return_value = {"message_id": 50}
    runner = Mock()
    worker = Worker(SimpleNamespace(data=tmp_path), runner, telegram)
    pending = {
        key: {
            "question": {"id": key, "kind": "mail", "version": key},
            "offer": {"title": key},
            "draft": {"recipient": "example@example.org"},
        }
        for key in ("first", "second")
    }
    worker.telegram_state["prompts"] = {"first": 10, "second": 11}
    worker.notify_mail_group(pending)
    pending["second"]["question"]["version"] = "updated"
    callback = {
        "id": "callback",
        "data": "mail_group:approve",
        "message": {"chat": {"id": 12}, "message_id": 50},
        "from": {"id": 12},
    }
    telegram.call.side_effect = [[{"update_id": 3, "callback_query": callback}], {}]
    first = pending["first"]
    worker.receive(pending)
    runner.run.assert_called_once_with(first, {"id": "first", "choice": "approve"})
    assert list(pending) == ["second"]
