"""
AI Workforce for Businesses — FastAPI Backend
Autonomous multi-agent orchestration for enterprise task execution.
"""

import asyncio
import json
import os
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from backend.database import init_db, get_db
from backend.models import BusinessRequest, TaskApproval, ContactCreate, DealCreate
from backend.orchestrator import create_request, plan_and_execute, execute_approved_task
from backend.tools.crm_tool import (
    get_all_contacts, create_contact, get_pipeline_summary
)
from backend.tools.email_tool import get_email_log, get_email_stats
from backend.tools.db_tool import (
    get_pending_approvals, get_tasks_for_request
)

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    await init_db()
    print("[AI Workforce] System initialized. All agents ready.")
    yield
    print("[AI Workforce] Shutting down.")


app = FastAPI(
    title="AI Workforce for Businesses",
    description="Autonomous multi-agent orchestration for cross-platform enterprise task execution",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ─────────────────────────────────────────────────────────────────────────────
# ROOT & FRONTEND
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def serve_dashboard():
    """Serve the AI Workforce dashboard."""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "AI Workforce API running. Visit /docs for API reference."}


# ─────────────────────────────────────────────────────────────────────────────
# BUSINESS REQUESTS — Core orchestration endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/requests", summary="Submit a business request to the AI Workforce")
async def submit_request(request: BusinessRequest, background_tasks: BackgroundTasks):
    """
    Submit a business task request. The Orchestrator Agent will:
    1. Decompose it into sub-tasks
    2. Assign each task to the appropriate AI agent
    3. Execute tasks with error handling and retry
    4. Request human approval for sensitive operations
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured in .env file")

    # Create the request record
    req = await create_request(request.title, request.description)
    request_id = req["id"]

    # Run orchestration in background
    background_tasks.add_task(
        plan_and_execute,
        request_id=request_id,
        title=request.title,
        description=request.description,
        api_key=api_key
    )

    return {
        "request_id": request_id,
        "status": "accepted",
        "message": "Business request accepted. AI agents are now working on it.",
        "tracking_url": f"/api/requests/{request_id}"
    }


@app.get("/api/requests", summary="List all business requests")
async def list_requests():
    """Get all business requests with their status."""
    async with await get_db() as db:
        db.row_factory = lambda cursor, row: dict(zip([d[0] for d in cursor.description], row))
        async with db.execute("""
            SELECT * FROM business_requests ORDER BY created_at DESC
        """) as cursor:
            requests = await cursor.fetchall()
    return {"requests": requests, "total": len(requests)}


@app.get("/api/requests/{request_id}", summary="Get request details and task execution status")
async def get_request(request_id: str):
    """Get a specific business request with all its tasks."""
    async with await get_db() as db:
        db.row_factory = lambda cursor, row: dict(zip([d[0] for d in cursor.description], row))
        async with db.execute("SELECT * FROM business_requests WHERE id=?", (request_id,)) as cursor:
            req = await cursor.fetchone()

    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    tasks = await get_tasks_for_request(request_id)
    return {**req, "tasks": tasks}


# ─────────────────────────────────────────────────────────────────────────────
# HUMAN APPROVAL GATE
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/approvals", summary="List pending human approval requests")
async def list_approvals():
    """Get all tasks waiting for human approval."""
    approvals = await get_pending_approvals()
    return {"approvals": approvals, "total": len(approvals)}


@app.post("/api/approvals/{approval_id}", summary="Approve or reject a pending task")
async def decide_approval(approval_id: str, decision: TaskApproval, background_tasks: BackgroundTasks):
    """Approve or reject a task that requires human authorization."""
    api_key = os.getenv("GEMINI_API_KEY")

    async with await get_db() as db:
        db.row_factory = lambda cursor, row: dict(zip([d[0] for d in cursor.description], row))
        async with db.execute("SELECT * FROM approval_queue WHERE id=?", (approval_id,)) as cursor:
            approval = await cursor.fetchone()

    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Approval already decided: {approval['status']}")

    if decision.decision == "approve":
        background_tasks.add_task(
            execute_approved_task,
            task_id=approval["task_id"],
            approval_id=approval_id,
            api_key=api_key
        )
        return {"status": "approved", "message": "Task approved and queued for execution"}
    else:
        # Reject the task
        async with await get_db() as db:
            await db.execute("""
                UPDATE approval_queue SET status='rejected', decision='rejected',
                decided_at=? WHERE id=?
            """, (datetime.utcnow().isoformat(), approval_id))
            await db.execute("""
                UPDATE tasks SET status='failed', error=? WHERE id=?
            """, (f"Rejected by human: {decision.reason}", approval["task_id"]))
            await db.commit()
        return {"status": "rejected", "message": "Task rejected and cancelled"}


# ─────────────────────────────────────────────────────────────────────────────
# CRM ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/crm/contacts", summary="Get all CRM contacts")
async def get_contacts():
    """Fetch all contacts from the CRM database."""
    contacts = await get_all_contacts()
    return {"contacts": contacts, "total": len(contacts)}


@app.post("/api/crm/contacts", summary="Manually add a CRM contact")
async def add_contact(contact: ContactCreate):
    """Manually add a contact to the CRM."""
    result = await create_contact(
        name=contact.name,
        email=contact.email,
        company=contact.company or "",
        phone=contact.phone or ""
    )
    return result


@app.get("/api/crm/pipeline", summary="Get CRM pipeline summary")
async def get_pipeline():
    """Get the current CRM deal pipeline summary."""
    return await get_pipeline_summary()


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/emails", summary="Get email activity log")
async def get_emails(limit: int = 50):
    """Get the sent email activity log."""
    emails = await get_email_log(limit)
    return {"emails": emails, "total": len(emails)}


@app.get("/api/emails/stats", summary="Get email campaign statistics")
async def get_email_statistics():
    """Get email campaign performance statistics."""
    return await get_email_stats()


# ─────────────────────────────────────────────────────────────────────────────
# ACTIVITY FEED & AGENT LOGS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/activity", summary="Get agent activity log")
async def get_activity(limit: int = 100):
    """Get the real-time agent activity feed."""
    async with await get_db() as db:
        db.row_factory = lambda cursor, row: dict(zip([d[0] for d in cursor.description], row))
        async with db.execute("""
            SELECT * FROM agent_logs ORDER BY created_at DESC LIMIT ?
        """, (limit,)) as cursor:
            logs = await cursor.fetchall()
    return {"activity": logs, "total": len(logs)}


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD STATS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/dashboard", summary="Get dashboard overview stats")
async def get_dashboard():
    """Get aggregated stats for the main dashboard."""
    async with await get_db() as db:
        db.row_factory = lambda cursor, row: dict(zip([d[0] for d in cursor.description], row))

        async with db.execute("SELECT COUNT(*) as c FROM business_requests") as cur:
            total_requests = (await cur.fetchone())["c"]

        async with db.execute("SELECT COUNT(*) as c FROM business_requests WHERE status='completed'") as cur:
            completed_requests = (await cur.fetchone())["c"]

        async with db.execute("SELECT COUNT(*) as c FROM tasks") as cur:
            total_tasks = (await cur.fetchone())["c"]

        async with db.execute("SELECT COUNT(*) as c FROM tasks WHERE status='completed'") as cur:
            completed_tasks = (await cur.fetchone())["c"]

        async with db.execute("SELECT COUNT(*) as c FROM tasks WHERE status='failed'") as cur:
            failed_tasks = (await cur.fetchone())["c"]

        async with db.execute("SELECT COUNT(*) as c FROM crm_contacts") as cur:
            total_contacts = (await cur.fetchone())["c"]

        async with db.execute("SELECT COUNT(*) as c FROM email_log") as cur:
            emails_sent = (await cur.fetchone())["c"]

        async with db.execute("SELECT COUNT(*) as c FROM approval_queue WHERE status='pending'") as cur:
            pending_approvals = (await cur.fetchone())["c"]

        async with db.execute("""
            SELECT agent_type, COUNT(*) as count FROM tasks
            WHERE status='completed' GROUP BY agent_type
        """) as cur:
            agent_stats = await cur.fetchall()

    return {
        "requests": {"total": total_requests, "completed": completed_requests},
        "tasks": {
            "total": total_tasks,
            "completed": completed_tasks,
            "failed": failed_tasks,
            "success_rate": round((completed_tasks / max(total_tasks, 1)) * 100, 1)
        },
        "crm": {"total_contacts": total_contacts},
        "emails": {"sent": emails_sent},
        "pending_approvals": pending_approvals,
        "agent_performance": agent_stats,
        "timestamp": datetime.utcnow().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
