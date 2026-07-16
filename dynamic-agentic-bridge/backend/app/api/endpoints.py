"""
REST API endpoints for the Dynamic Agentic Bridge.

All endpoints use Pydantic request/response models.
All I/O boundaries have explicit error handling.
Credentials are encrypted at rest before storage.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.rate_limit import execute_limiter, observe_limiter
from app.core.security import CredentialEncryptor
from app.database import get_db
from app.models.orm import (
    AgentExecutionLog,
    LegacyApplication,
    MappedMCPTool,
    UIStateNode,
)
from app.models.schemas import (
    ApplicationCreate,
    ApplicationResponse,
    ExecutionCreate,
    ExecutionResponse,
    HealthResponse,
    MCPToolResponse,
    ObservationResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_encryptor() -> CredentialEncryptor:
    """Get the credential encryptor. Raises if key is not configured."""
    return CredentialEncryptor(settings.credential_encryption_key)


async def _get_application_or_404(
    app_id: uuid.UUID, db: AsyncSession
) -> LegacyApplication:
    """Fetch a legacy application by ID or raise 404."""
    result = await db.execute(
        select(LegacyApplication).where(LegacyApplication.id == app_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail=f"Application {app_id} not found")
    return app


async def _get_tool_or_404(
    tool_id: uuid.UUID, db: AsyncSession
) -> MappedMCPTool:
    """Fetch a mapped MCP tool by ID or raise 404."""
    result = await db.execute(
        select(MappedMCPTool).where(MappedMCPTool.id == tool_id)
    )
    tool = result.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool {tool_id} not found")
    return tool


async def _get_execution_or_404(
    execution_id: uuid.UUID, db: AsyncSession
) -> AgentExecutionLog:
    """Fetch an execution log by ID or raise 404."""
    result = await db.execute(
        select(AgentExecutionLog).where(AgentExecutionLog.id == execution_id)
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(
            status_code=404, detail=f"Execution {execution_id} not found"
        )
    return log


# ── Health ───────────────────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse()


# ── Applications ─────────────────────────────────────────────────────────────


@router.post(
    "/applications",
    response_model=ApplicationResponse,
    status_code=201,
)
async def create_application(
    body: ApplicationCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new legacy application. Encrypts credentials before storing."""
    encryptor = _get_encryptor()
    encrypted_creds = None
    if body.auth_credentials:
        encrypted_creds = encryptor.encrypt(body.auth_credentials)

    app = LegacyApplication(
        id=uuid.uuid4(),
        name=body.name,
        base_url=body.base_url,
        auth_credentials=encrypted_creds,
    )
    db.add(app)
    await db.flush()
    await db.refresh(app)
    logger.info("Created application %s (%s)", app.name, app.id)
    return app


@router.get("/applications", response_model=list[ApplicationResponse])
async def list_applications(db: AsyncSession = Depends(get_db)):
    """List all registered legacy applications."""
    result = await db.execute(
        select(LegacyApplication).order_by(LegacyApplication.created_at.desc())
    )
    return result.scalars().all()


# ── Observation ──────────────────────────────────────────────────────────────


async def _run_observation_pipeline(
    app_id: uuid.UUID,
    base_url: str,
    auth_credentials_encrypted: str | None,
    session_id: uuid.UUID,
):
    """Background task: run the full observe → map → persist pipeline."""
    from app.core.mcp_generator import process_observation
    from app.core.security import CredentialEncryptor

    async_session_factory = None
    try:
        from app.database import async_session_factory as factory

        async_session_factory = factory
    except ImportError:
        logger.error("Cannot import async_session_factory")
        return

    # Decrypt credentials if present
    auth_creds = None
    if auth_credentials_encrypted:
        try:
            encryptor = CredentialEncryptor(settings.credential_encryption_key)
            auth_creds = encryptor.decrypt(auth_credentials_encrypted)
        except Exception as e:
            logger.error("Failed to decrypt credentials for app %s: %s", app_id, e)

    async with async_session_factory() as db:
        # Create pending execution log
        log = AgentExecutionLog(
            id=uuid.uuid4(),
            session_id=session_id,
            app_id=app_id,
            action_payload={"pipeline": "observe"},
            execution_status="pending",
        )
        db.add(log)
        await db.commit()

        try:
            result = await process_observation(
                db=db,
                app_id=app_id,
                base_url=base_url,
                auth_credentials=auth_creds,
            )
            log.execution_status = "success"
            log.action_payload = result
            logger.info("Observation pipeline succeeded for app %s", app_id)
        except Exception as e:
            log.execution_status = "failed"
            log.error_message = str(e)[:2000]
            logger.error("Observation pipeline failed for app %s: %s", app_id, e)

        await db.commit()


