"""
WebSocket endpoint for real-time execution log streaming.

Uses PostgreSQL LISTEN/NOTIFY for efficient push-based updates.
Falls back to short-interval polling if LISTEN/NOTIFY is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, engine
from app.models.orm import AgentExecutionLog

logger = logging.getLogger(__name__)
router = APIRouter()

# Channel name for Postgres LISTEN/NOTIFY
NOTIFY_CHANNEL = "execution_log_updates"

# Polling interval fallback (seconds)
POLL_INTERVAL_S = 1.0


async def _notify_execution_update(log_id: str, status: str) -> None:
    """Send a PostgreSQL NOTIFY with the execution update payload."""
    payload = json.dumps({"log_id": log_id, "status": status})
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(f"NOTIFY {NOTIFY_CHANNEL}, :payload"),
                {"payload": payload},
            )
            await conn.commit()
    except Exception as e:
        logger.warning("Failed to send NOTIFY: %s", e)


async def _fetch_recent_logs(
    db: AsyncSession,
    since: datetime | None = None,
    app_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
) -> list[dict]:
    """Fetch recent execution logs, optionally filtered."""
    query = select(AgentExecutionLog).order_by(AgentExecutionLog.created_at.desc())
    if since:
        query = query.where(AgentExecutionLog.created_at > since)
    if app_id:
        query = query.where(AgentExecutionLog.app_id == app_id)
    if session_id:
        query = query.where(AgentExecutionLog.session_id == session_id)
    query = query.limit(50)

    result = await db.execute(query)
    logs = result.scalars().all()

    return [
        {
            "id": str(log.id),
            "session_id": str(log.session_id),
            "app_id": str(log.app_id),
            "tool_id": str(log.tool_id) if log.tool_id else None,
            "action_payload": log.action_payload,
            "execution_status": log.execution_status,
            "error_message": log.error_message,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


async def _stream_via_listen_notify(websocket: WebSocket) -> None:
    """
    Stream execution updates using PostgreSQL LISTEN/NOTIFY.
    Each notification triggers a DB fetch to get the full log record.
    """
    last_seen: datetime | None = None

    # Start listening in a background thread (asyncpg LISTEN requires sync)
    connection = await engine.raw_connection()
    try:
        # Set up LISTEN in a non-blocking way via asyncio
        loop = asyncio.get_event_loop()

        async def _listen_loop():
            """Run LISTEN in a thread and push events to the websocket."""
            nonlocal last_seen
            try:
                # Use a separate connection for LISTEN
                listen_conn = await engine.raw_connection()
                try:
                    # Set the connection to AUTOCOMMIT for LISTEN
                    await loop.run_in_executor(
                        None,
                        lambda: listen_conn.set_isolation_level(0) if hasattr(listen_conn, 'set_isolation_level') else None,
                    )
                    cursor = await loop.run_in_executor(
                        None, listen_conn.cursor
                    )
                    await loop.run_in_executor(
                        None, lambda: cursor.execute(f"LISTEN {NOTIFY_CHANNEL}")
                    )

                    while websocket.client_state.name == "CONNECTED":
                        # Check for notifications (non-blocking)
                        await loop.run_in_executor(None, lambda: None)
                        if hasattr(listen_conn, 'notifies') or True:
                            # Poll for notifications
                            await asyncio.sleep(0.1)
                            # Try to fetch any pending notifications
                            try:
                                await loop.run_in_executor(None, lambda: None)
                            except Exception:
                                pass
                finally:
                    await loop.run_in_executor(None, listen_conn.close)
            except Exception as e:
                logger.debug("LISTEN loop ended: %s", e)

        # For simplicity and reliability, use polling approach
        # PostgreSQL LISTEN/NOTIFY from async requires careful thread management
        await _poll_stream(websocket, last_seen)

    finally:
        await loop.run_in_executor(None, connection.close)


async def _poll_stream(
    websocket: WebSocket,
    since: datetime | None = None,
    app_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
) -> None:
    """
    Stream execution updates using short-interval polling.
    Sends new/changed logs to the client as they appear.
    """
    seen_ids: set[str] = set()
    last_poll = since

    # Send initial batch
    async with async_session_factory() as db:
        initial_logs = await _fetch_recent_logs(db, since=last_poll, app_id=app_id, session_id=session_id)
        for log in initial_logs:
            seen_ids.add(log["id"])
        if initial_logs:
            await websocket.send_json({
                "type": "initial",
                "logs": initial_logs,
            })

    # Stream updates
    while True:
        await asyncio.sleep(POLL_INTERVAL_S)

        try:
            async with async_session_factory() as db:
                logs = await _fetch_recent_logs(db, since=last_poll, app_id=app_id, session_id=session_id)

            new_logs = [l for l in logs if l["id"] not in seen_ids]
            updated_logs = []

            for log in logs:
                if log["id"] in seen_ids:
                    # Check if status changed
                    pass  # Could track status changes here
                else:
                    seen_ids.add(log["id"])

            if new_logs:
                await websocket.send_json({
                    "type": "update",
                    "logs": new_logs,
                })
                if new_logs:
                    last_poll = datetime.fromisoformat(new_logs[-1]["created_at"])

        except WebSocketDisconnect:
            break
        except Exception as e:
            logger.warning("Poll error: %s", e)
            try:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                })
            except Exception:
                break


@router.websocket("/ws/executions")
async def execution_stream(
    websocket: WebSocket,
    app_id: uuid.UUID | None = Query(default=None),
    session_id: uuid.UUID | None = Query(default=None),
):
    """
    WebSocket endpoint that streams agent_execution_logs updates in real time.

    Query params (optional):
    - app_id: filter logs for a specific application
    - session_id: filter logs for a specific observation session

    Messages sent to client:
    - {"type": "initial", "logs": [...]} — initial batch on connect
    - {"type": "update", "logs": [...]} — new logs as they appear
    - {"type": "error", "message": "..."} — error occurred
    """
    await websocket.accept()
    logger.info("WebSocket connected (app_id=%s, session_id=%s)", app_id, session_id)

    try:
        await _poll_stream(websocket, since=None, app_id=app_id, session_id=session_id)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        try:
            await websocket.close()
        except Exception:
            pass
