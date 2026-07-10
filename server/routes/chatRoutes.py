from typing import List, Dict, Optional, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from agent.index import create_simple_custom_agent
from services.db import (
    create_interaction,
    get_interaction,
    get_form_data_from_interaction,
    update_interaction_form_data,
    insert_message,
    insert_audit_log,
    REQUIRED_FIELDS,
    reset_interaction_form_data,
    get_messages
)
import json
router = APIRouter(tags=["chatRoutes"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    chat_history: Optional[List[ChatMessage]] = []
    interaction_id: Optional[str] = None   # <-- NEW: client carries this across turns
    user_id: str = Field(..., min_length=1)  # <-- NEW: needed to create a row


class ChatResponse(BaseModel):
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



@router.post("/")
@router.post("")
async def send_message(request: ChatRequest):
    try:
        interaction_id = request.interaction_id
        if not interaction_id:
            interaction_id = create_interaction(request.user_id)

        interaction_row = get_interaction(interaction_id)
        previous_form_data = get_form_data_from_interaction(interaction_row)
        chat_history = get_messages(interaction_id)

        insert_message(interaction_id, "user", request.message)

        agent = create_simple_custom_agent(chat_history=chat_history)

        result = await agent.ainvoke({
            "messages": [{"role": "user", "content": request.message}],
            "form_data": previous_form_data,
        })

        messages = result.get("messages", [])
        updated_form_data = result.get("form_data", {})

        assistant_message = ""
        for msg in reversed(messages):
            if msg.__class__.__name__ == "AIMessage" and msg.content:
                assistant_message = msg.content
                break

        if assistant_message:
            insert_message(interaction_id, "assistant", assistant_message)

        # --- Detect whether reset_form_tool was invoked this turn ---
        was_reset = any(
            getattr(msg, "name", None) == "reset_form_tool"
            or (
                hasattr(msg, "tool_calls")
                and any(tc.get("name") == "reset_form_tool" for tc in (msg.tool_calls or []))
            )
            for msg in messages
        )

        is_done_turn = request.message.strip().lower() == "done"
        validation_errors = updated_form_data.get("validation_errors", [])
        submitted = is_done_turn and not validation_errors

        if was_reset:
            reset_interaction_form_data(interaction_id)
        else:
            update_interaction_form_data(
                interaction_id,
                updated_form_data,
                status="submitted" if submitted else None,
            )

        if not was_reset and updated_form_data != previous_form_data:
            insert_audit_log(
                interaction_id,
                tool_name="log_interaction_tool/edit_interaction_tool",
                previous_data=previous_form_data,
                new_data=updated_form_data,
            )
        elif was_reset:
            insert_audit_log(
                interaction_id,
                tool_name="reset_form_tool",
                previous_data=previous_form_data,
                new_data={},
            )

        print("=== FINAL RESPONSE DEBUG ===")
        print("updated_form_data:", json.dumps(updated_form_data, indent=2, default=str))
        print("============================")

        return {
            "assistant_message": assistant_message,
            "form_data": updated_form_data,
            "messages": [serialize_message(msg) for msg in messages],
            "interaction_id": interaction_id,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An internal server error occurred while creating message: {str(e)}",
        )