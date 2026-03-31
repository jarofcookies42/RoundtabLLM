/**
 * AnchorToggle — Switches which model goes last.
 *
 * Knowledge: Claude anchors (last). Best for professional knowledge work, coding, nuanced analysis.
 *   Order: Grok → GPT → Gemini → Claude
 *
 * Abstract: Gemini anchors (last). Best for abstract reasoning, novel logic, scientific synthesis.
 *   Order: Grok → GPT → Claude → Gemini
 *
 * The anchor sees all other models' full responses before generating its own.
 */

export default function AnchorToggle({ anchor, onChange }) {
  const isAbstract = anchor === "abstract";

  return (
    <button
      onClick={() => onChange(isAbstract ? "knowledge" : "abstract")}
      style={{
        padding: "6px 14px",
        borderRadius: 16,
        border: `1.5px solid ${isAbstract ? "#6366F1" : "#D97706"}`,
        background: isAbstract ? "#6366F115" : "#D9770615",
        color: isAbstract ? "#A5B4FC" : "#FBBF24",
        fontFamily: "inherit",
        fontSize: 11,
        fontWeight: 600,
        cursor: "pointer",
        letterSpacing: "0.04em",
        transition: "all 0.2s",
        whiteSpace: "nowrap",
      }}
    >
      {isAbstract ? "◆ Abstract anchor" : "◈ Knowledge anchor"}
    </button>
  );
}
