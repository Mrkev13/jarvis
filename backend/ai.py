import json
import os
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import HTTPException
from openai import OpenAI
from sqlalchemy import update as _sql_update

from tools import get_wot_resources, get_wot_grinds
from tools import get_finance_summary, get_finance_transactions
from tools import get_school_subjects, get_school_assignments, get_school_exams
from tools import get_work_summary, get_work_sessions
from tools import get_mff_summary, get_mff_characters
from tools import get_goals_summary, get_goals
from tools import get_memories
from tools import get_notifications, get_notification_summary, get_goal_progress_history
from tools import add_work_session, add_finance_transaction
from tools import add_school_subject, add_school_assignment, add_school_exam
from tools import update_wot_resource, upsert_wot_grind
from tools import upsert_mff_character, upsert_goal
from tools import save_memory
from activity_service import log_activity, delta_dict
from database import SessionLocal
from models import PendingAction

load_dotenv()

client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)


SYSTEM_PROMPT = """
You are the AI assistant inside Standa Hub, a personal dashboard.

You help manage:
- World of Tanks (WoT) resources and tank grinds
- Personal finances (income, expenses, transactions)
- University / school (subjects, assignments, exams)
- Work (work sessions, hours, earnings)
- Marvel Future Fight (MFF) characters and builds
- Personal goals (progress, priorities, target dates)
- Long-term user memory (preferences, plans, routines, constraints, decisions)

You have access to TWO categories of tools:

1. READ TOOLS
   - You can call them immediately.
   - They never change user data.
   - Examples:
     get_wot_grinds
     get_wot_resources
     get_work_summary
     get_work_sessions
     get_finance_summary
     get_finance_transactions
     get_school_subjects
     get_school_assignments
     get_school_exams
     get_mff_summary
     get_mff_characters
     get_goals
     get_goals_summary
     get_memories

2. WRITE TOOLS
   - They change user data.
   - Examples:
     add_work_session
     add_finance_transaction
     add_school_subject
     add_school_assignment
     add_school_exam
     update_wot_resource
     upsert_wot_grind
     upsert_mff_character
     upsert_goal
     save_memory

When you decide to use a WRITE tool:
- CALL the write tool with the correct arguments.
- Do NOT imply that the change has already happened.
- The system will return confirmation_required.
- After receiving confirmation_required, tell the user that the action has been prepared and is waiting for explicit confirmation in the UI.
- Never bypass the confirmation flow.

================================================================================
TOOL USAGE RULES

1. Before answering, determine which tools are actually needed.

2. Call ONLY relevant tools.

Examples:

- "Kolik zbývá XP na VZ.55?"
  → call get_wot_grinds

- "Kolik mám kreditů?"
  → call get_wot_resources

- "Kolik jsem odpracoval tento měsíc?"
  → call get_work_summary

- "Jaká je moje finanční bilance?"
  → call get_finance_summary

- "Jaké mám otevřené úkoly?"
  → call get_school_assignments

- "Kolik mám T4 postav?"
  → call get_mff_summary

- "Jaké mám aktivní cíle?"
  → call get_goals

- "Pamatuj si, že po VZ.55 chci začít CS linii."
  → call save_memory

- "Přidej mi dnes do práce 7,5 hodiny za 325 Kč/h na Servindu."
  → call add_work_session with:
    date_value=<today in YYYY-MM-DD>,
    hours=7.5,
    project="Servind",
    hourly_rate=325

- "Co mám dnes udělat?"
  → use planner flow and multiple relevant read tools

- General chit-chat or greetings
  → no tool needed

3. Avoid redundant tool calls.
   Do not call the same tool again with the same arguments during one request unless:
   - the user explicitly asks for fresh data,
   - the previous tool call failed,
   - or another tool result shows that a second call is necessary.

4. After receiving tool results, answer in natural human-readable language.

5. Tool results are authoritative for current application data.

================================================================================
CRITICAL DATA RULES

1. Never invent missing user data.

2. Never invent:
   - game mechanics
   - currencies
   - conversion rates
   - rewards
   - prices
   - events
   - rentals
   - loans
   - features
   - deadlines
   - exam dates
   - XP values
   - financial values
   - work hours
   - goal progress

3. If required information is missing, say so clearly.

4. If current external information is required and no tool provides it, state that current external data would need to be checked.

5. For numerical questions:
   - use exact values returned by tools
   - calculate directly from those values
   - do not estimate unless explicitly stated

6. Prefer concise, practical answers.

7. Do not add generic or unrelated advice unless it materially helps answer the user's request.

8. Preserve conversation context.
   Understand follow-up questions such as:
   - "Jsi si jistý?"
   - "A kolik mi teda zbývá?"
   - "A potom co?"
   - "Myslel jsem ten druhý."

9. When the user asks for verification or confirmation:
   - reuse a valid previous tool result if it is still relevant,
   - or call the relevant read tool again when fresh verification is useful.

10. Never expose internal tool-call artifacts.

Do not output:
- raw tool-call IDs
- internal tool names unless useful for debugging
- hidden arguments
- internal execution metadata
- raw JSON tool responses

Present results as normal Czech text, lists, or short tables.

================================================================================
MEMORY RULES

Memory is for long-term context only.

Memory may contain:
- preferences
- plans
- decisions
- routines
- constraints
- long-term context

Examples:
- "Po VZ.55 chce uživatel začít CS linii."
- "Uživatel preferuje krátké týdenní studijní plány."
- "Uživatel chce dlouhodobě šetřit na cestování."

Memory is NOT authoritative for volatile or exact current data.

NEVER use memory as the source of truth for:
- money balances
- transaction totals
- XP amounts
- work hours
- earnings
- assignment deadlines
- exam dates
- goal progress
- current WoT resources
- current MFF character state

For these values, always call the relevant module READ tool.

Memory may supplement module data with long-term context.

If memory conflicts with current module data:
- current module data wins.

If the user explicitly says:
- "pamatuj si"
- "zapamatuj si"
- "ulož si"
- "do budoucna chci..."

and the information is appropriate for long-term memory:
→ call save_memory.

Do NOT save temporary numerical facts into memory.

================================================================================
WRITE SAFETY RULES

1. WRITE tools must always go through confirmation.

2. Never claim:
   - "uložil jsem"
   - "změnil jsem"
   - "přidal jsem"

before confirmation has actually succeeded.

3. When the tool returns confirmation_required, use wording such as:
   "Připravil jsem změnu k potvrzení."

4. Use correct argument names for every WRITE tool.

5. Relative dates:
   - "dnes" = CURRENT APPLICATION DATE
   - "zítra" = CURRENT APPLICATION DATE + 1 day
   - "včera" = CURRENT APPLICATION DATE - 1 day

6. Never guess a missing write parameter if it would materially change the record.
   If necessary, ask for the missing value.

================================================================================
PLANNER RULES

Apply these rules when the user asks:
- what to do today
- what to prioritize
- what to do this week
- what to focus on
- how to proceed against goals
- which goals are stagnating
- how to divide time between school/work/finance/games/etc.

Planner is READ-ONLY.

1. Start directly by calling:
   get_goals

2. Then call:
   get_memories

3. Determine which goal areas are relevant.

4. Call only the module tools needed for those areas.

Examples:

School:
- get_school_assignments
- get_school_exams

Work:
- get_work_summary
- get_work_sessions if useful

Finance:
- get_finance_summary
- get_finance_transactions if useful

WoT:
- get_wot_grinds
- get_wot_resources

MFF:
- get_mff_characters
- get_mff_summary if useful

6. PRIORITY ORDER:

Highest priority first:

1. Overdue assignments or obligations
2. Hard deadlines within 14 days
3. Exams/tests within 14 days
4. Financial constraints or lagging monthly targets
5. Work commitments or lagging monthly-hour targets
6. High-priority goals with progress below 50%
7. Medium-priority goals
8. Low-priority goals
9. Routine or nice-to-have tasks

7. Do not invent tasks just to fill the plan.

8. Return up to 5 concrete actions.
   Normally use 3–5 actions when enough real data exists.

9. If only 1–2 meaningful actions are supported by data:
   return only those 1–2 actions.

10. Each action must be:
   - specific
   - actionable
   - based on tool data or memory
   - bounded enough to act on immediately

Bad:
- "Více se učit."

Good:
- "Projít kapitolu 3 z práva před pátečním testem."

11. Planner must never:
   - create goals automatically
   - modify goal progress automatically
   - save memories automatically
   - modify finance/work/school/game data automatically

If the user wants an action from the plan saved:
→ use the corresponding WRITE tool and confirmation flow.

12. Avoid generic filler such as:
   - "sleduj eventy"
   - "hraj efektivně"
   - "uč se pravidelně"
   - "šetři peníze"

unless directly supported by current context and useful.

13. For progression advice, especially WoT and MFF:
   - prioritize exact stored data
   - use relevant memories
   - avoid speculative gameplay advice
   - prefer 3–5 concrete next steps
   - do not invent mechanics

================================================================================
PLANNER OUTPUT FORMAT

When planner mode is used:

First write 1–2 short Czech sentences summarizing the situation.

Then output exactly one fenced JSON block:

```json
{
  "summary": "Krátké české shrnutí hlavní priority.",
  "actions": [
    {
      "priority": 1,
      "area": "school",
      "title": "Konkrétní akce",
      "reason": "Krátký důvod."
    }
  ]
}

Allowed area values:

school
work
finance
wot
mff
personal
fitness
hobby
travel
general

Rules:

priorities start at 1
increase by exactly 1
title should normally be 5–15 words
title must not exceed 30 words
reason must not exceed 40 words
do not output JSON outside this one fenced block
do not mention the schema to the user

================================================================================
AFFORDABILITY RULE

When the user asks whether they can afford something:

Get the relevant current resources.
Compare available amount against cost.
Calculate exact surplus or shortfall.
Give a direct recommendation.
Do not invent ways to obtain the missing amount.

================================================================================
LANGUAGE

The user communicates primarily in Czech.

Reply in Czech unless the user switches to another language.
"""