@router.post(
    "/applications/{app_id}/observe",
    response_model=ObservationResponse,
    status_code=202,
)
async def trigger_observation(
    request: Request,
    app_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger the observer + mapper pipeline for a given application.
    Runs as a background task — returns session_id immediately.
    """
    observe_limiter.check(request)
    app = await _get_application_or_404(app_id, db)
    session_id = uuid.uuid4()

    background_tasks.add_task(
        _run_observation_pipeline,
        app_id=app.id,
        base_url=app.base_url,
        auth_credentials_encrypted=app.auth_credentials,
        session_id=session_id,
    )

    logger.info("Queued observation for app %s (session %s)", app_id, session_id)
    return ObservationResponse(
        session_id=session_id,
        status="queued",
        message=f"Observation pipeline triggered for {app.name}",
    )


# ── Tools ────────────────────────────────────────────────────────────────────


@router.get(
    "/applications/{app_id}/tools",
    response_model=list[MCPToolResponse],
)
async def list_tools(
    app_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """List all mapped MCP tools for an application."""
    await _get_application_or_404(app_id, db)

    result = await db.execute(
        select(MappedMCPTool)
        .join(UIStateNode, MappedMCPTool.state_node_id == UIStateNode.id)
        .where(UIStateNode.app_id == app_id)
        .order_by(MappedMCPTool.created_at.desc())
    )
    return result.scalars().all()


# ── Execution ────────────────────────────────────────────────────────────────


async def _execute_tool_action(
    execution_id: uuid.UUID,
    tool_id: uuid.UUID,
    app_id: uuid.UUID,
    action_payload: dict,
):
    """Background task: execute a tool action against the live legacy app."""
    from app.core.executor import execute_tool_action
    from app.core.security import CredentialEncryptor

    async with async_session_factory() as db:
        # Fetch the tool
        tool_result = await db.execute(
            select(MappedMCPTool).where(MappedMCPTool.id == tool_id)
        )
        tool = tool_result.scalar_one_or_none()
        if not tool:
            logger.error("Tool %s not found during execution", tool_id)
            return

        # Fetch the app
        app_result = await db.execute(
            select(LegacyApplication).where(LegacyApplication.id == app_id)
        )
        app = app_result.scalar_one_or_none()
        if not app:
            logger.error("App %s not found during execution", app_id)
            return

        log_result = await db.execute(
            select(AgentExecutionLog).where(AgentExecutionLog.id == execution_id)
        )
        log = log_result.scalar_one_or_none()
        if not log:
            return

        # Decrypt credentials if present
        auth_creds = None
        if app.auth_credentials:
            try:
                encryptor = CredentialEncryptor(settings.credential_encryption_key)
                auth_creds = encryptor.decrypt(app.auth_credentials)
            except Exception as e:
                logger.error("Failed to decrypt credentials: %s", e)

        # Fetch the state node to get the URL path
        node_result = await db.execute(
            select(UIStateNode).where(UIStateNode.id == tool.state_node_id)
        )
        state_node = node_result.scalar_one_or_none()
        url_path = state_node.url_path if state_node else "/"

        try:
            result = await execute_tool_action(
                base_url=app.base_url,
                url_path=url_path,
                element_type=tool.element_type,
                semantic_intent=tool.semantic_intent,
                bounding_box=tool.bounding_box,
                action_params=action_payload,
                auth_credentials=auth_creds,
            )

            if result.success:
                log.execution_status = "success"
            else:
                log.execution_status = "failed"
                log.error_message = result.error_message

            log.screenshot_after_action = result.screenshot_b64
            log.action_payload = {
                **action_payload,
                "tool_semantic_intent": tool.semantic_intent,
                "action_performed": result.action_performed,
                "post_url": result.post_action_url,
            }
            logger.info(
                "Tool execution %s: %s — %s",
                "succeeded" if result.success else "failed",
                execution_id,
                result.action_performed,
            )
        except Exception as e:
            log.execution_status = "failed"
            log.error_message = str(e)[:2000]
            logger.error("Tool execution failed: %s — %s", execution_id, e)

        await db.commit()


@router.post(
    "/tools/{tool_id}/execute",
    response_model=ExecutionResponse,
    status_code=202,
)
async def execute_tool(
    request: Request,
    tool_id: uuid.UUID,
    body: ExecutionCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Execute a mapped tool against the live legacy app.

    If requires_human_approval is true, sets status to 'awaiting_human'
    and does NOT execute until the approve endpoint is called.
    """
    execute_limiter.check(request)
    """
    tool = await _get_tool_or_404(tool_id, db)

    # Fetch the app via the state node
    node_result = await db.execute(
        select(UIStateNode).where(UIStateNode.id == tool.state_node_id)
    )
    state_node = node_result.scalar_one_or_none()
    if not state_node:
        raise HTTPException(
            status_code=404, detail="State node not found for tool"
        )

    session_id = uuid.uuid4()
    initial_status = "awaiting_human" if tool.requires_human_approval else "pending"

    log = AgentExecutionLog(
        id=uuid.uuid4(),
        session_id=session_id,
        app_id=state_node.app_id,
        tool_id=tool_id,
        action_payload=body.action_payload,
        execution_status=initial_status,
    )
    db.add(log)
    await db.flush()
    await db.refresh(log)

    if not tool.requires_human_approval:
        # Safe to execute immediately
        background_tasks.add_task(
            _execute_tool_action,
            execution_id=log.id,
            tool_id=tool_id,
            app_id=state_node.app_id,
            action_payload=body.action_payload,
        )
        logger.info("Tool %s queued for execution (session %s)", tool_id, session_id)
    else:
        logger.info(
            "Tool %s requires human approval — execution pending (session %s)",
            tool_id,
            session_id,
        )

    return log


@router.post(
    "/executions/{execution_id}/approve",
    response_model=ExecutionResponse,
)
async def approve_execution(
    execution_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Approve an awaiting_human execution and proceed with tool execution.
    """
    log = await _get_execution_or_404(execution_id, db)

    if log.execution_status != "awaiting_human":
        raise HTTPException(
            status_code=400,
            detail=f"Execution {execution_id} is not awaiting approval "
            f"(current status: {log.execution_status})",
        )

    # Transition to pending and trigger execution
    log.execution_status = "pending"
    await db.flush()

    background_tasks.add_task(
        _execute_tool_action,
        execution_id=log.id,
        tool_id=log.tool_id,
        app_id=log.app_id,
        action_payload=log.action_payload,
    )

    logger.info("Execution %s approved and queued", execution_id)
    return log
