from typing import List, Dict, Optional, Any
from fastapi import APIRouter, HTTPException, Header
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from agent.index import create_simple_custom_agent
from services.db import (
    create_interaction,
    get_interaction,
    get_form_data_from_interaction,
    update_interaction_form_data,
    insert_message,
    get_messages,
    insert_audit_log,
    REQUIRED_FIELDS,
)

router = APIRouter(tags=["chatRoutes"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    interaction_id: Optional[str] = None  # omit/None => new session (e.g. after page refresh)


class ChatResponse(BaseModel):
    interaction_id: str
    assistant_message: str
    form_data: Dict[str, Any]
    messages: List[Dict[str, Any]]


def serialize_message(msg):
    return {
        "type": msg.__class__.__name__,
        "role": getattr(msg, "type", None),
        "content": getattr(msg, "content", ""),
        "tool_calls": getattr(msg, "tool_calls", None),
    }


@router.post("/", response_model=ChatResponse)
@router.post("", response_model=ChatResponse)
async def send_message(request: ChatRequest, x_user_id: str = "1"):
    try:
        # 1. Resolve the session. No id (fresh page load) or an unknown id -> start a new draft row.
        interaction_id = request.interaction_id
        interaction_row = get_interaction(interaction_id) if interaction_id else None
        if interaction_row is None:
            interaction_id = create_interaction(user_id=x_user_id)

        # 2. Load persisted state from Postgres -- this is the fix for your original bug:
        #    form_data now survives across requests because it lives in the DB, not in memory.
        previous_form_data = get_form_data_from_interaction(interaction_row)
        chat_history = [{"role": m["role"], "content": m["content"]} for m in get_messages(interaction_id)]

        # 3. Persist the incoming user message
        insert_message(interaction_id, "user", request.message)

        # 4. Run the agent, seeding it with the DB-backed form_data
        agent = create_simple_custom_agent(chat_history=chat_history)
        result = await agent.ainvoke({
            "messages": [HumanMessage(content=request.message)],
            "form_data": previous_form_data,
        })

        messages = result.get("messages", [])
        updated_form_data = result.get("form_data", {})

        # 5. Persist form_data + audit trail if anything changed
        tool_names_used = [
            tc["name"]
            for msg in messages
            if getattr(msg, "tool_calls", None)
            for tc in msg.tool_calls
        ]
        if updated_form_data != previous_form_data:
            missing = [f for f in REQUIRED_FIELDS if not updated_form_data.get(f)]
            status = "submitted" if ("validate_interaction_tool" in tool_names_used and not missing) else None
            update_interaction_form_data(interaction_id, updated_form_data, status=status)
            for tool_name in tool_names_used:
                insert_audit_log(interaction_id, tool_name, previous_form_data, updated_form_data)

        # 6. Persist assistant/tool turns
        assistant_message = ""
        for msg in messages:
            cls = msg.__class__.__name__
            if cls == "ToolMessage":
                insert_message(interaction_id, "tool", msg.content or "")
            elif cls == "AIMessage" and msg.content:
                insert_message(interaction_id, "assistant", msg.content)
                assistant_message = msg.content

        return {
            "interaction_id": interaction_id,
            "assistant_message": assistant_message,
            "form_data": updated_form_data,
            "messages": [serialize_message(msg) for msg in messages],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An internal server error occurred while creating message: {str(e)}"
        )