from typing import Any, List, Dict, Optional, Literal, TypedDict
from typing_extensions import Annotated
from langchain.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langchain_core.messages import ToolMessage, AIMessage, SystemMessage
from langgraph.graph import MessagesState, StateGraph, START, END, add_messages
from langgraph.types import Command
from langchain_groq import ChatGroq
import os
import json
from datetime import datetime
import asyncio
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from copy import deepcopy
load_dotenv()

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0.1
)

class FollowUpActionsResult(BaseModel):
    follow_up_actions: List[str] = Field(default_factory=list)

class InteractionFormData(TypedDict, total=False):
    interaction_id: Optional[str]
    hcp_name: Optional[str]
    interaction_type: str
    interaction_date: str
    interaction_time: str
    attendees: List[str]
    materials_shared: List[str]
    samples_distributed: List[str]
    hcp_sentiment: Optional[Literal["positive", "neutral", "negative"]]
    outcomes: Optional[str]
    follow_up_actions: List[str]
    validation_errors: List[str]

class CustomAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    form_data: InteractionFormData
    validation_failed: bool



INITIAL_FORM_DATA: InteractionFormData = {
    "interaction_id": None,
    "hcp_name": None,
    "interaction_type": None,
    "interaction_date": None,
    "interaction_time": None,
    "attendees": [],
    "materials_shared": [],
    "samples_distributed": [],
    "hcp_sentiment": None,
    "outcomes": None,
    "follow_up_actions": [],
    "validation_errors": [],
}


# =========================================================
# BASE PROMPT
# =========================================================
now = datetime.now()
current_date = now.strftime("%Y-%m-%d")
current_time = now.strftime("%H:%M")

BASE_SYSTEM_PROMPT = f"""
You are an AI assistant that controls an HCP interaction form.

The user must NOT manually fill the form.
All form updates must happen through tool calls.

Current date: {current_date}
Current time: {current_time}

Responsibilities:
1. Understand the user's natural language input.
2. Select the correct tool.
3. Extract structured form data.
4. Update only fields the user mentioned or fields required by date/time default rules.
5. Preserve existing values unless the user explicitly corrects them.
6. Never invent missing information except date/time defaults described below.

Date/time default rules:
- If the user provides no date and no time, set:
  - interaction_date = current date
  - interaction_time = current time
- If the user provides a date but no time, set:
  - interaction_date = provided date
  - interaction_time = current time
- If the user provides a time but no date, set:
  - interaction_date = current date
  - interaction_time = provided time
- Convert relative dates like today/tomorrow/yesterday using the current date.

Completion flow:
- After every final assistant response that updates or summarizes the form, ask:
  "Please provide any further changes, or type done to submit."
- If the user types "done", "Done", or similar:
  - FIRST, check if the most recent message in the history is a failed validation tool execution.
  - If validation has ALREADY failed in the immediate previous step, DO NOT call the validation tool again. Instead, write a natural language response explaining to the user what fields are missing and ask them to provide them.
  - If validation has NOT been run yet for this "done" request, go ahead and call `validate_interaction_tool`.
- Do not submit until validation passes.

Tool usage rules:
- Use log_interaction_tool when the user describes a new interaction for the first time.
- Use edit_interaction_tool when the user corrects or changes an existing scalar field
  (e.g. hcp_name, interaction_type, interaction_date, interaction_time, hcp_sentiment, outcomes).
- Use manage_follow_up_tool when the user wants to add, remove, or change a
  follow_up_actions item specifically (e.g. "also remind me to...", "remove the
  reconnect follow-up", "change the follow-up to next Friday instead").
  Do NOT use edit_interaction_tool for follow-up list changes.
- Use reset_form_tool ONLY when the user clearly wants to discard the entire
  interaction and start completely over (e.g. "start over", "scrap this",
  "clear the whole form", "reset everything"). Never use it for clearing a
  single field.
- Use validate_interaction_tool when the user says "done", "Done", or asks if the form is complete/ready to submit. 
- CRITICAL: If the tool returns a validation failed/error message, stop calling tools. Directly show that error message to the user as a natural language response and ask them to provide the missing information (e.g., "Please provide the interaction_time to proceed")

Never directly output JSON to the user unless asked.
After a tool updates the form, briefly summarize what changed.
"""
def format_chat_history(chat_history: List[Dict[str, str]]) -> str:
    """
    Format chat history into a readable string for the system prompt
    """
    print("inside format_chat_history")
    if not chat_history:
        return ""

    formatted_messages = []
    for msg in chat_history:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        role_lable = "User Message" if role.lower() == "user" else "AI Messaage"
        formatted_messages.append(f"{role_lable}: {content}")

    # print("formatted_messages:", "\n\n".join(formatted_messages))
    return "\n\n".join(formatted_messages)

