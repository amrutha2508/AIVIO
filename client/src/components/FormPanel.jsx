import { useSelector, useDispatch } from "react-redux";
import { updateFormFields } from "../redux/interactionSlice"; // adjust path
import "../LogInteractionScreen/LogInteractionScreen.css";

const INTERACTION_TYPES = [
  "Sync / Call",
  "Office Visit",
  "Conference / Event",
  "Email / Digital",
  "Group Meeting",
  "Sample Drop",
  "Other",
];

const SENTIMENTS = [
  { value: "positive", label: "Positive", color: "#2e7d32" },
  { value: "neutral", label: "Neutral", color: "#f9a825" },
  { value: "negative", label: "Negative", color: "#c62828" },
];

export default function FormPanel() {
  const dispatch = useDispatch();
  const formValues = useSelector((state) => state.interaction.formValues);

  const handleChange = (field, value) => {
    dispatch(updateFormFields({ [field]: value }));
  };

  return (
    <div className="form-panel">
      <h1 className="form-title">Log HCP Interaction</h1>
      <div className="form-sections">
        <div>
          <h2 className="section-heading">Interaction Details</h2>
          <div className="field-grid two-col">
            <FieldPlaceholder
              label="HCP Name"
              value={formValues.hcp_name}
              onChange={(v) => handleChange("hcp_name", v)}
            />

            <DropdownField
              label="Interaction Type"
              value={formValues.interaction_type}
              options={INTERACTION_TYPES}
              onChange={(v) => handleChange("interaction_type", v)}
            />

            <DateField
              label="Date"
              value={formValues.interaction_date} // YYYY-MM-DD
              onChange={(v) => handleChange("interaction_date", v)}
            />

            <TimeField
              label="Time"
              value={formValues.interaction_time} // HH:MM (24hr)
              onChange={(v) => handleChange("interaction_time", v)}
            />
          </div>

          <div className="field-grid one-col">
            <FieldPlaceholder
              label="Attendees"
              value={formValues.attendees?.join(", ")}
              onChange={(v) =>
                handleChange(
                  "attendees",
                  v.split(",").map((s) => s.trim()).filter(Boolean)
                )
              }
            />
          </div>

          <h2 className="section-heading">
            Materials Shared / Samples Distributed
          </h2>
          <div className="field-grid one-col">
            <FieldPlaceholder
              label="Materials Shared"
              value={formValues.materials_shared?.join(", ")}
              onChange={(v) =>
                handleChange(
                  "materials_shared",
                  v.split(",").map((s) => s.trim()).filter(Boolean)
                )
              }
            />
            <FieldPlaceholder
              label="Samples Distributed"
              value={formValues.samples_distributed?.join(", ")}
              onChange={(v) =>
                handleChange(
                  "samples_distributed",
                  v.split(",").map((s) => s.trim()).filter(Boolean)
                )
              }
            />
          </div>

          <div className="field-grid one-col">
            <SentimentField
              label="Observed/Inferred HCP Sentiment"
              value={formValues.hcp_sentiment}
              onChange={(v) => handleChange("hcp_sentiment", v)}
            />
            <FieldPlaceholder
              label="Outcomes"
              value={formValues.outcomes}
              tall
              onChange={(v) => handleChange("outcomes", v)}
            />
            <FieldPlaceholder
              label="Follow-up Actions"
              value={formValues.follow_up_actions?.join(", ")}
              tall
              onChange={(v) =>
                handleChange(
                  "follow_up_actions",
                  v.split(",").map((s) => s.trim()).filter(Boolean)
                )
              }
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function FieldPlaceholder({ label, value = "", tall, onChange }) {
  const displayValue = Array.isArray(value) ? value.join(", ") : value || "";
  return (
    <div className="field">
      <label className="field-label">{label}</label>
      {tall ? (
        <textarea
          rows={4}
          value={displayValue}
          style={{ color: "#000" }}
          onChange={(e) => onChange?.(e.target.value)}
        />
      ) : (
        <input
          type="text"
          value={displayValue}
          style={{ color: "#000" }}
          onChange={(e) => onChange?.(e.target.value)}
        />
      )}
    </div>
  );
}

function DropdownField({ label, value, options, onChange }) {
  return (
    <div className="field">
      <label className="field-label">{label}</label>
      <div className="dropdown-wrapper">
        <select
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
          className="dropdown-select"
        >
          <option value="" disabled>
            Select type
          </option>
          {options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

// --- DATE: stores/reads YYYY-MM-DD, displays DD/MM/YYYY, native picker via overlay ---
function DateField({ label, value, onChange }) {
  const displayValue = isoToDDMMYYYY(value);

  return (
    <div className="field date-field-wrapper">
      <label className="field-label">{label}</label>
      <div className="picker-overlay-container">
        <input
          type="text"
          readOnly
          value={displayValue}
          placeholder="DD/MM/YYYY"
          className="picker-display-input"
        />
        <input
          type="date"
          value={value || ""}
          onChange={(e) => onChange(e.target.value)} // native gives YYYY-MM-DD
          className="picker-native-input"
        />
      </div>
    </div>
  );
}

// --- TIME: stores/reads HH:MM (24hr), displays HH:MM AM/PM, native picker via overlay ---
function TimeField({ label, value, onChange }) {
  const displayValue = time24ToAMPM(value);

  return (
    <div className="field time-field-wrapper">
      <label className="field-label">{label}</label>
      <div className="picker-overlay-container">
        <input
          type="text"
          readOnly
          value={displayValue}
          placeholder="HH:MM AM/PM"
          className="picker-display-input"
        />
        <input
          type="time"
          value={value || ""}
          onChange={(e) => onChange(e.target.value)} // native gives HH:MM 24hr
          className="picker-native-input"
        />
      </div>
    </div>
  );
}

function SentimentField({ label, value, onChange }) {
  return (
    <div className="field">
      <label className="field-label">{label}</label>
      <div className="sentiment-options">
        {SENTIMENTS.map((s) => (
          <button
            key={s.value}
            type="button"
            className={`sentiment-circle ${value === s.value ? "selected" : ""}`}
            style={{
              "--sentiment-color": s.color,
            }}
            onClick={() => onChange(s.value)}
            title={s.label}
          >
            <span className="sentiment-dot" />
            <span className="sentiment-label">{s.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// --- Formatting helpers ---
function isoToDDMMYYYY(isoDate) {
  if (!isoDate) return "";
  const [y, m, d] = isoDate.split("-");
  if (!y || !m || !d) return "";
  return `${d}/${m}/${y}`;
}

function time24ToAMPM(time24) {
  if (!time24) return "";
  const [hStr, mStr] = time24.split(":");
  let h = parseInt(hStr, 10);
  const period = h >= 12 ? "PM" : "AM";
  h = h % 12;
  if (h === 0) h = 12;
  return `${String(h).padStart(2, "0")}:${mStr} ${period}`;
}