READ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_wot_resources",
            "description": "Get current World of Tanks resources (credits, gold, bonds, free XP).",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_wot_grinds",
            "description": "Get current World of Tanks active tank grinds with XP remaining, priority and status.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_finance_summary",
            "description": "Get finance summary: total income, expenses, balance and transactions count.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_finance_transactions",
            "description": "Get the full list of finance transactions (income and expenses), newest first.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_school_subjects",
            "description": "Get the list of school subjects with names, codes, semesters, credits and active flag.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_school_assignments",
            "description": "Get the list of school assignments with title, due date, priority, status and subject.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_school_exams",
            "description": "Get the list of school exams with title, exam date, status, notes and subject.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_work_summary",
            "description": "Get work hours and earnings summary (total and current month).",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_work_sessions",
            "description": "Get the list of work sessions (date, hours, project, description, hourly rate, earnings), newest first.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_mff_summary",
            "description": "Get Marvel Future Fight summary (tracked characters, T4 count, T3 count, priority count).",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_mff_characters",
            "description": "Get the list of tracked Marvel Future Fight characters with tier, level, uniform, CTP, artifact, priority and status.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_goals_summary",
            "description": "Get goals counts by status (active, in_progress, completed, paused, cancelled) and total count.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_goals",
            "description": "Get the list of user goals with area, title, description, status, priority, progress, target date.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_memories",
            "description": (
                "Get long-term user memories: preferences, decisions, plans, routines, constraints, context. "
                "This is NOT the source of truth for numbers, currency, XP, dates — those always come from the "
                "dedicated module tables (wot_resources, finance_transactions, goals, etc.). "
                "Use memories for higher-level patterns the user stated they want remembered long-term, "
                "e.g. 'po VZ.55 pokračovat CS linií', 'preferuje krátké týdenní plány'. "
                "Filtering parameters are OPTIONAL. Pass area='wot' to get only WoT-related memories, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {
                        "type": "string",
                        "description": (
                            "Optional area filter: 'general', 'wot', 'finance', 'school', 'work', 'mff', "
                            "'personal', 'fitness', 'hobby', 'travel'."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "enum": ["preference", "decision", "context", "routine", "constraint", "plan"],
                        "description": (
                            "Optional category filter: preference=uživatelovo přání, decision=přijaté rozhodnutí, "
                            "context=obecný kontext, routine=opakující se rutina, constraint=omezení, "
                            "plan=dlouhodobý plán."
                        ),
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_notifications",
            "description": "Get notifications list with optional filters (unread_only, severity, area, include_resolved).",
            "parameters": {
                "type": "object",
                "properties": {
                    "unread_only": {"type": "boolean"},
                    "severity": {"type": "string", "enum": ["info", "warning", "important"]},
                    "area": {"type": "string"},
                    "include_resolved": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_notification_summary",
            "description": "Get notifications summary counters (unread, important, warning, info).",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_goal_progress_history",
            "description": "Get goal progress history snapshots for a given goal_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {"type": "integer"},
                },
                "required": ["goal_id"],
                "additionalProperties": False,
            },
        },
    },
]


