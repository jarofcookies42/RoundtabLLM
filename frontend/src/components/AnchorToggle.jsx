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

export default function AnchorToggle({ anchor, onChange, disabled }) {
  const isAbstract = anchor === "abstract";

  return (
    <button
      onClick={() => !disabled && onChange(isAbstract ? "knowledge" : "abstract")}
      title={disabled ? "Locked for this conversation" : ""}
      style={{
        padding: "6px 14px",
        borderRadius: 16,
        border: `1.5px solid ${disabled ? "#27272a" : isAbstract ? "#6366F1" : "#D97706"}`,
        background: disabled ? "transparent" : isAbstract ? "#6366F115" : "#D9770615",
        color: disabled ? "#52525b" : isAbstract ? "#A5B4FC" : "#FBBF24",
        fontFamily: "inherit",
        fontSize: 11,
        fontWeight: 600,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.6 : 1,
        letterSpacing: "0.04em",
        transition: "all 0.2s",
        whiteSpace: "nowrap",
      }}
    >
      {isAbstract ? "◆ Abstract anchor" : "◈ Knowledge anchor"}
    </button>
  );
}
