from datetime import datetime, timedelta, timezone

import pytest

from llm_chat.runtime import Capability, RunManager
from llm_chat.storage import Storage
from llm_chat.work import (
    ArtifactKind,
    GrantScope,
    GrantStatus,
    PlanStatus,
    PlanStepStatus,
    ResourceGrantService,
    ResourceType,
    WorkItemService,
)


@pytest.fixture
def services(tmp_path):
    Storage.set_instance(None)
    storage = Storage(str(tmp_path / "plans-and-grants.db"))
    work_items = WorkItemService(
        repository=storage,
        runs=RunManager(repository=storage),
    )
    grants = ResourceGrantService(storage)
    yield storage, work_items, grants
    Storage.set_instance(None)


def test_plan_revisions_are_versioned_and_approval_supersedes_previous(services):
    storage, work_items, _ = services
    item = work_items.create(objective="交付架构审计")
    first = work_items.create_plan_revision(
        item.id,
        summary="先审计再交付",
        steps=[
            {
                "id": "audit",
                "title": "审计代码",
                "required_capabilities": ["read"],
            },
            {
                "id": "report",
                "title": "生成报告",
                "depends_on": ["audit"],
                "expected_artifact_kind": ArtifactKind.REPORT,
            },
        ],
        approve=True,
    )

    assert first.version == 1
    assert first.status == PlanStatus.APPROVED
    assert first.steps[1].depends_on == [first.steps[0].id]

    second = work_items.create_plan_revision(
        item.id,
        summary="增加复核",
        change_summary="在交付前增加人工复核",
        steps=[
            {"title": "审计代码"},
            {"title": "复核结论"},
            {"title": "生成报告"},
        ],
    )

    with pytest.raises(ValueError, match="only the latest"):
        work_items.approve_plan_revision(item.id, first.id)

    approved = work_items.approve_plan_revision(item.id, second.id)
    history = work_items.list_plan_revisions(item.id)

    assert approved.status == PlanStatus.APPROVED
    assert [plan.version for plan in history] == [2, 1]
    assert storage.get_plan_revision(first.id).status == PlanStatus.SUPERSEDED


def test_only_approved_plan_steps_can_be_projected(services):
    _, work_items, _ = services
    item = work_items.create(objective="执行计划")
    draft = work_items.create_plan_revision(
        item.id,
        summary="执行两步",
        steps=[{"title": "准备"}, {"title": "交付"}],
    )

    with pytest.raises(ValueError, match="no approved plan"):
        work_items.update_plan_step(
            item.id,
            draft.steps[0].id,
            PlanStepStatus.RUNNING,
        )

    work_items.approve_plan_revision(item.id, draft.id)
    updated = work_items.update_plan_step(
        item.id,
        draft.steps[0].id,
        PlanStepStatus.COMPLETED,
    )

    assert updated.steps[0].status == PlanStepStatus.COMPLETED
    assert work_items.detail(item.id).plan.id == draft.id


def test_plan_rejects_dependency_cycles(services):
    _, work_items, _ = services
    item = work_items.create(objective="执行循环计划")

    with pytest.raises(ValueError, match="contain a cycle"):
        work_items.create_plan_revision(
            item.id,
            summary="无效计划",
            steps=[
                {"id": "first", "title": "第一步", "depends_on": ["second"]},
                {"id": "second", "title": "第二步", "depends_on": ["first"]},
            ],
        )


def test_directory_grant_matches_descendants_and_relative_workspace_paths(services):
    _, work_items, grants = services
    item = work_items.create(
        objective="更新报告",
        workspace="/workspace/project",
    )
    grant = grants.create(
        work_item_id=item.id,
        capability=Capability.WORKSPACE_WRITE.value,
        resource_type=ResourceType.DIRECTORY,
        resource="/workspace/project/reports",
    )

    allowed = grants.authorizes_tool(
        work_item_id=item.id,
        workflow_id=None,
        tool_name="write_file",
        arguments={"path": "reports/result.md"},
        capabilities={Capability.WORKSPACE_WRITE},
        workspace=item.workspace,
    )
    escaped = grants.authorizes_tool(
        work_item_id=item.id,
        workflow_id=None,
        tool_name="write_file",
        arguments={"path": "../outside.md"},
        capabilities={Capability.WORKSPACE_WRITE},
        workspace=item.workspace,
    )

    assert allowed is True
    assert escaped is False
    assert grants.repository.get_resource_grant(grant.id).last_used_at is not None


def test_process_capability_is_never_bypassed_by_directory_grant(services):
    _, work_items, grants = services
    item = work_items.create(objective="运行命令")
    grants.create(
        work_item_id=item.id,
        capability=Capability.WORKSPACE_WRITE.value,
        resource_type=ResourceType.DIRECTORY,
        resource="/workspace/project",
    )

    assert (
        grants.authorizes_tool(
            work_item_id=item.id,
            workflow_id=None,
            tool_name="shell_exec",
            arguments={"cwd": "/workspace/project"},
            capabilities={Capability.PROCESS, Capability.WORKSPACE_WRITE},
        )
        is False
    )


def test_once_grant_is_consumed_and_expired_grant_is_not_authoritative(services):
    storage, work_items, grants = services
    item = work_items.create(objective="发送通知")
    once = grants.create(
        work_item_id=item.id,
        capability=Capability.EXTERNAL_MESSAGE.value,
        resource_type=ResourceType.MESSAGE_TARGET,
        resource="team@example.com",
        scope=GrantScope.ONCE,
    )

    first = grants.authorizes_tool(
        work_item_id=item.id,
        workflow_id=None,
        tool_name="send_email",
        arguments={"recipient": "TEAM@example.com"},
        capabilities={Capability.EXTERNAL_MESSAGE},
    )
    second = grants.authorizes_tool(
        work_item_id=item.id,
        workflow_id=None,
        tool_name="send_email",
        arguments={"recipient": "team@example.com"},
        capabilities={Capability.EXTERNAL_MESSAGE},
    )

    assert first is True
    assert second is False
    assert storage.get_resource_grant(once.id).status == GrantStatus.REVOKED

    expired = grants.create(
        work_item_id=item.id,
        capability=Capability.NETWORK.value,
        resource_type=ResourceType.DOMAIN,
        resource="example.com",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert (
        grants.authorizes_tool(
            work_item_id=item.id,
            workflow_id=None,
            tool_name="web_fetch",
            arguments={"url": "https://docs.example.com/page"},
            capabilities={Capability.NETWORK},
        )
        is False
    )
    assert storage.get_resource_grant(expired.id).status == GrantStatus.EXPIRED


def test_grant_revoke_is_auditable_and_idempotent(services):
    storage, work_items, grants = services
    item = work_items.create(objective="写入文件")
    created = grants.create(
        work_item_id=item.id,
        capability=Capability.WORKSPACE_WRITE.value,
        resource_type=ResourceType.DIRECTORY,
        resource="/workspace",
        reason="仅允许当前任务写入",
    )

    revoked = grants.revoke(created.id)
    repeated = grants.revoke(created.id)

    assert revoked.status == GrantStatus.REVOKED
    assert revoked.revoked_at is not None
    assert repeated.revoked_at == revoked.revoked_at
    assert storage.get_resource_grant(created.id).reason == "仅允许当前任务写入"