WRITE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_work_session",
            "description": (
                "Prepare a new work session to be added to Standa Hub. "
                "This action changes user data and therefore requires confirmation. "
                "Use this when the user says things like 'přidej do práce X hodin', "
                "'zaznamenej práci', 'přidej mi dnes do práce'. "
                "Argument 'date_value' must be YYYY-MM-DD. For 'dnes' use today's date. "
                "Argument 'project' is the project name / company name. "
                "Argument 'hourly_rate' is the hourly rate in CZK. "
                "Optional 'description' is any extra note."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_value": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format (e.g. 2026-09-10).",
                    },
                    "hours": {
                        "type": "number",
                        "description": "Number of hours worked (e.g. 7.5).",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project or company name.",
                    },
                    "hourly_rate": {
                        "type": "number",
                        "description": "Hourly rate in CZK (e.g. 325).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description of work done.",
                    },
                },
                "required": [
                    "date_value",
                    "hours",
                    "project",
                    "hourly_rate",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_finance_transaction",
            "description": (
                "Prepare a new finance transaction (income or expense) to be added. "
                "Requires user confirmation. "
                "Use when user says 'přidej příjem', 'přidej výdaj', 'utratil jsem X Kč za Y', "
                "'přidej 450 Kč za benzín'. "
                "Always try to infer the transaction_type from context: "
                "positive payment received = 'income', cost / spent = 'expense'. "
                "For expenses if category is unclear use a sensible default like 'Doprava' for fuel, "
                "'Jídlo' for groceries/restaurants, 'Zábava' for entertainment, 'Ostatní' otherwise."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "Transaction amount in CZK (always positive number).",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category label (e.g. 'Doprava', 'Jídlo', 'Mzda', 'Práce', 'Ostatní').",
                    },
                    "transaction_type": {
                        "type": "string",
                        "enum": ["income", "expense"],
                        "description": "'income' = příjem, 'expense' = výdaj.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional note like 'Benzín', 'Plat za srpen'.",
                    },
                },
                "required": ["amount", "category", "transaction_type"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_school_subject",
            "description": (
                "Add a new school subject. Requires confirmation. "
                "Use when user says 'přidej předmět X', 'vytvoř nový předmět'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Full subject name (e.g. 'English in IT')."},
                    "code": {"type": "string", "description": "Optional subject abbreviation/code."},
                    "semester": {"type": "string", "description": "Semester label, e.g. 'ZS 2026/2027'."},
                    "credits": {"type": "integer", "description": "Number of ECTS credits (default 0)."},
                    "active": {
                        "type": "boolean",
                        "description": "True if the subject is currently studied (default True).",
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_school_assignment",
            "description": (
                "Add a new school assignment / homework / project / semestral work. "
                "Requires confirmation. "
                "Use when user says 'přidej úkol', 'mám odevzdat X do Y data', 'přidej semestrálku'. "
                "You need subject_id — if the user mentions the subject name, try to find its id "
                "by calling get_school_subjects READ tool first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Assignment title."},
                    "subject_id": {
                        "type": "integer",
                        "description": "ID of the subject (from get_school_subjects).",
                    },
                    "description": {"type": "string", "description": "Optional longer description."},
                    "due_date": {
                        "type": "string",
                        "description": "Due date in YYYY-MM-DD format.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Priority (default 'medium').",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["todo", "in_progress", "done", "overdue"],
                        "description": "Status (default 'todo').",
                    },
                },
                "required": ["title", "subject_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_school_exam",
            "description": (
                "Add a new school exam (zkouška / zápočet / písemka). Requires confirmation. "
                "Use when user says 'přidej zkoušku', 'mám písemku z X', 'zkouška 15. listopadu'. "
                "Need subject_id — if user only mentions subject name, call get_school_subjects FIRST."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Exam title."},
                    "subject_id": {
                        "type": "integer",
                        "description": "Subject ID (from get_school_subjects).",
                    },
                    "exam_type": {
                        "type": "string",
                        "enum": ["exam", "test", "quiz", "paper", "other"],
                        "description": "Type: exam=zkouška, test=písemka, quiz=kvíz, paper=zápočtový, other=ostatní.",
                    },
                    "exam_date": {
                        "type": "string",
                        "description": "Exam date in YYYY-MM-DD format.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["upcoming", "passed", "failed", "scheduled"],
                        "description": "Status (default 'upcoming').",
                    },
                    "notes": {"type": "string", "description": "Optional notes."},
                },
                "required": ["title", "subject_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_wot_resource",
            "description": (
                "Set the current amount of a WoT resource (credits, gold, bonds, free_xp, ...). "
                "This will UPSERT the value (update if resource exists, insert if not). "
                "Requires confirmation. "
                "Use when user says 'mám 12 miliónů kreditů', 'nastav gold na 25 000', "
                "'aktualizuj WoT resources'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "resource": {
                        "type": "string",
                        "enum": ["credits", "gold", "bonds", "free_xp"],
                        "description": "Resource identifier.",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Current amount (integer is best).",
                    },
                },
                "required": ["resource", "amount"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_wot_grind",
            "description": (
                "Create or update a WoT tank grind (update if tank already tracked, insert if new). "
                "Requires confirmation. "
                "Use when user says 'začni grindoat VZ.55', 'zbývá 200k XP na VZ.55', "
                "'nastav status grindu na completed'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tank": {"type": "string", "description": "Tank name (e.g. 'VZ.55')."},
                    "xp_remaining": {
                        "type": "number",
                        "description": "Remaining XP needed.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Grind priority.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused", "completed", "planned"],
                        "description": "Status.",
                    },
                },
                "required": ["tank", "xp_remaining"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_mff_character",
            "description": (
                "Create or update a Marvel Future Fight tracked character by unique NAME. "
                "If character with that name exists, update its fields, otherwise insert. "
                "Requires confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Character name (unique key)."},
                    "tier": {
                        "type": "string",
                        "enum": ["T1", "T2", "T3", "T4"],
                        "description": "Character tier.",
                    },
                    "level": {"type": "integer", "description": "Character level (1-80 usually)."},
                    "uniform": {"type": "string", "description": "Uniform/build name, empty string if none."},
                    "ctp": {"type": "string", "description": "CTP (card) name or 'none' if none."},
                    "artifact": {"type": "string", "description": "Artifact name or empty string."},
                    "role": {"type": "string", "description": "DEPRECATED - use roles instead. Legacy free-text roles (e.g. 'ABX · ABL · GBR')."},
                    "roles": {"type": "array", "items": {"type": "string", "enum": ["ABX","ABL","GBR","World Boss","PvP","Dispatch","Other"]}, "description": "Multi-select list of character roles/mode tags. Preferred over legacy 'role'."},
                    "team": {"type": "string", "description": "DEPRECATED - use team_supports. Legacy team supports text."},
                    "team_supports": {"type": "string", "description": "Recommended team / supports (free text, e.g. 'White Fox + Shuri')."},
                    "uru_state": {"type": "string", "description": "DEPRECATED - use uru_slots_total/filled + odin_blessings_count. Legacy text like '20/20 · 6 OB'."},
                    "uru_slots_total": {"type": "integer", "description": "Total Uru slots (default 20)."},
                    "uru_slots_filled": {"type": "integer", "description": "Filled Uru slots (0..uru_slots_total)."},
                    "odin_blessings_count": {"type": "integer", "description": "Number of Odin's Blessings (0+)."},
                    "iso8_set": {"type": "string", "description": "ISO-8 set name or status."},
                    "build_completeness": {"type": "integer", "description": "IGNORED (read-only). Always recomputed automatically from the 8 build components 0-100."},
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Build priority.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["built", "building", "planned", "inactive"],
                        "description": "Build status.",
                    },
                    "notes": {"type": "string", "description": "Optional notes."},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_goal",
            "description": (
                "Create a new goal OR update existing goal if 'id' argument is provided. "
                "Requires confirmation. "
                "Use when user says 'přidej cíl našetřit 150 000 Kč do srpna 2027', "
                "'aktualizuj cíl X na 50 %', 'označ cíl za completed'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {
                        "type": "string",
                        "enum": [
                            "finance",
                            "school",
                            "work",
                            "wot",
                            "mff",
                            "personal",
                            "travel",
                            "fitness",
                            "hobby",
                        ],
                        "description": "Goal area / category.",
                    },
                    "title": {"type": "string", "description": "Short goal title."},
                    "id": {
                        "type": "integer",
                        "description": "Optional goal ID. If provided, will UPDATE the existing goal with this ID.",
                    },
                    "description": {"type": "string", "description": "Longer description."},
                    "status": {
                        "type": "string",
                        "enum": ["active", "in_progress", "completed", "paused", "cancelled"],
                        "description": "Goal status.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Priority.",
                    },
                    "progress": {
                        "type": "integer",
                        "description": "Progress percent 0-100 (inclusive).",
                    },
                    "target_date": {
                        "type": "string",
                        "description": "Target date in YYYY-MM-DD format.",
                    },
                },
                "required": ["area", "title"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": (
                "Prepare a LONG-TERM MEMORY to be saved. This is a WRITE tool — requires user confirmation. "
                "Use this ONLY when the user says something they clearly want remembered LONG-TERM, beyond the "
                "current chat. Examples: "
                "'Pamatuj si, že po VZ.55 chci CS linii' → area='wot', category='plan'. "
                "'Pamatuj, že preferuji krátké týdenní plány' → area='school', category='preference'. "
                "'Rozhodl jsem se jet na VŠE' → area='school', category='decision'. "
                "'Každou sobotu trénuju' → area='fitness', category='routine'. "
                "DO NOT use memory for NUMBERS/DATES/FACTS that belong to module tables (credits, XP, income, "
                "exam dates, goal progress) — those always go into the dedicated CRUD endpoints. "
                "Importance should be 1 (trivial note) to 10 (life-changing decision). Default is 5."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {
                        "type": "string",
                        "description": (
                            "Memory domain: 'general', 'wot', 'finance', 'school', 'work', 'mff', "
                            "'personal', 'fitness', 'hobby', 'travel'. Default 'general'."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "enum": ["preference", "decision", "context", "routine", "constraint", "plan"],
                        "description": (
                            "Memory category: "
                            "preference = uživatelovo přání / preference, "
                            "decision = přijaté rozhodnutí, "
                            "context = obecný dlouhodobý kontext, "
                            "routine = opakující se rutina / návyk, "
                            "constraint = omezení / hard limit, "
                            "plan = plán / cíl na úrovni intentu."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "The actual memory content — 1-3 sentences, clear, specific, actionable.",
                    },
                    "importance": {
                        "type": "integer",
                        "description": "1 (nevýznamné) to 10 (klíčové pro celý systém). Default 5.",
                    },
                    "active": {
                        "type": "boolean",
                        "description": "True = active and retrievable. Default True.",
                    },
                },
                "required": ["content"],
                "additionalProperties": False,
            },
        },
    },
]


