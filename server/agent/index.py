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



load_dotenv()
os.environ["GROQ_API_KEY"] = "GROQ_API_KEY"

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0.1
)



class InteractionFormData(TypedDict, total=False):
    interaction_id: Optional[str]
    hcp_name: Optional[str]
    interaction_type: Optional[str]
    interaction_date: Optional[str]
    interaction_time: Optional[str]
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

class FollowUpActionsResult(BaseModel):
    follow_up_actions: List[str] = Field(default_factory=list)
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
- If the user types "done", "Done", or similar, use validate_interaction_tool.
- Do not submit until validation passes.
- If validation fails, tell the user which required fields are missing.

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
- Use validate_interaction_tool when the user says done, Done, or asks if the
  form is complete/ready to submit.


Never directly output JSON to the user unless asked.
After a tool updates the form, briefly summarize what changed.
"""


# =========================================================
# HELPERS
# =========================================================

def merge_form_data(
    current: InteractionFormData,
    updates: Dict[str, Any]
) -> InteractionFormData:
    """
    Merge updates into current form data.
    Lists are replaced only when explicitly provided.
    """
    updated = dict(current or {})

    for key, value in updates.items():
        if value is not None:
            updated[key] = value

    return updated


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
    print("inside log_interaction_tool")
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
You update an existing HCP interaction form based on a correction message.

Current form data:
{current_form_data}

User correction message:
{message}

Extract only the fields that should change.

Rules:
- Do not return the full form.
- Return only fields explicitly corrected or updated by the user.
- Preserve all other existing fields.
- If the user says a value was wrong, replace only that field.
- Do NOT modify follow_up_actions here — that is handled by a different tool.
- interaction_type must be exactly one of: "Sync / Call", "Office Visit", "Conference / Event",
  "Email / Digital", "Group Meeting", "Sample Drop", "Other". Choose the closest match based
  on context (e.g. a phone call or virtual sync -> "Sync / Call"; an in-person meeting at the
  HCP's office -> "Office Visit").
- Return only valid JSON.
- Do not include markdown.

Example:
Current form:
{{
  "hcp_name": "Dr. Smith",
  "interaction_date": "2026-07-09",
  "hcp_sentiment": "positive",
  "materials_shared": ["brochures"]
}}

User correction:
Sorry, the name was actually Dr. John and the sentiment was negative.

Output:
{{
  "hcp_name": "Dr. John",
  "hcp_sentiment": "negative"
}}
"""