def get_system_prompt(chat_history: Optional[List[Dict[str, str]]] = None) -> str:
    """
    Get the system prompt for the RAG agent, optionally including chat history.
    """
    prompt = BASE_SYSTEM_PROMPT
    if chat_history:
        formatted_history = format_chat_history(chat_history)
        if formatted_history:
            prompt += "\n\n### Previous Conversation Context\n"
            prompt += "The following is the recent conversation history for context: \n\n"
            prompt += formatted_history
            prompt += "\n\nUse this conversation history to understand context and references in the current question."
    # print("system_prompt: ", prompt)
    return prompt



EXTRACTION_PROMPT = """
You extract structured HCP interaction form data from a natural language message.

Current date: {current_date}
Current time: {current_time}

User message:
{message}

Extract only information clearly present in the message, except apply date/time defaults.

Allowed fields:
- hcp_name
- interaction_type
- interaction_date
- interaction_time
- attendees
- materials_shared
- samples_distributed
- hcp_sentiment
- outcomes
- follow_up_actions

Date/time rules:
- If no date and no time are provided, use current date and current time.
- If date is provided but time is missing, use current time.
- If time is provided but date is missing, use current date.
- Convert "today" to current date.
- Convert "tomorrow" to next date.
- Use YYYY-MM-DD for date.
- Use HH:MM 24-hour format for time.

Other rules:
- hcp_sentiment must be one of: positive, neutral, negative.
- interaction_type must be exactly one of: "Sync / Call", "Office Visit", "Conference / Event",
  "Email / Digital", "Group Meeting", "Sample Drop", "Other". Choose the closest match.
- materials_shared / samples_distributed are things ALREADY given or shown DURING this
  interaction (past tense — e.g. "shared brochures", "gave 10 samples").
- follow_up_actions are things planned for the FUTURE, after this interaction
  (e.g. "agreed to reconnect in two weeks", "will send the dosage guide next week",
  "follow-up: ..."). Do NOT put future/promised actions into materials_shared —
  they belong in follow_up_actions even if the sentence uses a word like "send".
- If a message lists multiple distinct follow-up actions (e.g. separated by "and" or
  commas), extract ALL of them as separate items in the follow_up_actions list —
  do not merge them into one string or drop any of them.
- materials_shared, samples_distributed, attendees, and follow_up_actions must be lists.
- Return only valid JSON.
- Do not include markdown.

Example:
User message: Today I met with Dr. Smith and discussed product X efficiency. Sentiment was
positive, I shared brochures, and we agreed to reconnect in two weeks and I'll send the
updated dosage guide next week.

Output:
{{
  "hcp_name": "Dr. Smith",
  "interaction_date": "{current_date}",
  "hcp_sentiment": "positive",
  "materials_shared": ["brochures"],
  "outcomes": "Discussed product X efficiency",
  "follow_up_actions": ["Reconnect in two weeks", "Send updated dosage guide next week"]
}}
"""