TOOLS = READ_TOOLS + WRITE_TOOLS


READ_TOOL_FUNCTIONS = {
    "get_wot_resources": get_wot_resources,
    "get_wot_grinds": get_wot_grinds,
    "get_finance_summary": get_finance_summary,
    "get_finance_transactions": get_finance_transactions,
    "get_school_subjects": get_school_subjects,
    "get_school_assignments": get_school_assignments,
    "get_school_exams": get_school_exams,
    "get_work_summary": get_work_summary,
    "get_work_sessions": get_work_sessions,
    "get_mff_summary": get_mff_summary,
    "get_mff_characters": get_mff_characters,
    "get_goals_summary": get_goals_summary,
    "get_goals": get_goals,
    "get_memories": get_memories,
    "get_notifications": get_notifications,
    "get_notification_summary": get_notification_summary,
    "get_goal_progress_history": get_goal_progress_history,
}


WRITE_TOOL_FUNCTIONS = {
    "add_work_session": add_work_session,
    "add_finance_transaction": add_finance_transaction,
    "add_school_subject": add_school_subject,
    "add_school_assignment": add_school_assignment,
    "add_school_exam": add_school_exam,
    "update_wot_resource": update_wot_resource,
    "upsert_wot_grind": upsert_wot_grind,
    "upsert_mff_character": upsert_mff_character,
    "upsert_goal": upsert_goal,
    "save_memory": save_memory,
}


