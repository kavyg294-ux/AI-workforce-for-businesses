# AI Workforce for Businesses

> Autonomous multi-agent orchestration for cross-platform enterprise task execution.

## Quick Start

1. **Get a Gemini API Key** → [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

2. **Create your `.env` file:**
   ```
   GEMINI_API_KEY=your_api_key_here
   ```

3. **Run the server:**
   ```bash
   # Windows — double-click start.bat OR:
   python server.py
   ```

4. **Open Dashboard:** [http://localhost:8000](http://localhost:8000)

---

## System Architecture

```
Business Request
      │
      ▼
┌─────────────────┐
│  Orchestrator   │  ← AI decomposes request into tasks
│     Agent       │
└────────┬────────┘
         │ Plans & queues tasks
    ┌────┴────┐
    ▼         ▼
┌──────┐  ┌────────┐  ┌──────┐  ┌───────────┐  ┌─────────┐
│ CRM  │  │ Email  │  │ Lead │  │ Analytics │  │Follow-up│
│Agent │  │ Agent  │  │Agent │  │   Agent   │  │  Agent  │
└──┬───┘  └───┬────┘  └──┬───┘  └─────┬─────┘  └────┬────┘
   │          │           │            │              │
   ▼          ▼           ▼            ▼              ▼
CRM DB    Email Log   CRM Scores   BI Reports    Follow-ups
```

## AI Agents

| Agent | Role | Actions |
|-------|------|---------|
| **Orchestrator** | Plans and coordinates all agents | Decomposes requests, queues tasks |
| **CRM Agent** | Manages contacts & deals | Create contacts, update stages, create deals |
| **Email Agent** | Personalized outreach | Draft & send tailored emails |
| **Lead Manager** | Lead qualification | Score leads, segment hot/warm/cold |
| **Analytics Agent** | Business intelligence | KPIs, funnel analysis, reports |
| **Follow-up Agent** | Automated sequences | Follow-up emails, re-engagement |

## How It Works

1. **Submit** a business request in natural language
2. **Orchestrator** calls Gemini AI to decompose it into 3–6 tasks
3. **Tasks** are queued and assigned to specialized agents
4. **Agents** execute using AI reasoning + simulated business tools
5. **Sensitive operations** are paused for human approval
6. **Dashboard** shows real-time progress, results, CRM, email log

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/requests` | Submit a business request |
| `GET` | `/api/requests` | List all requests |
| `GET` | `/api/requests/{id}` | Get request + task details |
| `GET` | `/api/approvals` | List pending approvals |
| `POST` | `/api/approvals/{id}` | Approve or reject a task |
| `GET` | `/api/crm/contacts` | All CRM contacts |
| `POST` | `/api/crm/contacts` | Add a contact |
| `GET` | `/api/crm/pipeline` | Deal pipeline summary |
| `GET` | `/api/emails` | Email activity log |
| `GET` | `/api/activity` | Live agent activity feed |
| `GET` | `/api/dashboard` | Dashboard KPI stats |

## Example Requests

**Lead Onboarding:**
```json
{
  "title": "Onboard New Leads from Marketing Campaign",
  "description": "We collected 50 new leads from LinkedIn. Add them to CRM, score each, send personalized intro emails, and schedule follow-ups for hot leads."
}
```

**Pipeline Review:**
```json
{
  "title": "Q4 Sales Pipeline Review",
  "description": "Analyze all deals, identify stalled ones, update deal stages, generate pipeline report with KPIs, and send follow-ups to qualified leads."
}
```

## Project Structure

```
ai-workforce/
├── server.py          # Main server (pure Python, no external deps)
├── frontend/
│   └── index.html     # Real-time dashboard
├── workforce.db        # SQLite database (auto-created)
├── .env               # API key configuration
├── start.bat          # Windows startup script
└── README.md
```

## Human-in-the-Loop

The system automatically detects sensitive operations and pauses for human approval:
- Mass email campaigns (>20 recipients)
- Destructive data operations
- High-value deal modifications

Approvals are shown in the **Approvals** tab of the dashboard.

## Tech Stack

- **Backend**: Pure Python 3.10+ (no external packages required)
- **AI**: Google Gemini 2.0 Flash via REST API
- **Database**: SQLite3 (built-in)
- **Frontend**: HTML + Tailwind CSS + Vanilla JS
- **Server**: Python `http.server` (built-in)
