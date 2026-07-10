import { createSlice, createAsyncThunk } from "@reduxjs/toolkit";
import { apiClient } from "../api/apiClient";

// TODO: replace with your real auth/user context
const getUserId = () => "demo-user-123";

export const processChatInteraction = createAsyncThunk(
  "interaction/processChat",
  async ({ message }, { getState, rejectWithValue }) => {
    try {
      const state = getState().interaction;

      const response = await apiClient.post("/api/chats", {
        message,
        chat_history: state.chatMessages.map((m) => ({
          role: m.role,
          content: m.text,
        })),
        interaction_id: state.interactionId || null,
        user_id: getUserId(),
      });
      return response;
    } catch (error) {
      return rejectWithValue(
        error.response?.data?.detail || error.message
      );
    }
  }
);

const initialState = {
  interactionId: null, // <-- NEW: persists the draft across turns
  formValues: {
    hcp_name: "",
    interaction_type: "",
    interaction_date: "",
    interaction_time: "",
    attendees: [],
    materials_shared: [],
    samples_distributed: [],
    hcp_sentiment: "",
    outcomes: "",
    follow_up_actions: [],
  },
  chatMessages: [
    {
      role: "assistant",
      text: 'Log interaction details here (e.g., "Met Dr. Smith, discussed Product X efficacy, positive sentiment, shared brochure").',
    },
  ],
  isProcessing: false,
};

const interactionSlice = createSlice({
  name: "interaction",
  initialState,
  reducers: {
    addUserMessage: (state, action) => {
      state.chatMessages.push({
        role: "user",
        text: action.payload,
      });
    },
    updateFormFields: (state, action) => {
      state.formValues = {
        ...state.formValues,
        ...action.payload,
      };
    },
    // Call this when the user starts a brand-new interaction / clicks "New"
    resetInteraction: (state) => {
      state.interactionId = null;
      state.formValues = initialState.formValues;
      state.chatMessages = initialState.chatMessages;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(processChatInteraction.pending, (state) => {
        state.isProcessing = true;
      })
      .addCase(processChatInteraction.fulfilled, (state, action) => {
        state.isProcessing = false;

        if (action.payload.interaction_id) {
          state.interactionId = action.payload.interaction_id;
        }

        state.chatMessages.push({
          role: "assistant",
          text: action.payload.assistant_message,
        });

        // Backend already sends the full merged form_data (not a diff),
        // so just replace matching keys directly — no filtering.
        const incoming = action.payload.form_data || {};
        state.formValues = {
          ...state.formValues,
          ...incoming,
        };
      })
      .addCase(processChatInteraction.rejected, (state, action) => {
        state.isProcessing = false;
        state.chatMessages.push({
          role: "assistant",
          text: `Error: ${action.payload}`,
        });
      });
  },
});

export const { addUserMessage, updateFormFields, resetInteraction } =
  interactionSlice.actions;
export default interactionSlice.reducer;