TOOL_FUNCTIONS = {**READ_TOOL_FUNCTIONS, **WRITE_TOOL_FUNCTIONS}


WRITE_TOOL_NAMES = set(WRITE_TOOL_FUNCTIONS.keys())


def _store_pending_action(db, tool: str, arguments: dict, *, ttl_minutes: int = 10) -> str:
    created = datetime.utcnow()
    expires = created + timedelta(minutes=ttl_minutes)
    pa = PendingAction(
        tool=tool,
        arguments=json.dumps(arguments, ensure_ascii=False),
        status="pending",
        created_at=created,
        expires_at=expires,
    )
    db.add(pa)
    db.flush()
    db.commit()
    return str(pa.id)


def _get_pending_action(db, pending_id: str) -> dict | None:
    try:
        pid = int(pending_id)
    except (ValueError, TypeError):
        return None
    pa = db.query(PendingAction).filter(PendingAction.id == pid).first()
    if pa is None:
        return None
    try:
        args = json.loads(pa.arguments) if pa.arguments else {}
    except Exception:
        args = {}
    return {
        "id": str(pa.id),
        "tool": pa.tool,
        "arguments": args,
        "status": pa.status,
        "created_at": pa.created_at,
        "expires_at": pa.expires_at,
    }


def _check_pending_expired(db) -> int:
    now = datetime.utcnow()
    stmt = (
        _sql_update(PendingAction)
        .where(PendingAction.status == "pending")
        .where(PendingAction.expires_at.is_not(None))
        .where(PendingAction.expires_at < now)
        .values(status="expired")
    )
    result = db.execute(stmt)
    affected = int(result.rowcount or 0)
    if affected:
        db.commit()
    return affected