@tool
async def edit_interaction_tool(
    message: str,
    current_form_data: Dict[str, Any],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Use this tool when the user corrects or updates an existing scalar field
    (hcp_name, interaction_type, interaction_date, interaction_time, hcp_sentiment,
    outcomes, attendees, materials_shared, samples_distributed).
    Do NOT use this for follow_up_actions changes — use manage_follow_up_tool instead.
    The tool extracts only the changed fields.
    """
    print("inside edit_interaction_tool")
    prompt = EDIT_EXTRACTION_PROMPT.format(
        current_form_data=json.dumps(current_form_data, indent=2),
        message=message,
    )

    result = await llm.ainvoke(prompt)

    try:
        extracted_updates = json.loads(result.content)
        # Clear out validation errors since a field was updated
        extracted_updates["validation_errors"] = []
        print("extracted_updates:", extracted_updates)
        # extracted_updates = json.loads(result.content)
        # print("extracted_updates:", extracted_updates)
    except Exception:
        extracted_updates = {}

    return Command(
        update={
            "form_data": extracted_updates,
            "messages": [
                ToolMessage(
                    content=f"Updated fields: {json.dumps(extracted_updates)}",
                    tool_call_id=tool_call_id,
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


@tool
async def validate_interaction_tool(
    current_form_data: Dict[str, Any],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Use this tool when the user says done, Done, or asks if the form is
    complete / ready to submit.
    Validates required fields are not null or empty.
    """
    print("inside validate_interaction_tool")
    missing = []

    for field in REQUIRED_FIELDS:
        value = current_form_data.get(field)
        if value is None or value == "" or value == []:
            missing.append(field)

    validation_errors = [
        f"{field} is required" for field in missing
    ]

    return Command(
        update={
            "form_data": {
                **current_form_data,
                "validation_errors": validation_errors,
            },
            "messages": [
                ToolMessage(
                    content=(
                        "Validation passed. Form is ready to submit."
                        if not validation_errors
                        else f"Validation failed. Missing fields: {missing}. "
                             f"Please provide any further changes, or type done to submit."
                    ),
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


MANAGE_FOLLOWUP_PROMPT = """
Update an existing follow-up action list based on the user's instruction.

Current date:
{current_date}

Current follow-up actions:
{current_follow_ups}

User instruction:
{message}

Requirements:
- Preserve every existing action unless explicitly removed or replaced.
- ADD: append the new action.
- REMOVE: remove the matching action.
- REPLACE: remove the old action and append the replacement.
- A message may contain both ADD and REMOVE.
- Do not convert relative wording unless required.
- Preserve wording such as "next month", "next Tuesday", and "in two weeks".
- Return the full updated follow-up action list.
"""


@tool
async def manage_follow_up_tool(
    message: str,
    current_form_data: Dict[str, Any],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Add, remove or replace follow-up actions.
    """
    print("inside manage_follow_up_tool")

    current_date = datetime.now().strftime("%Y-%m-%d")

    current_follow_ups = list(
        current_form_data.get("follow_up_actions", []) or []
    )

    prompt = MANAGE_FOLLOWUP_PROMPT.format(
        current_date=current_date,
        current_follow_ups=json.dumps(current_follow_ups),
        message=message,
    )

    follow_up_llm = llm.with_structured_output(FollowUpActionsResult)
    try:
        result = await follow_up_llm.ainvoke(prompt)

        print("structured manage_follow_up_tool result:", result)

        updated_follow_ups = [
            item.strip()
            for item in result.follow_up_actions
            if item and item.strip()
        ]

    except Exception as exc:
        print("manage_follow_up_tool error:", repr(exc))
        updated_follow_ups = current_follow_ups

    updated_form_data = {
        **current_form_data,
        "follow_up_actions": updated_follow_ups,
        "validation_errors": [],
    }

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
    print("system_prompt: ", prompt)
    return prompt

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
        print("inside model node")

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
        print("inside tool_node")

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

            form_updates.update(current_tool_update)

            # Make later tools in the same turn see earlier tool updates.
            current_form = {
                **current_form,
                **current_tool_update,
            }

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

#     async def final_response(state: CustomAgentState):
#         """
#         Generate the human-facing response without exposing any tools.
#         This node cannot initiate another tool call.
#         """
#         print("inside final_response node")

#         final_prompt = """
# You are generating the final response after a form-management tool has
# already completed successfully.

# Use the tool result and current form data to briefly explain what changed.

# Do not call or request another tool.
# Do not output JSON.
# Do not claim that a change occurred unless it appears in the current form data.

# End with exactly:
# Please provide any further changes, or type done to submit.
# """

#         messages = [
#             SystemMessage(content=final_prompt),
#             *state["messages"],
#             SystemMessage(
#                 content=(
#                     "Current authoritative form data:\n"
#                     + json.dumps(
#                         state.get("form_data", {}),
#                         indent=2,
#                         default=str,
#                     )
#                 )
#             ),
#         ]

#         # Important: plain `llm`, not `llm_with_tools`.
#         result = await llm.ainvoke(messages)

#         return {
#             "messages": [result],
#         }

    graph.add_node("model", call_model)
    graph.add_node("tool_node", tool_node)
    # graph.add_node("final_response", final_response)

    graph.set_entry_point("model")

    graph.add_conditional_edges(
        "model",
        tools_router,
        {
            "tool_node": "tool_node",
            END: END,
        },
    )

    graph.add_edge("tool_node", "model")


    return graph.compile().with_config({"recursion_limit": 5})