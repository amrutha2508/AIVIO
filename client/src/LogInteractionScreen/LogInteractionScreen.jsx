import "./LogInteractionScreen.css";
import ChatbotPanel from "../components/chatbotPanel";
import FormPanel from "../components/formPanel";

export default function LogInteractionScreen() {
  return (
    <div className="screen">
      <div className="panel">
        <FormPanel />
      </div>

      <div className="panel">
        <ChatbotPanel />
      </div>
    </div>
  );
}