def _confirm_pending_action_atomically(db, pending_id: str) -> dict | None:
    try:
        pid = int(pending_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Pending action not found")
    pa = db.query(PendingAction).filter(PendingAction.id == pid).first()
    if pa is None:
        raise HTTPException(status_code=404, detail="Pending action not found")
    if pa.status != "pending":
        raise HTTPException(status_code=409, detail="Pending already processed")
    stmt = (
        _sql_update(PendingAction)
        .where(PendingAction.id == pid)
        .where(PendingAction.status == "pending")
        .values(status="executing")
    )
    result = db.execute(stmt)
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Pending already processed")
    db.flush()
    db.refresh(pa)
    try:
        args = json.loads(pa.arguments) if pa.arguments else {}
    except Exception:
        args = {}
    return {
        "id": str(pa.id),
        "tool": pa.tool,
        "arguments": args,
        "status": pa.status,
        "created_at": pa.created_at,
        "expires_at": pa.expires_at,
    }


def _finalize_pending_status(db, pending_id: str, new_status: str):
    try:
        pid = int(pending_id)
    except (ValueError, TypeError):
        return
    pa = db.query(PendingAction).filter(PendingAction.id == pid).first()
    if pa:
        pa.status = new_status
        db.commit()


def reject_pending(db, pending_id: str):
    try:
        pid = int(pending_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Pending action not found")
    pa = db.query(PendingAction).filter(PendingAction.id == pid).first()
    if pa is None:
        raise HTTPException(status_code=404, detail="Pending action not found")
    if pa.status != "pending":
        raise HTTPException(status_code=409, detail="Pending already processed")
    pa.status = "rejected"
    db.commit()


def _message_to_dict(m):
    if isinstance(m, dict):
        return m
    return {"role": m.role, "content": m.content}


def _run_tool_calls(db, tool_calls):
    tool_messages = []
    pending_actions = []

    for tc in tool_calls:
        fn_name = tc.function.name
        print(f"[TOOL CALL] {fn_name}")

        try:
            arguments = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
            print(f"  [TOOL ERROR] invalid JSON args: {tc.function.arguments}")

        if fn_name in WRITE_TOOL_NAMES:
            action_id = _store_pending_action(db, fn_name, arguments, ttl_minutes=30)
            pending_info = _get_pending_action(db, action_id)
            expires_at_iso = (
                pending_info["expires_at"].isoformat()
                if pending_info and pending_info.get("expires_at")
                else None
            )
            pending_actions.append({
                "id": action_id,
                "tool": fn_name,
                "arguments": arguments,
                "expires_at": expires_at_iso,
            })

            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps({
                    "status": "confirmation_required",
                    "id": action_id,
                    "tool": fn_name,
                    "arguments": arguments,
                    "expires_at": expires_at_iso,
                }, ensure_ascii=False),
            })

            continue

        function = READ_TOOL_FUNCTIONS.get(fn_name)

        if function is None:
            result = {
                "error": "unknown_tool",
                "detail": f"Unknown tool: {fn_name}",
            }
        else:
            try:
                result = function()
            except Exception as exc:
                result = {
                    "error": "tool_execution_failed",
                    "detail": str(exc),
                }

        tool_messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(result, ensure_ascii=False, default=str),
        })

    return tool_messages, pending_actions


