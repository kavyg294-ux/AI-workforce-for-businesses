"""
Master Orchestrator Agent — Accepts business requests, plans tasks,
and dispatches them to specialized agents.
"""

import json
import uuid
import asyncio
import google.generativeai as genai
from datetime import datetime

from backend.database import get_db
from backend.tools.db_tool import (
    log_agent_action, create_task, update_task_status,
    create_approval_request, get_pending_approvals
)
from backend.agents import crm_agent, email_agent, lead_agent, analytics_agent, followup_agent


AGENT_REGISTRY = {
    "crm": crm_agent,
    "email": email_agent,
    "lead": lead_agent,
    "analytics": analytics_agent,
    "followup": followup_agent,
}

AGENT_DESCRIPTIONS = {
    "crm": "Manages CRM contacts, deals, and pipeline stages",
    "email": "Drafts and sends personalized business emails",
    "lead": "Scores, segments, and qualifies leads",
    "analytics": "Generates business reports and KPI dashboards",
    "followup": "Plans and sends intelligent follow-up sequences",
}


async def create_request(title: str, description: str) -> dict:
    """Create a new business request and return its ID."""
    request_id = str(uuid.uuid4())[:12]
    async with await get_db() as db:
        await db.execute("""
            INSERT INTO business_requests (id, title, description, status)
            VALUES (?, ?, ?, 'planning')
        """, (request_id, title, description))
        await db.commit()
    return {"id": request_id, "title": title, "status": "planning"}


