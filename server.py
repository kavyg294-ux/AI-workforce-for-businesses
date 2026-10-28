"""
AI Workforce for Businesses — Pure Python Server
Autonomous multi-agent orchestration using Python stdlib + Gemini API.
No external packages required.

Usage:
  1. Set GEMINI_API_KEY in .env or as environment variable
  2. python server.py
  3. Open http://localhost:8000
"""

import json
import os
import re
import sqlite3
import threading
import time
import uuid
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ─── Configuration ─────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "workforce.db"
FRONTEND_PATH = BASE_DIR / "frontend" / "index.html"

# Load .env file
def load_env():
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                os.environ.setdefault(key.strip(), val.strip())

load_env()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


# ─── Database ─────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS business_requests (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
        status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP, result TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY, request_id TEXT NOT NULL, agent_type TEXT NOT NULL,
        title TEXT NOT NULL, description TEXT NOT NULL, status TEXT DEFAULT 'queued',
        priority INTEGER DEFAULT 5, attempts INTEGER DEFAULT 0,
        requires_approval INTEGER DEFAULT 0, approved INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, started_at TEXT,
        completed_at TEXT, result TEXT, error TEXT, metadata TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS crm_contacts (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
        company TEXT DEFAULT '', phone TEXT DEFAULT '', lead_score INTEGER DEFAULT 0,
        stage TEXT DEFAULT 'lead', notes TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS crm_deals (
        id TEXT PRIMARY KEY, contact_id TEXT NOT NULL, title TEXT NOT NULL,
        value REAL DEFAULT 0, stage TEXT DEFAULT 'prospecting',
        probability INTEGER DEFAULT 10, close_date TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS email_log (
        id TEXT PRIMARY KEY, to_email TEXT NOT NULL, to_name TEXT DEFAULT '',
        subject TEXT NOT NULL, body TEXT NOT NULL, status TEXT DEFAULT 'sent',
        email_type TEXT DEFAULT 'general', sent_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS agent_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, agent_type TEXT NOT NULL,
        task_id TEXT DEFAULT '', action TEXT NOT NULL, details TEXT DEFAULT '',
        status TEXT DEFAULT 'info', created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS approval_queue (
        id TEXT PRIMARY KEY, task_id TEXT NOT NULL, request_id TEXT NOT NULL,
        title TEXT NOT NULL, description TEXT NOT NULL, context TEXT DEFAULT '{}',
        status TEXT DEFAULT 'pending', decision TEXT DEFAULT '',
        decided_at TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # Seed demo contacts
    demo = [
        ("c001","Alice Johnson","alice@techcorp.com","TechCorp Inc","+1-555-0101",85,"qualified"),
        ("c002","Bob Martinez","bob@startupxyz.com","StartupXYZ","+1-555-0102",42,"lead"),
        ("c003","Carol Lee","carol@enterprise.com","Enterprise Solutions","+1-555-0103",91,"proposal"),
        ("c004","David Kim","david@innovate.io","Innovate.io","+1-555-0104",67,"qualified"),
        ("c005","Eva Brown","eva@globalfirm.com","Global Firm LLC","+1-555-0105",23,"lead"),
    ]
    for d in demo:
        c.execute("INSERT OR IGNORE INTO crm_contacts (id,name,email,company,phone,lead_score,stage) VALUES (?,?,?,?,?,?,?)", d)

    conn.commit()
    conn.close()
    print(f"[DB] Database initialized at {DB_PATH}")


# ─── Gemini API Client ─────────────────────────────────────────────────────────

def call_gemini(prompt: str) -> str:
    """Call Gemini API using urllib (no external packages needed)."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set. Please add it to your .env file.")

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096}
    }
    data = json.dumps(payload).encode('utf-8')
    url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            return result['candidates'][0]['content']['parts'][0]['text']
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        raise RuntimeError(f"Gemini API error {e.code}: {body}")


def parse_json_from_ai(text: str) -> dict:
    """Extract JSON from AI response text."""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    return json.loads(text.strip())


# ─── Database Helpers ─────────────────────────────────────────────────────────

def log_agent(agent_type, action, details="", task_id="", status="info"):
    conn = get_db()
    conn.execute("INSERT INTO agent_logs (agent_type, task_id, action, details, status) VALUES (?,?,?,?,?)",
                 (agent_type, task_id, action, details, status))
    conn.commit(); conn.close()

def create_task_db(request_id, agent_type, title, description, priority=5, requires_approval=False, metadata=None):
    task_id = str(uuid.uuid4())[:12]
    conn = get_db()
    conn.execute("INSERT INTO tasks (id,request_id,agent_type,title,description,priority,requires_approval,metadata) VALUES (?,?,?,?,?,?,?,?)",
                 (task_id, request_id, agent_type, title, description, priority,
                  1 if requires_approval else 0, json.dumps(metadata or {})))
    conn.commit(); conn.close()
    return task_id

def update_task(task_id, status, result=None, error=None):
    conn = get_db()
    now = datetime.utcnow().isoformat()
    if status == "running":
        conn.execute("UPDATE tasks SET status=?, started_at=?, attempts=attempts+1 WHERE id=?", (status, now, task_id))
    elif status in ("completed","failed"):
        conn.execute("UPDATE tasks SET status=?, completed_at=?, result=?, error=? WHERE id=?", (status, now, result, error, task_id))
    else:
        conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    conn.commit(); conn.close()

def get_task_db(task_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def db_row_to_dict(row):
    return dict(row) if row else None

def db_rows_to_list(rows):
    return [dict(r) for r in rows]


# ─── Simulated Business Tools ──────────────────────────────────────────────────

def tool_create_contact(name, email, company="", phone="", lead_score=0):
    contact_id = str(uuid.uuid4())[:8]
    conn = get_db()
    existing = conn.execute("SELECT * FROM crm_contacts WHERE email=?", (email,)).fetchone()
    if existing:
        conn.execute("UPDATE crm_contacts SET name=?,company=?,phone=?,updated_at=? WHERE email=?",
                     (name, company, phone, datetime.utcnow().isoformat(), email))
        conn.commit(); conn.close()
        return {"id": dict(existing)["id"], "action": "updated", "name": name}
    conn.execute("INSERT INTO crm_contacts (id,name,email,company,phone,lead_score,stage) VALUES (?,?,?,?,?,?,'lead')",
                 (contact_id, name, email, company, phone, lead_score))
    conn.commit(); conn.close()
    return {"id": contact_id, "action": "created", "name": name, "email": email}

def tool_update_stage(contact_id, stage):
    conn = get_db()
    conn.execute("UPDATE crm_contacts SET stage=?,updated_at=? WHERE id=?",
                 (stage, datetime.utcnow().isoformat(), contact_id))
    conn.commit(); conn.close()
    return {"contact_id": contact_id, "stage": stage, "updated": True}

def tool_update_score(contact_id, score):
    score = max(0, min(100, score))
    conn = get_db()
    conn.execute("UPDATE crm_contacts SET lead_score=?,updated_at=? WHERE id=?",
                 (score, datetime.utcnow().isoformat(), contact_id))
    conn.commit(); conn.close()
    return {"contact_id": contact_id, "lead_score": score}

def tool_create_deal(contact_id, title, value, stage="prospecting", probability=10, close_date=""):
    deal_id = str(uuid.uuid4())[:8]
    conn = get_db()
    conn.execute("INSERT INTO crm_deals (id,contact_id,title,value,stage,probability,close_date) VALUES (?,?,?,?,?,?,?)",
                 (deal_id, contact_id, title, value, stage, probability, close_date))
    conn.commit(); conn.close()
    return {"id": deal_id, "title": title, "value": value}

def tool_send_email(to_email, to_name, subject, body, email_type="general"):
    email_id = str(uuid.uuid4())[:8]
    conn = get_db()
    conn.execute("INSERT INTO email_log (id,to_email,to_name,subject,body,email_type) VALUES (?,?,?,?,?,?)",
                 (email_id, to_email, to_name, subject, body, email_type))
    conn.commit(); conn.close()
    return {"id": email_id, "to": to_email, "subject": subject, "status": "sent"}

def tool_get_all_contacts():
    conn = get_db()
    rows = conn.execute("SELECT * FROM crm_contacts ORDER BY lead_score DESC").fetchall()
    conn.close()
    return db_rows_to_list(rows)


# ─── AI Agents ─────────────────────────────────────────────────────────────────

AGENT_DESCRIPTIONS = {
    "crm": "Manages CRM contacts, deals, and pipeline stages",
    "email": "Drafts and sends personalized business emails",
    "lead": "Scores, segments, and qualifies leads",
    "analytics": "Generates business reports and KPI dashboards",
    "followup": "Plans and sends intelligent follow-up sequences",
}


def run_crm_agent(task):
    task_id = task["id"]
    log_agent("crm", "Task started", task["title"], task_id)
    update_task(task_id, "running")

    contacts = tool_get_all_contacts()
    contacts_summary = json.dumps(contacts[:8], indent=2)

    prompt = f"""You are a CRM Agent for a business AI workforce.

Task: {task['title']}
Description: {task['description']}

Current CRM Contacts:
{contacts_summary}

Generate a JSON plan with CRM actions to execute. Be specific and use real contact IDs from the data above.

Respond ONLY with valid JSON (no explanation):
{{
  "actions": [
    {{"type": "create_contact|update_stage|create_deal|update_score", "data": {{}}, "reason": "..."}}
  ],
  "summary": "what was accomplished",
  "insights": "key CRM insights"
}}

For create_contact: data = {{name, email, company, phone, lead_score}}
For update_stage: data = {{contact_id, stage}} (stages: lead/qualified/proposal/negotiation/closed_won)
For create_deal: data = {{contact_id, title, value, stage, probability, close_date}}
For update_score: data = {{contact_id, score (0-100)}}"""

    ai_response = call_gemini(prompt)
    plan = parse_json_from_ai(ai_response)
    results = []

    for action in plan.get("actions", []):
        atype = action.get("type", "")
        d = action.get("data", {})
        if atype == "create_contact":
            r = tool_create_contact(d.get("name",""), d.get("email",""), d.get("company",""), d.get("phone",""), d.get("lead_score",50))
            results.append(r)
            log_agent("crm", f"Contact {r.get('action','processed')}: {d.get('name')}", "", task_id)
        elif atype == "update_stage":
            r = tool_update_stage(d.get("contact_id",""), d.get("stage","lead"))
            results.append(r)
            log_agent("crm", f"Stage → {d.get('stage')} for contact {d.get('contact_id')}", "", task_id)
        elif atype == "create_deal":
            r = tool_create_deal(d.get("contact_id",""), d.get("title","Deal"), float(d.get("value",0)), d.get("stage","prospecting"), int(d.get("probability",10)), d.get("close_date",""))
            results.append(r)
            log_agent("crm", f"Deal created: {d.get('title')} (${d.get('value',0):,.0f})", "", task_id)
        elif atype == "update_score":
            r = tool_update_score(d.get("contact_id",""), int(d.get("score",50)))
            results.append(r)
            log_agent("crm", f"Score → {d.get('score')} for {d.get('contact_id')}", "", task_id)

    final = {"agent": "crm", "actions_taken": len(results), "results": results,
             "summary": plan.get("summary","CRM tasks completed"), "insights": plan.get("insights","")}
    update_task(task_id, "completed", json.dumps(final))
    log_agent("crm", f"Task completed — {len(results)} CRM actions", "", task_id, "success")
    return final


def run_email_agent(task):
    task_id = task["id"]
    log_agent("email", "Task started", task["title"], task_id)
    update_task(task_id, "running")

    contacts = tool_get_all_contacts()

    prompt = f"""You are an Email Agent for a business AI workforce.

Task: {task['title']}
Description: {task['description']}

Available CRM Contacts:
{json.dumps(contacts[:8], indent=2)}

Generate personalized emails for appropriate contacts. Respond ONLY with valid JSON:
{{
  "emails": [
    {{
      "to_email": "...", "to_name": "...", "subject": "...",
      "body": "full professional email body (3-4 paragraphs, personalized)",
      "email_type": "follow_up|introduction|proposal|re_engagement|check_in",
      "personalization": "why tailored to this contact"
    }}
  ],
  "campaign_summary": "...",
  "expected_outcome": "..."
}}"""

    ai_response = call_gemini(prompt)
    plan = parse_json_from_ai(ai_response)
    sent = []

    for e in plan.get("emails", []):
        r = tool_send_email(e.get("to_email",""), e.get("to_name",""), e.get("subject",""), e.get("body",""), e.get("email_type","general"))
        sent.append({"email_id": r["id"], "to": e.get("to_name"), "subject": e.get("subject"), "type": e.get("email_type")})
        log_agent("email", f"Email sent → {e.get('to_name')} ({e.get('email_type')})", e.get("subject",""), task_id)

    final = {"agent": "email", "emails_sent": len(sent), "emails": sent,
             "campaign_summary": plan.get("campaign_summary",""), "expected_outcome": plan.get("expected_outcome","")}
    update_task(task_id, "completed", json.dumps(final))
    log_agent("email", f"Task completed — {len(sent)} emails sent", "", task_id, "success")
    return final


def run_lead_agent(task):
    task_id = task["id"]
    log_agent("lead", "Task started", task["title"], task_id)
    update_task(task_id, "running")

    contacts = tool_get_all_contacts()

    prompt = f"""You are a Lead Management Agent. Analyze and score these CRM contacts.

Task: {task['title']}
Description: {task['description']}

Contacts to analyze:
{json.dumps(contacts, indent=2)}

Score each contact (0-100) and decide if their stage should advance.
Respond ONLY with valid JSON:
{{
  "lead_analysis": [
    {{
      "contact_id": "...", "name": "...", "current_score": 0, "new_score": 0,
      "segment": "hot|warm|cold", "advance_stage": true/false,
      "new_stage": "lead|qualified|proposal|negotiation",
      "recommended_action": "...", "rationale": "..."
    }}
  ],
  "summary": "...", "hot_leads": ["names"],
  "total_pipeline_value_estimate": 0
}}"""

    ai_response = call_gemini(prompt)
    plan = parse_json_from_ai(ai_response)
    updates = []

    for lead in plan.get("lead_analysis", []):
        cid = lead.get("contact_id","")
        if cid:
            tool_update_score(cid, lead.get("new_score", 0))
            entry = {"contact_id": cid, "name": lead.get("name",""), "segment": lead.get("segment",""),
                     "score": lead.get("new_score",0), "action": lead.get("recommended_action","")}
            if lead.get("advance_stage") and lead.get("new_stage"):
                tool_update_stage(cid, lead["new_stage"])
                entry["stage_advanced_to"] = lead["new_stage"]
            updates.append(entry)
            log_agent("lead", f"Lead scored: {lead.get('name')} → {str(lead.get('segment','')).upper()} ({lead.get('new_score')})", "", task_id)

    final = {"agent": "lead", "leads_analyzed": len(updates), "updates": updates,
             "hot_leads": plan.get("hot_leads",[]), "summary": plan.get("summary",""),
             "pipeline_value_estimate": plan.get("total_pipeline_value_estimate",0)}
    update_task(task_id, "completed", json.dumps(final))
    log_agent("lead", f"Task completed — {len(updates)} leads analyzed", "", task_id, "success")
    return final


def run_analytics_agent(task):
    task_id = task["id"]
    log_agent("analytics", "Task started", task["title"], task_id)
    update_task(task_id, "running")

    conn = get_db()
    contacts = db_rows_to_list(conn.execute("SELECT * FROM crm_contacts ORDER BY lead_score DESC").fetchall())
    pipeline = db_rows_to_list(conn.execute("SELECT stage, COUNT(*) as count, SUM(value) as total FROM crm_deals GROUP BY stage").fetchall())
    email_stats = db_rows_to_list(conn.execute("SELECT email_type, COUNT(*) as count FROM email_log GROUP BY email_type").fetchall())
    email_total = conn.execute("SELECT COUNT(*) as c FROM email_log").fetchone()["c"]
    task_stats = db_rows_to_list(conn.execute("SELECT status, COUNT(*) as count FROM tasks GROUP BY status").fetchall())
    conn.close()

    biz_data = {"contacts": contacts, "pipeline": pipeline, "email_stats": email_stats,
                "email_total": email_total, "task_stats": task_stats}

    prompt = f"""You are a Business Analytics Agent. Generate a comprehensive BI report.

Task: {task['title']}
Description: {task['description']}

Business Data:
{json.dumps(biz_data, indent=2)}

Respond ONLY with valid JSON:
{{
  "report_title": "...", "executive_summary": "3-4 sentences",
  "kpis": [{{"name":"...", "value":"...", "trend":"up|down|stable", "insight":"..."}}],
  "funnel_analysis": {{"stages":[{{"stage":"...","count":0,"conversion_rate":"..."}}], "bottleneck":"...", "recommendation":"..."}},
  "opportunities": ["..."],
  "risks": ["..."],
  "action_items": [{{"priority":"high|medium|low","action":"...","owner":"agent_type","impact":"..."}}]
}}"""

    ai_response = call_gemini(prompt)
    report = parse_json_from_ai(ai_response)
    log_agent("analytics", f"Report generated: {len(report.get('kpis',[]))} KPIs", report.get("executive_summary",""), task_id, "success")

    final = {"agent": "analytics", "report": report,
             "data_snapshot": {"total_contacts": len(contacts), "emails_sent": email_total, "tasks_tracked": sum(t.get("count",0) for t in task_stats)}}
    update_task(task_id, "completed", json.dumps(final))
    return final


def run_followup_agent(task):
    task_id = task["id"]
    log_agent("followup", "Task started", task["title"], task_id)
    update_task(task_id, "running")

    contacts = tool_get_all_contacts()

    prompt = f"""You are a Follow-up Agent. Design and send follow-up sequences.

Task: {task['title']}
Description: {task['description']}

CRM Contacts:
{json.dumps(contacts, indent=2)}

Create personalized follow-up emails for contacts needing attention.
Respond ONLY with valid JSON:
{{
  "strategy": "overall strategy",
  "sequence_plan": [
    {{
      "contact_email": "...", "contact_name": "...", "contact_stage": "...",
      "follow_up_type": "initial_outreach|check_in|proposal_nudge|closing|re_engagement",
      "email": {{"subject":"...", "body":"full personalized email body"}},
      "rationale": "..."
    }}
  ],
  "expected_conversions": "...",
  "summary": "..."
}}"""

    ai_response = call_gemini(prompt)
    plan = parse_json_from_ai(ai_response)
    sent = []

    for seq in plan.get("sequence_plan", []):
        email = seq.get("email", {})
        if email.get("subject") and seq.get("contact_email"):
            r = tool_send_email(seq.get("contact_email",""), seq.get("contact_name",""),
                                email.get("subject",""), email.get("body",""), seq.get("follow_up_type","follow_up"))
            sent.append({"email_id": r["id"], "to": seq.get("contact_name"), "type": seq.get("follow_up_type"), "subject": email.get("subject")})
            log_agent("followup", f"Follow-up → {seq.get('contact_name')} ({seq.get('follow_up_type')})", seq.get("rationale",""), task_id)

    final = {"agent": "followup", "strategy": plan.get("strategy",""), "followups_sent": len(sent),
             "sequence_details": sent, "expected_conversions": plan.get("expected_conversions",""),
             "summary": plan.get("summary","")}
    update_task(task_id, "completed", json.dumps(final))
    log_agent("followup", f"Task completed — {len(sent)} follow-ups sent", "", task_id, "success")
    return final


AGENT_RUNNERS = {
    "crm": run_crm_agent, "email": run_email_agent, "lead": run_lead_agent,
    "analytics": run_analytics_agent, "followup": run_followup_agent,
}


# ─── Orchestrator ──────────────────────────────────────────────────────────────

def orchestrate(request_id, title, description):
    """Master orchestration — runs in background thread."""
    log_agent("orchestrator", "Orchestration started", title, request_id)
    conn = get_db()
    conn.execute("UPDATE business_requests SET status='planning' WHERE id=?", (request_id,))
    conn.commit(); conn.close()

    try:
        prompt = f"""You are the Master Orchestrator for an AI Business Workforce.
Break down this business request into 3-5 tasks for specialized agents.

Request Title: {title}
Description: {description}

Available agents: {json.dumps(AGENT_DESCRIPTIONS, indent=2)}

Respond ONLY with valid JSON:
{{
  "plan_summary": "...",
  "tasks": [
    {{
      "agent": "crm|email|lead|analytics|followup",
      "title": "specific task title",
      "description": "detailed description with specific goals",
      "priority": 1-10,
      "requires_approval": false,
      "approval_reason": ""
    }}
  ],
  "expected_outcome": "..."
}}

Flag requires_approval=true only for mass emails (>20 people) or destructive operations."""

        ai_response = call_gemini(prompt)
        plan = parse_json_from_ai(ai_response)

        log_agent("orchestrator", f"Plan: {len(plan.get('tasks',[]))} tasks", plan.get("plan_summary",""), request_id)
        conn = get_db()
        conn.execute("UPDATE business_requests SET status='executing', result=? WHERE id=?",
                     (json.dumps({"plan": plan}), request_id))
        conn.commit(); conn.close()

        task_ids = []
        for tdef in plan.get("tasks", []):
            tid = create_task_db(request_id, tdef.get("agent","crm"), tdef.get("title","Task"),
                                 tdef.get("description",""), tdef.get("priority",5),
                                 tdef.get("requires_approval", False))
            task_ids.append({"id": tid, "agent": tdef.get("agent","crm"),
                             "requires_approval": tdef.get("requires_approval", False),
                             "approval_reason": tdef.get("approval_reason","")})

        for tinfo in task_ids:
            tid = tinfo["id"]
            task = get_task_db(tid)
            if not task:
                continue

            if tinfo.get("requires_approval"):
                approval_id = str(uuid.uuid4())[:10]
                conn = get_db()
                conn.execute("INSERT INTO approval_queue (id,task_id,request_id,title,description,context) VALUES (?,?,?,?,?,?)",
                             (approval_id, tid, request_id,
                              f"Approval needed: {task['title']}", task['description'],
                              json.dumps({"reason": tinfo.get("approval_reason","")})))
                conn.commit(); conn.close()
                update_task(tid, "waiting_approval")
                log_agent("orchestrator", f"Awaiting approval: {task['title']}", "", request_id, "warning")
                continue

            try:
                runner = AGENT_RUNNERS.get(tinfo["agent"])
                if runner:
                    runner(task)
                    log_agent("orchestrator", f"Task done ({tinfo['agent']}): {task['title']}", "", request_id, "success")
                    time.sleep(0.5)  # Brief pause between agents
            except Exception as e:
                log_agent("orchestrator", f"Task FAILED ({tinfo['agent']}): {str(e)}", "", request_id, "error")

        # Check pending approvals
        conn = get_db()
        pending = conn.execute("SELECT COUNT(*) as c FROM approval_queue WHERE status='pending' AND request_id=?", (request_id,)).fetchone()["c"]
        final_status = "waiting_approval" if pending > 0 else "completed"
        conn.execute("UPDATE business_requests SET status=?, updated_at=? WHERE id=?",
                     (final_status, datetime.utcnow().isoformat(), request_id))
        conn.commit(); conn.close()
        log_agent("orchestrator", f"Orchestration {final_status}", plan.get("expected_outcome",""), request_id, "success")

    except Exception as e:
        conn = get_db()
        conn.execute("UPDATE business_requests SET status='failed' WHERE id=?", (request_id,))
        conn.commit(); conn.close()
        log_agent("orchestrator", f"FAILED: {str(e)}", "", request_id, "error")
        raise


def execute_approved_task_bg(task_id, approval_id):
    task = get_task_db(task_id)
    if not task:
        return
    conn = get_db()
    conn.execute("UPDATE approval_queue SET status='approved',decision='approved',decided_at=? WHERE id=?",
                 (datetime.utcnow().isoformat(), approval_id))
    conn.execute("UPDATE tasks SET approved=1 WHERE id=?", (task_id,))
    conn.commit(); conn.close()

    runner = AGENT_RUNNERS.get(task["agent_type"])
    if runner:
        runner(task)


# ─── HTTP Request Handler ──────────────────────────────────────────────────────

class AIWorkforceHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # Suppress default request logging

    def send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, message):
        self.send_json({"detail": message}, status)

    def get_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length)) if length > 0 else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]
        params = {}
        if '?' in self.path:
            params = dict(urllib.parse.parse_qsl(self.path.split('?')[1]))

        try:
            if path == '/' or path == '/index.html':
                if FRONTEND_PATH.exists():
                    content = FRONTEND_PATH.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', len(content))
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    self.send_json({"message": "AI Workforce API — frontend not found"})

            elif path == '/api/dashboard':
                conn = get_db()
                total_req = conn.execute("SELECT COUNT(*) as c FROM business_requests").fetchone()["c"]
                comp_req = conn.execute("SELECT COUNT(*) as c FROM business_requests WHERE status='completed'").fetchone()["c"]
                total_tasks = conn.execute("SELECT COUNT(*) as c FROM tasks").fetchone()["c"]
                comp_tasks = conn.execute("SELECT COUNT(*) as c FROM tasks WHERE status='completed'").fetchone()["c"]
                failed_tasks = conn.execute("SELECT COUNT(*) as c FROM tasks WHERE status='failed'").fetchone()["c"]
                contacts = conn.execute("SELECT COUNT(*) as c FROM crm_contacts").fetchone()["c"]
                emails = conn.execute("SELECT COUNT(*) as c FROM email_log").fetchone()["c"]
                pending_approvals = conn.execute("SELECT COUNT(*) as c FROM approval_queue WHERE status='pending'").fetchone()["c"]
                agent_stats = db_rows_to_list(conn.execute("SELECT agent_type, COUNT(*) as count FROM tasks WHERE status='completed' GROUP BY agent_type").fetchall())
                conn.close()
                self.send_json({
                    "requests": {"total": total_req, "completed": comp_req},
                    "tasks": {"total": total_tasks, "completed": comp_tasks, "failed": failed_tasks,
                              "success_rate": round((comp_tasks / max(total_tasks,1)) * 100, 1)},
                    "crm": {"total_contacts": contacts},
                    "emails": {"sent": emails},
                    "pending_approvals": pending_approvals,
                    "agent_performance": agent_stats,
                    "timestamp": datetime.utcnow().isoformat()
                })

            elif path == '/api/requests':
                conn = get_db()
                rows = db_rows_to_list(conn.execute("SELECT * FROM business_requests ORDER BY created_at DESC").fetchall())
                conn.close()
                self.send_json({"requests": rows, "total": len(rows)})

            elif re.match(r'^/api/requests/[^/]+$', path):
                req_id = path.split('/')[-1]
                conn = get_db()
                req = db_row_to_dict(conn.execute("SELECT * FROM business_requests WHERE id=?", (req_id,)).fetchone())
                tasks = db_rows_to_list(conn.execute("SELECT * FROM tasks WHERE request_id=? ORDER BY priority DESC", (req_id,)).fetchall())
                conn.close()
                if not req:
                    self.send_error_json(404, "Request not found")
                else:
                    self.send_json({**req, "tasks": tasks})

            elif path == '/api/approvals':
                conn = get_db()
                approvals = db_rows_to_list(conn.execute("SELECT * FROM approval_queue WHERE status='pending' ORDER BY created_at ASC").fetchall())
                conn.close()
                self.send_json({"approvals": approvals, "total": len(approvals)})

            elif path == '/api/crm/contacts':
                conn = get_db()
                contacts = db_rows_to_list(conn.execute("SELECT * FROM crm_contacts ORDER BY lead_score DESC").fetchall())
                conn.close()
                self.send_json({"contacts": contacts, "total": len(contacts)})

            elif path == '/api/crm/pipeline':
                conn = get_db()
                pipeline = db_rows_to_list(conn.execute("SELECT stage, COUNT(*) as count, SUM(value) as total_value FROM crm_deals GROUP BY stage").fetchall())
                total = conn.execute("SELECT COUNT(*) as c FROM crm_contacts").fetchone()["c"]
                conn.close()
                self.send_json({"pipeline": pipeline, "total_contacts": total})

            elif path == '/api/emails':
                limit = int(params.get('limit', 50))
                conn = get_db()
                emails = db_rows_to_list(conn.execute("SELECT * FROM email_log ORDER BY sent_at DESC LIMIT ?", (limit,)).fetchall())
                conn.close()
                self.send_json({"emails": emails, "total": len(emails)})

            elif path == '/api/emails/stats':
                conn = get_db()
                by_type = db_rows_to_list(conn.execute("SELECT email_type, COUNT(*) as count FROM email_log GROUP BY email_type").fetchall())
                total = conn.execute("SELECT COUNT(*) as c FROM email_log").fetchone()["c"]
                conn.close()
                self.send_json({"total_sent": total, "by_type": by_type})

            elif path == '/api/activity':
                limit = int(params.get('limit', 100))
                conn = get_db()
                logs = db_rows_to_list(conn.execute("SELECT * FROM agent_logs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall())
                conn.close()
                self.send_json({"activity": logs, "total": len(logs)})

            else:
                self.send_error_json(404, f"Route not found: {path}")

        except Exception as e:
            self.send_error_json(500, str(e))

    def do_POST(self):
        path = self.path.split('?')[0]
        try:
            body = self.get_body()

            if path == '/api/requests':
                title = body.get('title', '').strip()
                desc = body.get('description', '').strip()
                if not title or not desc:
                    return self.send_error_json(400, "title and description required")
                if not GEMINI_API_KEY:
                    return self.send_error_json(500, "GEMINI_API_KEY not set in .env file")

                req_id = str(uuid.uuid4())[:12]
                conn = get_db()
                conn.execute("INSERT INTO business_requests (id,title,description,status) VALUES (?,?,?,'pending')",
                             (req_id, title, desc))
                conn.commit(); conn.close()

                # Run orchestration in background thread
                t = threading.Thread(target=orchestrate, args=(req_id, title, desc), daemon=True)
                t.start()

                self.send_json({
                    "request_id": req_id, "status": "accepted",
                    "message": "Business request accepted. AI agents are now working on it.",
                    "tracking_url": f"/api/requests/{req_id}"
                }, 202)

            elif re.match(r'^/api/approvals/[^/]+$', path):
                approval_id = path.split('/')[-1]
                decision = body.get('decision', '')
                reason = body.get('reason', '')

                conn = get_db()
                approval = db_row_to_dict(conn.execute("SELECT * FROM approval_queue WHERE id=?", (approval_id,)).fetchone())
                conn.close()

                if not approval:
                    return self.send_error_json(404, "Approval not found")
                if approval["status"] != "pending":
                    return self.send_error_json(400, f"Already decided: {approval['status']}")

                if decision == "approve":
                    t = threading.Thread(target=execute_approved_task_bg,
                                         args=(approval["task_id"], approval_id), daemon=True)
                    t.start()
                    self.send_json({"status": "approved", "message": "Task approved and executing"})
                else:
                    conn = get_db()
                    conn.execute("UPDATE approval_queue SET status='rejected',decision='rejected',decided_at=? WHERE id=?",
                                 (datetime.utcnow().isoformat(), approval_id))
                    conn.execute("UPDATE tasks SET status='failed',error=? WHERE id=?",
                                 (f"Rejected: {reason}", approval["task_id"]))
                    conn.commit(); conn.close()
                    self.send_json({"status": "rejected", "message": "Task rejected"})

            elif path == '/api/crm/contacts':
                name = body.get('name','').strip()
                email = body.get('email','').strip()
                if not name or not email:
                    return self.send_error_json(400, "name and email required")
                result = tool_create_contact(name, email, body.get('company',''), body.get('phone',''))
                self.send_json(result, 201)

            else:
                self.send_error_json(404, f"Route not found: {path}")

        except Exception as e:
            self.send_error_json(500, str(e))


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*60)
    print("  [AI] AI WORKFORCE FOR BUSINESSES")
    print("  Autonomous Multi-Agent Orchestration System")
    print("="*60)

    init_db()

    if not GEMINI_API_KEY:
        print("\n  [!] WARNING: GEMINI_API_KEY not set!")
        print("  Create a .env file with: GEMINI_API_KEY=your_key_here")
        print("  Get your key at: https://aistudio.google.com/app/apikey\n")
    else:
        print(f"\n  [OK] Gemini API key loaded")

    print(f"\n  [*] Dashboard: http://localhost:8000")
    print(f"  [*] API Base:  http://localhost:8000/api")
    print(f"  [*] Database:  {DB_PATH}")
    print("\n  Agents Ready:")
    for name, desc in AGENT_DESCRIPTIONS.items():
        print(f"    [{name.upper()}] {name.capitalize()}: {desc}")
    print("\n" + "="*60 + "\n")

    server = HTTPServer(('0.0.0.0', 8000), AIWorkforceHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[AI Workforce] Server stopped.")


if __name__ == "__main__":
    main()