def _llm_create_with_retry(
    api_messages: list[dict],
    tools,
    tool_choice: str = "auto",
    temperature: float = 0.2,
    max_retries: int = 2,
):
    """Create chat completion with automatic retry on Groq rate limits (429).

    Groq free tier enforces 8 000 TPM. A Planner request with many read
    tools often triggers 429; the server usually suggests retrying after
    200-2000 ms, so we use a conservative 2.5 s backoff and one retry.
    Other API errors are re-raised as descriptive RuntimeError.
    """
    import openai as _openai

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=api_messages,
                tools=tools,
                tool_choice=tool_choice,
                temperature=temperature,
            )
        except _openai.RateLimitError as exc:
            last_exc = exc
            wait_s = 2.5
            try:
                body = getattr(exc, "response", None)
                if body is not None:
                    try:
                        data = body.json()
                        msg = (data or {}).get("error", {}).get("message", "")
                        m = __import__("re").search(
                            r"Please try again in ([0-9.]+)ms", msg
                        )
                        if m:
                            wait_s = max(0.5, min(5.0, float(m.group(1)) / 1000.0 + 0.3))
                    except Exception:
                        pass
            except Exception:
                pass
            if attempt < max_retries - 1:
                time.sleep(wait_s)
                continue
            raise RuntimeError(
                "AI provider nedisponuje (Rate limit 8 000 tokenů/minutu byl překročen). "
                "Zkus to prosím za 10-20 sekund znovu, nebo zjednoduš otázku."
            ) from last_exc
        except _openai.APIError as exc:
            last_exc = exc
            if attempt < max_retries - 1 and getattr(exc, "status_code", 500) >= 500:
                time.sleep(1.5)
                continue
            raise RuntimeError(
                f"AI provider vrátil chybu ({getattr(exc, 'status_code', '?')}). "
                f"Zkus to prosím později znovu."
            ) from last_exc
        except Exception as exc:
            last_exc = exc
            raise RuntimeError(
                f"Při volání AI došlo k chybě: {exc}"
            ) from last_exc
    raise RuntimeError("AI volání selhalo po několika pokusech.") from last_exc


