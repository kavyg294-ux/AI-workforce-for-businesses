"""
Database setup and initialization for AI Workforce.
Uses aiosqlite for async SQLite operations.
"""

import aiosqlite
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "workforce.db"


async def get_db():
    """Get database connection."""
    return await aiosqlite.connect(DB_PATH)


async def init_db():
    """Initialize all database tables."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Business requests
        await db.execute("""
            CREATE TABLE IF NOT EXISTS business_requests (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                result TEXT
            )
        """)

        # Task queue
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT DEFAULT 'queued',
                priority INTEGER DEFAULT 5,
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                requires_approval INTEGER DEFAULT 0,
                approved INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                completed_at TEXT,
                result TEXT,
                error TEXT,
                metadata TEXT,
                FOREIGN KEY (request_id) REFERENCES business_requests(id)
            )
        """)

        # CRM contacts
        await db.execute("""
            CREATE TABLE IF NOT EXISTS crm_contacts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                company TEXT,
                phone TEXT,
                lead_score INTEGER DEFAULT 0,
                stage TEXT DEFAULT 'lead',
                tags TEXT DEFAULT '[]',
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # CRM deals
        await db.execute("""
            CREATE TABLE IF NOT EXISTS crm_deals (
                id TEXT PRIMARY KEY,
                contact_id TEXT NOT NULL,
                title TEXT NOT NULL,
                value REAL DEFAULT 0,
                stage TEXT DEFAULT 'prospecting',
                probability INTEGER DEFAULT 10,
                close_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (contact_id) REFERENCES crm_contacts(id)
            )
        """)

        # Email log
        await db.execute("""
            CREATE TABLE IF NOT EXISTS email_log (
                id TEXT PRIMARY KEY,
                to_email TEXT NOT NULL,
                to_name TEXT,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT DEFAULT 'sent',
                email_type TEXT DEFAULT 'general',
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
                opened_at TEXT,
                clicked_at TEXT
            )
        """)

        # Agent activity log
        await db.execute("""
            CREATE TABLE IF NOT EXISTS agent_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_type TEXT NOT NULL,
                task_id TEXT,
                action TEXT NOT NULL,
                details TEXT,
                status TEXT DEFAULT 'info',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Human approval queue
        await db.execute("""
            CREATE TABLE IF NOT EXISTS approval_queue (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                context TEXT,
                status TEXT DEFAULT 'pending',
                decision TEXT,
                decided_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
        """)

        # Seed demo CRM contacts
        demo_contacts = [
            ("c001", "Alice Johnson", "alice@techcorp.com", "TechCorp Inc", "+1-555-0101", 85, "qualified"),
            ("c002", "Bob Martinez", "bob@startupxyz.com", "StartupXYZ", "+1-555-0102", 42, "lead"),
            ("c003", "Carol Lee", "carol@enterprise.com", "Enterprise Solutions", "+1-555-0103", 91, "proposal"),
            ("c004", "David Kim", "david@innovate.io", "Innovate.io", "+1-555-0104", 67, "qualified"),
            ("c005", "Eva Brown", "eva@globalfirm.com", "Global Firm LLC", "+1-555-0105", 23, "lead"),
        ]
        for c in demo_contacts:
            await db.execute("""
                INSERT OR IGNORE INTO crm_contacts (id, name, email, company, phone, lead_score, stage)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, c)

        await db.commit()
    print(f"[DB] Database initialized at {DB_PATH}")