async def plan_and_execute(request_id: str, title: str, description: str, api_key: str):
    """
    Main orchestration flow:
    1. Use AI to decompose the business request into tasks
    2. Queue tasks to appropriate agents
    3. Execute tasks with error handling
    4. Create human approval gates for sensitive tasks
    """
    await log_agent_action("orchestrator", "Orchestration started", title, request_id)

    # Update request status
    async with await get_db() as db:
        await db.execute("""
            UPDATE business_requests SET status='planning' WHERE id=?
        """, (request_id,))
        await db.commit()

    try:
        # Step 1: AI-powered task decomposition
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        agents_info = json.dumps(AGENT_DESCRIPTIONS, indent=2)

        prompt = f"""You are the Master Orchestrator for an AI Business Workforce system.
Your job is to break down a business request into specific tasks for specialized AI agents.

Business Request:
Title: {title}
Description: {description}

Available Agents:
{agents_info}

Decompose this request into 3-6 actionable tasks. Each task should:
- Be assigned to the most appropriate agent
- Have a clear, specific goal
- Be ordered by logical dependency (earlier tasks may inform later ones)
- Flag sensitive tasks (e.g. sending emails to >100 people, deleting data) as requiring human approval

Respond in JSON format:
{{
  "plan_summary": "brief orchestration plan",
  "tasks": [
    {{
      "agent": "crm|email|lead|analytics|followup",
      "title": "Specific task title",
      "description": "Detailed task description with specific goals",
      "priority": 1-10,
      "requires_approval": true/false,
      "approval_reason": "why approval needed (if applicable)",
      "depends_on": []
    }}
  ],
  "expected_outcome": "what will be achieved when all tasks complete",
  "estimated_time": "time estimate"
}}"""

        response = model.generate_content(prompt)
        response_text = response.text

        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        plan = json.loads(response_text.strip())

        await log_agent_action(
            "orchestrator",
            f"Plan created: {len(plan.get('tasks', []))} tasks",
            plan.get("plan_summary", ""),
            request_id,
            "info"
        )

        # Update request with plan
        async with await get_db() as db:
            await db.execute("""
                UPDATE business_requests SET status='executing', result=? WHERE id=?
            """, (json.dumps({"plan": plan}), request_id))
            await db.commit()

        # Step 2: Create all tasks in DB
        task_ids = []
        for task_def in plan.get("tasks", []):
            agent_type = task_def.get("agent", "crm")
            task_id = await create_task(
                request_id=request_id,
                agent_type=agent_type,
                title=task_def.get("title", "Untitled Task"),
                description=task_def.get("description", ""),
                priority=task_def.get("priority", 5),
                requires_approval=task_def.get("requires_approval", False),
                metadata={"depends_on": task_def.get("depends_on", [])}
            )
            task_ids.append({
                "id": task_id,
                "agent": agent_type,
                "requires_approval": task_def.get("requires_approval", False),
                "approval_reason": task_def.get("approval_reason", "")
            })

        # Step 3: Execute tasks
        completed_results = []
        for task_info in task_ids:
            task_id = task_info["id"]

            # Fetch task from DB
            async with await get_db() as db:
                db.row_factory = lambda cursor, row: dict(zip([d[0] for d in cursor.description], row))
                async with db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)) as cursor:
                    task = await cursor.fetchone()

            if not task:
                continue

            agent_type = task_info["agent"]

            # Check if approval required
            if task_info.get("requires_approval"):
                approval_id = await create_approval_request(
                    task_id=task_id,
                    request_id=request_id,
                    title=f"Approval needed: {task['title']}",
                    description=f"Agent '{agent_type}' wants to execute: {task['description']}",
                    context={"reason": task_info.get("approval_reason", "")}
                )
                await update_task_status(task_id, "waiting_approval")
                await log_agent_action(
                    "orchestrator",
                    f"Waiting for approval: {task['title']}",
                    f"Approval ID: {approval_id}",
                    request_id,
                    "warning"
                )
                # Skip execution — will be triggered after approval
                continue

            # Execute task
            try:
                agent_module = AGENT_REGISTRY.get(agent_type)
                if agent_module:
                    result = await agent_module.run(task, api_key)
                    completed_results.append({
                        "task_id": task_id,
                        "agent": agent_type,
                        "result": result
                    })
                    await log_agent_action(
                        "orchestrator",
                        f"Task completed by {agent_type}: {task['title']}",
                        "",
                        request_id,
                        "success"
                    )
                    # Small delay between agents to avoid rate limiting
                    await asyncio.sleep(1)

            except Exception as e:
                await log_agent_action(
                    "orchestrator",
                    f"Task FAILED ({agent_type}): {task['title']} — {str(e)}",
                    "",
                    request_id,
                    "error"
                )
                # Continue with other tasks even if one fails

        # Step 4: Finalize
        pending_approvals = await get_pending_approvals()
        final_status = "waiting_approval" if pending_approvals else "completed"

        async with await get_db() as db:
            await db.execute("""
                UPDATE business_requests SET status=?, updated_at=? WHERE id=?
            """, (final_status, datetime.utcnow().isoformat(), request_id))
            await db.commit()

        await log_agent_action(
            "orchestrator",
            f"Orchestration {final_status}: {len(completed_results)} tasks executed",
            plan.get("expected_outcome", ""),
            request_id,
            "success" if final_status == "completed" else "warning"
        )

        return {
            "request_id": request_id,
            "status": final_status,
            "tasks_completed": len(completed_results),
            "pending_approvals": len(pending_approvals),
            "plan": plan
        }

    except Exception as e:
        async with await get_db() as db:
            await db.execute("""
                UPDATE business_requests SET status='failed' WHERE id=?
            """, (request_id,))
            await db.commit()
        await log_agent_action("orchestrator", f"Orchestration FAILED: {str(e)}", "", request_id, "error")
        raise


async def execute_approved_task(task_id: str, approval_id: str, api_key: str):
    """Execute a task that has been approved by a human."""
    async with await get_db() as db:
        db.row_factory = lambda cursor, row: dict(zip([d[0] for d in cursor.description], row))
        async with db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)) as cursor:
            task = await cursor.fetchone()

        # Mark approval as decided
        await db.execute("""
            UPDATE approval_queue SET status='approved', decision='approved', decided_at=?
            WHERE id=?
        """, (datetime.utcnow().isoformat(), approval_id))
        await db.execute("""
            UPDATE tasks SET approved=1 WHERE id=?
        """, (task_id,))
        await db.commit()

    if task:
        agent_module = AGENT_REGISTRY.get(task["agent_type"])
        if agent_module:
            return await agent_module.run(task, api_key)
    return {"error": "Task not found"}
