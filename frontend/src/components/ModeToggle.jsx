/**
 * ModeToggle — Switches between Regular and Maximum Overdrive.
 *
 * Regular:  Sonnet 4.6, GPT-5.4 (no reasoning), Gemini (low think), Grok (0.7)
 * Overdrive: Opus 4.6 (adaptive), GPT-5.4 (high reasoning), Gemini (Deep Think Mini), Grok (0.9)
 *
 * Single toggle. Two states. That's it.
 */

export default function ModeToggle({ mode, onChange, disabled }) {
  const isOverdrive = mode === "overdrive";

  return (
    <button
      onClick={() => !disabled && onChange(isOverdrive ? "regular" : "overdrive")}
      title={disabled ? "Locked for this conversation" : ""}
      style={{
        padding: "6px 14px",
        borderRadius: 16,
        border: `1.5px solid ${disabled ? "#27272a" : isOverdrive ? "#EF4444" : "#27272A"}`,
        background: disabled ? "transparent" : isOverdrive ? "#EF444415" : "transparent",
        color: disabled ? "#52525b" : isOverdrive ? "#FCA5A5" : "#71717A",
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
      {isOverdrive ? "⚡ MAXIMUM OVERDRIVE" : "● Regular"}
    </button>
  );
}