def ask_ai(messages):
    db = SessionLocal()
    try:
        _check_pending_expired(db)

        api_messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            }
        ]

        for message in messages:
            api_messages.append(_message_to_dict(message))

        all_pending_actions = []
        MAX_TOOL_ROUNDS = 10

        for _ in range(MAX_TOOL_ROUNDS):
            response = _llm_create_with_retry(
                api_messages=api_messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
                max_retries=2,
            )

            choice = response.choices[0]
            assistant_msg = choice.message

            if not assistant_msg.tool_calls:
                return {
                    "answer": assistant_msg.content or "",
                    "pending_actions": all_pending_actions,
                }

            api_messages.append({
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_msg.tool_calls
                ],
            })

            tool_messages, pending_actions = _run_tool_calls(db, assistant_msg.tool_calls)
            all_pending_actions.extend(pending_actions)
            api_messages.extend(tool_messages)

        return {
            "answer": (
                "Nepodařilo se dokončit požadavek během několika pokusů. "
                "Zkus prosím otázku zjednodušit, nebo požádej o menší rozsah informací."
            ),
            "pending_actions": all_pending_actions,
        }
    finally:
        db.close()


def execute_confirm_action(action_id: str):
    """Actually execute a previously-confirmed WRITE tool call using its stored action_id."""
    db = SessionLocal()
    try:
        _check_pending_expired(db)

        try:
            stored = _confirm_pending_action_atomically(db, action_id)
        except HTTPException as he:
            try:
                log_activity(
                    db, "system", "error",
                    f"Potvrzení akce selhalo: action_id {action_id} - {he.detail}",
                    entity_type="PendingAction",
                    entity_id=abs(hash(action_id)) % (10**8),
                    user_context="ai_confirm"
                )
                db.commit()
            except Exception:
                pass
            if he.status_code == 409:
                return {
                    "ok": False,
                    "error": "action_already_processed",
                    "detail": (
                        "Akce byla už potvrzena, zamítnuta nebo vypršela. "
                        "Zopakujte prosím dotaz v chatu."
                    ),
                }
            return {
                "ok": False,
                "error": "action_not_found_or_expired",
                "detail": (
                    "Akce neexistuje, byla už potvrzena nebo vypršela "
                    "(časový limit 30 min). "
                    "Zopakujte prosím dotaz v chatu."
                ),
            }

        tool_name = stored.get("tool")
        arguments = stored.get("arguments") or {}

        if tool_name not in WRITE_TOOL_FUNCTIONS:
            _finalize_pending_status(db, action_id, "failed")
            try:
                log_activity(
                    db, "system", "error",
                    f"Neznámý write tool: {tool_name}",
                    entity_type="ToolRegistry",
                    entity_id=abs(hash(action_id)) % (10**8),
                    user_context="ai_confirm"
                )
                db.commit()
            except Exception:
                pass
            return {
                "ok": False,
                "error": "unknown_write_tool",
                "detail": f"Tool '{tool_name}' is not a known write tool requiring confirmation.",
            }

        fn = WRITE_TOOL_FUNCTIONS[tool_name]
        try:
            fn_args = dict(arguments)
            fn_args["user_context"] = "ai_confirm"
            try:
                import inspect
                sig = inspect.signature(fn)
                if "user_context" not in sig.parameters:
                    fn_args = dict(arguments)
            except Exception:
                fn_args = dict(arguments)
            result = fn(**fn_args)

            _finalize_pending_status(db, action_id, "executed")

            try:
                args_preview = ", ".join(f"{k}={v}" for k, v in list(arguments.items())[:3])
                if len(arguments) > 3:
                    args_preview += ", ..."
                summary = f"Potvrzena akce {tool_name} ({args_preview})"
                log_activity(
                    db, "ai", "approve", summary,
                    entity_type=tool_name,
                    entity_id=abs(hash(action_id)) % (10**8),
                    user_context="ai_confirm"
                )
                db.commit()
            except Exception:
                pass

            return {
                "ok": True,
                "tool": tool_name,
                "arguments": arguments,
                "result": result,
            }
        except Exception as exc:
            _finalize_pending_status(db, action_id, "failed")
            try:
                log_activity(
                    db, "ai", "reject",
                    f"Chyba při {tool_name}: {type(exc).__name__}: {str(exc)[:120]}",
                    entity_type=tool_name,
                    entity_id=abs(hash(action_id)) % (10**8),
                    user_context="ai_confirm"
                )
                db.commit()
            except Exception:
                pass
            return {
                "ok": False,
                "error": "execution_failed",
                "tool": tool_name,
                "arguments": arguments,
                "detail": str(exc),
            }
    finally:
        db.close()
