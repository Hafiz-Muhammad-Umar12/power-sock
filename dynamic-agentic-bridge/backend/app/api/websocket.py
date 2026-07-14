"""
WebSocket endpoint for real-time execution log streaming.
Stub for Phase 1; full implementation in Phase 4.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/executions")
async def execution_stream(websocket: WebSocket):
    """
    Stream agent_execution_logs updates in real time.
    Implementation coming in Phase 4.
    """
    await websocket.accept()
    try:
        while True:
            # Keep connection alive; real streaming added in Phase 4
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
