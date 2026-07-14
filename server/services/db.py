import json
from typing import Optional, Dict, Any, List
from services.db_pool import query
from agent.index import INITIAL_FORM_DATA, InteractionFormData
from copy import deepcopy

REQUIRED_FIELDS = ["hcp_name", "interaction_type", "interaction_date", "interaction_time", "outcomes"]


def create_interaction(user_id: str) -> str:
    rows = query(
        "INSERT INTO public.interactions (user_id, status) VALUES (%s, 'draft') RETURNING id",
        [user_id],
    )
    return str(rows[0]["id"])


def get_interaction(interaction_id: str) -> Optional[dict]:
    rows = query("SELECT * FROM public.interactions WHERE id = %s", [interaction_id])
    return rows[0] if rows else None
def reset_interaction_form_data(interaction_id: str) -> None:
    fields = [
        "hcp_name", "interaction_type", "interaction_date", "interaction_time",
        "attendees", "materials_shared", "samples_distributed",
        "hcp_sentiment", "outcomes", "follow_up_actions",
    ]
    set_clauses = [f"{f} = NULL" for f in fields]
    set_clauses.append("updated_at = NOW()")
    query(f"UPDATE public.interactions SET {', '.join(set_clauses)} WHERE id = %s", [interaction_id]) 

def get_form_data_from_interaction(
    interaction_row: Optional[dict],
) -> InteractionFormData:
    """Convert a DB row into the complete agent form state."""

    form_data = deepcopy(INITIAL_FORM_DATA)

    if not interaction_row:
        return form_data

    form_data.update({
        "interaction_id": (
            str(interaction_row["id"])
            if interaction_row.get("id")
            else None
        ),
        "hcp_name": interaction_row.get("hcp_name"),
        "interaction_type": interaction_row.get("interaction_type"),
        "interaction_date": (
            interaction_row["interaction_date"].isoformat()
            if interaction_row.get("interaction_date")
            else None
        ),
        "interaction_time": (
            interaction_row["interaction_time"].strftime("%H:%M")
            if interaction_row.get("interaction_time")
            else None
        ),
        "attendees": interaction_row.get("attendees") or [],
        "materials_shared": interaction_row.get("materials_shared") or [],
        "samples_distributed": interaction_row.get("samples_distributed") or [],
        "hcp_sentiment": interaction_row.get("hcp_sentiment"),
        "outcomes": interaction_row.get("outcomes"),
        "follow_up_actions": interaction_row.get("follow_up_actions") or [],
        "validation_errors": [],
    })

    return form_data


def update_interaction_form_data(interaction_id: str, form_data: dict, status: Optional[str] = None) -> None:
    fields = [
        "hcp_name", "interaction_type", "interaction_date", "interaction_time",
        "attendees", "materials_shared", "samples_distributed",
        "hcp_sentiment", "outcomes", "follow_up_actions",
    ]
    set_clauses, params = [], []
    for f in fields:
        if f in form_data:
            set_clauses.append(f"{f} = %s")
            params.append(form_data[f])
    if status:
        set_clauses.append("status = %s")
        params.append(status)
    if not set_clauses:
        return
    set_clauses.append("updated_at = NOW()")
    params.append(interaction_id)
    query(f"UPDATE public.interactions SET {', '.join(set_clauses)} WHERE id = %s", params)


def insert_message(interaction_id: str, role: str, content: str) -> None:
    query(
        "INSERT INTO public.interaction_messages (interaction_id, role, content) VALUES (%s, %s, %s)",
        [interaction_id, role, content],
    )


def get_messages(interaction_id: str) -> List[dict]:
    return query(
        "SELECT role, content FROM public.interaction_messages WHERE interaction_id = %s ORDER BY created_at ASC",
        [interaction_id],
    )


def insert_audit_log(interaction_id: str, tool_name: str, previous_data: dict, new_data: dict) -> None:
    query(
        "INSERT INTO public.interaction_audit_logs (interaction_id, tool_name, previous_data, new_data) VALUES (%s, %s, %s, %s)",
        [interaction_id, tool_name, json.dumps(previous_data), json.dumps(new_data)],
    )

def reset_interaction_form_data(interaction_id: str) -> None:
    fields = [
        "hcp_name", "interaction_type", "interaction_date", "interaction_time",
        "attendees", "materials_shared", "samples_distributed",
        "hcp_sentiment", "outcomes", "follow_up_actions",
    ]
    set_clauses = [f"{f} = NULL" for f in fields]
    set_clauses.append("updated_at = NOW()")
    query(f"UPDATE public.interactions SET {', '.join(set_clauses)} WHERE id = %s", [interaction_id])