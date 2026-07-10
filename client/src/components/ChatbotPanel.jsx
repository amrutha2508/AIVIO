import { useRef, useEffect, useState } from "react";
import { Send, Bot } from "lucide-react";
import { useDispatch, useSelector } from "react-redux";
import {
  addUserMessage,
  processChatInteraction,
} from "../redux/interactionSlice";
import "../LogInteractionScreen/LogInteractionScreen.css";

export default function ChatbotPanel() {
  const [input, setInput] = useState("");
  const scrollRef = useRef(null);

  const dispatch = useDispatch();
  const { chatMessages, isProcessing } = useSelector(
    (state) => state.interaction
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
    });
  }, [chatMessages]);

  const handleSend = async () => {
    if (!input.trim() || isProcessing) return;

    const messageText = input;

    dispatch(addUserMessage(messageText));
    setInput("");

    dispatch(processChatInteraction({ message: messageText }));
  };

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <Bot size={20} color="#2563eb" />
        <div>
          <div className="chat-header-title">AI Assistant</div>
          <div className="chat-header-subtitle">
            Log interaction details here via chat
          </div>
        </div>
      </div>

      <div ref={scrollRef} className="chat-messages">
        {chatMessages.map((m, i) => (
          <div key={i} className={`message ${m.role}`}>
            {m.text}
          </div>
        ))}

        {isProcessing && (
          <div className="message assistant">
            Processing...
          </div>
        )}
      </div>

      <div className="chat-input-bar">
        <div className="chat-input-wrapper">
          <textarea
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Describe interaction..."
          />

          <button
            className="send-btn"
            onClick={handleSend}
            disabled={isProcessing}
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}