@tool
async def log_interaction_tool(
    message: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Use this tool when the user describes a new HCP interaction.
    Input should be the user's raw natural language message.
    The tool extracts form fields and updates the form state.
    """
    print("*"*20," inside log_interaction_tool","*"*20)
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")

    prompt = EXTRACTION_PROMPT.format(
        current_date=current_date,
        current_time=current_time,
        message=message,
    )

    result = await llm.ainvoke(prompt)

    try:
        extracted_data = json.loads(result.content)
        # Clear out validation errors since we just added new data
        extracted_data["validation_errors"] = [] 
        print("extracted_Data:", extracted_data)
        # extracted_data = json.loads(result.content)
        # print("extracted_Data:", extracted_data)
    except Exception:
        extracted_data = {}

    return Command(
        update={
            "form_data": extracted_data,
            "messages": [
                ToolMessage(
                    content=f"Extracted interaction details: {json.dumps(extracted_data)}",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )

EDIT_EXTRACTION_PROMPT = """
You update an existing HCP interaction form based on a correction, addition, deletion, or reset message.

Current form data:
{current_form_data}

User correction message:
{message}

Extract only the fields that should change.

Rules for Updates & Additions:
- Do not return the full form.
- Return only fields explicitly corrected, added, updated, or removed by the user.
- If the user provides a value for a field that is currently missing, empty, or null, extract it anyway.
- Use HH:MM 24-hour format for time updates (e.g., "10 am" -> "10:00", "2:30 pm" -> "14:30").
- interaction_type must be exactly one of: "Sync / Call", "Office Visit", "Conference / Event", "Email / Digital", "Group Meeting", "Sample Drop", "Other".

Rules for Removal, Deletions, & Clears:
- If the user asks to clear, remove, or delete a scalar field (like interaction_time, hcp_name, outcomes, hcp_sentiment, etc.), set that field's value to null.
- If the user asks to clear list fields (like attendees, materials_shared, samples_distributed), set that field's value to [].
- Do NOT modify follow_up_actions here under any circumstances.

Return ONLY valid JSON. Do not include markdown formatting or backticks.

Example 1 (Addition):
Current form:
{{
  "hcp_name": "Dr. Smith",
  "interaction_date": "2026-07-09"
}}
User correction: "set the time to 10 am"
Output:
{{
  "interaction_time": "10:00"
}}

Example 2 (Removal/Reset):
Current form:
{{
  "hcp_name": "Dr. Smith",
  "interaction_date": "2026-07-09",
  "interaction_time": "14:30"
}}
User correction: "remove the time and clear attendees"
Output:
{{
  "interaction_time": null,
  "attendees": []
}}
"""


EDITABLE_FIELDS = {
    "hcp_name",
    "interaction_type",
    "interaction_date",
    "interaction_time",
    "attendees",
    "materials_shared",
    "samples_distributed",
    "hcp_sentiment",
    "outcomes",
}

@tool
async def edit_interaction_tool(
    message: str,
    current_form_data: Dict[str, Any],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Use this tool when the user corrects, fills, removes, or clears an existing
    interaction field, excluding follow_up_actions.
    """
    print("inside edit_interaction_tool")

    prompt = EDIT_EXTRACTION_PROMPT.format(
        current_form_data=json.dumps(
            current_form_data,
            indent=2,
            default=str,
        ),
        message=message,
    )

    try:
        result = await llm.ainvoke(prompt)
        parsed_updates = json.loads(result.content)

        if not isinstance(parsed_updates, dict):
            raise ValueError("Edit extraction result must be a JSON object")

        extracted_updates = {
            key: value
            for key, value in parsed_updates.items()
            if key in EDITABLE_FIELDS
        }

    except Exception as exc:
        print("edit_interaction_tool error:", repr(exc))
        extracted_updates = {}

    updated_form = dict(current_form_data or {})
    updated_form.update(extracted_updates)
    updated_form["validation_errors"] = []

    return Command(
        update={
            "form_data": updated_form,
            "messages": [
                ToolMessage(
                    content=(
                        f"Updated fields: {json.dumps(extracted_updates)}"
                        if extracted_updates
                        else "No valid form updates were identified."
                    ),
                    tool_call_id=tool_call_id,
                    name="edit_interaction_tool",
                )
            ],
        }
    )


@tool
async def reset_form_tool(
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Use this tool ONLY when the user explicitly wants to discard the entire
    current interaction and start completely over — e.g. "start over",
    "scrap this", "clear the whole form", "reset everything", "let's redo
    this from scratch".

    Do NOT use this tool if the user only wants to clear or correct a single
    field (e.g. "remove the time", "the sentiment was wrong") — use
    edit_interaction_tool for that instead.
    """
    print("inside reset_form_tool")

    empty_form: InteractionFormData = {
        "interaction_id": None,
        "hcp_name": None,
        "interaction_type": None,
        "interaction_date": None,
        "interaction_time": None,
        "attendees": [],
        "materials_shared": [],
        "samples_distributed": [],
        "hcp_sentiment": None,
        "outcomes": None,
        "follow_up_actions": [],
        "validation_errors": [],
    }

    return Command(
        update={
            "form_data": empty_form,
            "messages": [
                ToolMessage(
                    content="The form has been reset. All fields are now empty. What would you like to log?",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )

MANAGE_FOLLOWUP_PROMPT = """
You are a precise data assistant tasked with updating a list of future follow-up actions for an HCP interaction form based on user instructions.

Current date:
{current_date}

Current follow-up actions list:
{current_follow_ups}

User instruction:
{message}

Requirements:
- Preserve every existing action in the list unless the user explicitly asks to remove or replace it.
- ADD: If the user adds a new task, append it to the list.
- REMOVE: If the user cancels or removes a task, remove it from the list.
- REPLACE: If the user updates an action, swap the old version for the new one.
- A single message might contain both additions and removals.
- Do not compute relative dates into static absolute dates unless requested. Preserve phrases like "next month", "next Tuesday", and "in two weeks".

CRITICAL: You must return a valid JSON object matching the requested schema. It must contain the key "follow_up_actions" mapping to a list of strings.
"""

@tool
async def manage_follow_up_tool(
    message: str,
    current_form_data: Dict[str, Any],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Add, remove, or replace follow-up actions inside the follow_up_actions list.
    """
    print("inside manage_follow_up_tool")

    # Guard against missing or null form data state
    current_form = dict(current_form_data or {})
    current_date = datetime.now().strftime("%Y-%m-%d")

    # Safely retrieve and copy the existing array
    current_follow_ups = list(current_form.get("follow_up_actions", []) or [])

    prompt = MANAGE_FOLLOWUP_PROMPT.format(
        current_date=current_date,
        current_follow_ups=json.dumps(current_follow_ups),
        message=message,
    )

    follow_up_llm = llm.with_structured_output(FollowUpActionsResult)
    
    try:
        result = await follow_up_llm.ainvoke(prompt)
        print("structured manage_follow_up_tool result:", result)

        # Access via the Pydantic model's field property safely
        updated_follow_ups = [
            item.strip()
            for item in result.follow_up_actions
            if item and item.strip()
        ]
    except Exception as exc:
        print("manage_follow_up_tool parsing error:", repr(exc))
        # If the LLM errors or hallucinates formatting, fall back safely to old actions
        updated_follow_ups = current_follow_ups

    # Merge cleanly back into the full form context
    updated_form_data = dict(current_form)
    updated_form_data["follow_up_actions"] = updated_follow_ups
    updated_form_data["validation_errors"] = []

    return Command(
        update={
            "form_data": updated_form_data,
            "messages": [
                ToolMessage(
                    content=(
                        "Follow-up actions updated successfully: "
                        f"{json.dumps(updated_follow_ups)}"
                    ),
                    tool_call_id=tool_call_id,
                    name="manage_follow_up_tool",
                )
            ],
        }
    )

REQUIRED_FIELDS = [
    "hcp_name",
    "interaction_type",
    "interaction_date",
    "interaction_time",
    # "outcomes",
]

@tool
async def validate_interaction_tool(
    current_form_data: Dict[str, Any],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Validate required interaction fields.
    """
    print("inside validate_interaction_tool")

    missing = [
        field
        for field in REQUIRED_FIELDS
        if current_form_data.get(field) in (None, "", [])
    ]

    validation_errors = [
        f"{field} is required"
        for field in missing
    ]

    validation_failed = bool(validation_errors)

    return Command(
        update={
            "form_data": {
                **current_form_data,
                "validation_errors": validation_errors,
            },
            "validation_failed": validation_failed,
            "messages": [
                ToolMessage(
                    content=(
                        "Validation passed. Form is ready to submit."
                        if not validation_failed
                        else (
                            "Validation failed. "
                            f"Missing required fields: {', '.join(missing)}."
                        )
                    ),
                    tool_call_id=tool_call_id,
                    name="validate_interaction_tool",
                )
            ],
        }
    )

async def validation_response(state: CustomAgentState):
    validation_errors = (
        state.get("form_data", {}).get("validation_errors", [])
    )

    missing_fields = [
        error.replace(" is required", "")
        for error in validation_errors
    ]

    readable_fields = [
        field.replace("_", " ")
        for field in missing_fields
    ]

    if len(readable_fields) == 1:
        content = (
            f"The {readable_fields[0]} is required. "
            f"Please provide the {readable_fields[0]} to continue."
        )
    else:
        content = (
            "The following fields are required: "
            f"{', '.join(readable_fields)}. "
            "Please provide them to continue."
        )

    return {
        "messages": [
            AIMessage(content=content)
        ]
    }

def create_simple_custom_agent(
    chat_history: Optional[List[Dict[str, str]]] = None
):
    tools = [
        edit_interaction_tool,
        log_interaction_tool,
        validate_interaction_tool,
        reset_form_tool,
        manage_follow_up_tool,
    ]

    system_prompt = get_system_prompt(chat_history=chat_history)

    # Used only for deciding which tool to call.
    llm_with_tools = llm.bind_tools(tools=tools)

    graph = StateGraph(CustomAgentState)

    async def call_model(state: CustomAgentState):
        print("*"*20,"inside model node","*"*20)

        messages = [
            SystemMessage(content=system_prompt),
            *state["messages"],
        ]

        result = await llm_with_tools.ainvoke(messages)
        print("model node result:", result)
        return {
            "messages": [result],
        }
    async def tools_router(state: CustomAgentState):
        last_message = state["messages"][-1]

        # If the model node just generated tool_calls, go to tool_node
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tool_node"

        # If it's a normal text response (no tool calls), STOP and wait for the user
        return END

    async def tool_node(state: CustomAgentState):
        print("*"*20,"inside tool_node","*"*20)
        print("current_form: ", state.get("form_data"))
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", []) or []

        tool_messages = []
        form_updates: Dict[str, Any] = {}

        tool_map = {
            "log_interaction_tool": log_interaction_tool,
            "edit_interaction_tool": edit_interaction_tool,
            "reset_form_tool": reset_form_tool,
            "manage_follow_up_tool": manage_follow_up_tool,
            "validate_interaction_tool": validate_interaction_tool,
        }

        current_form = dict(state.get("form_data", {}) or {})

        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            tool_id = tool_call.get("id") or tool_call.get("tool_call_id")

            if tool_name not in tool_map:
                continue

            # Copy the arguments. Do not mutate the AIMessage's tool-call data.
            tool_args = dict(tool_call.get("args", {}) or {})

            if tool_name in {
                "edit_interaction_tool",
                "validate_interaction_tool",
                "manage_follow_up_tool",
            }:
                tool_args["current_form_data"] = current_form

            command = await tool_map[tool_name].ainvoke(
                {
                    "args": tool_args,
                    "name": tool_name,
                    "type": "tool_call",
                    "id": tool_id,
                }
            )

            update = command.update if hasattr(command, "update") else command

            tool_messages.extend(update.get("messages", []))

            current_tool_update = update.get("form_data", {}) or {}
            print("current_tool_update: ", json.dumps(current_tool_update, indent=2, default=str))

            form_updates.update(current_tool_update)

            # Make later tools in the same turn see earlier tool updates.
            current_form = {
                **current_form,
                **current_tool_update,
            }
            print("current_form with tool updates: ", json.dumps(current_form, indent=2, default=str))

        merged_form = {
            **state.get("form_data", {}),
            **form_updates,
        }

        print("tool_node merged_form:", json.dumps(
            merged_form,
            indent=2,
            default=str,
        ))

        return {
            "messages": tool_messages,
            "form_data": merged_form,
        }
    
    async def after_tool_router(state: CustomAgentState):
        if state.get("validation_failed", False):
            return "validation_response"

        return "model"

    graph.add_node("model", call_model)
    graph.add_node("tool_node", tool_node)
    graph.add_node("validation_response", validation_response)
    

    graph.set_entry_point("model")

    graph.add_conditional_edges(
        "model",
        tools_router,
        {
            "tool_node": "tool_node",
            END: END,
        },
    )

    # graph.add_edge("tool_node", "model")

    graph.add_conditional_edges(
        "tool_node",
        after_tool_router,
        {
            "validation_response": "validation_response",
            "model": "model",
        },
    )

    graph.add_edge("validation_response", END)


    return graph.compile().with_config({"recursion_limit": 15})