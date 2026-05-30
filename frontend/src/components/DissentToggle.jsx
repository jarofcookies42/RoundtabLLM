/**
 * DissentToggle — Toggles forced dissent mode (demanding models critical disagreement).
 */

export default function DissentToggle({ enabled, onChange, disabled }) {
  return (
    <button
      onClick={() => !disabled && onChange(!enabled)}
      title={disabled ? "Locked for this conversation" : "Toggle forced dissent (models must disagree)"}
      style={{
        padding: "6px 14px",
        borderRadius: 16,
        border: `1.5px solid ${disabled ? "#27272a" : enabled ? "#D97706" : "#27272A"}`,
        background: disabled ? "transparent" : enabled ? "#D9770615" : "transparent",
        color: disabled ? "#52525b" : enabled ? "#FBBF24" : "#71717A",
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
      {enabled ? "⚔ Dissent: Yes" : "⚔ Dissent: No"}
    </button>
  );
}
