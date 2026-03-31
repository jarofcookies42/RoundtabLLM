/**
 * ModeToggle — Switches between Regular and Maximum Overdrive.
 *
 * Regular:  Sonnet 4.6, GPT-5.4 (no reasoning), Gemini (low think), Grok (0.7)
 * Overdrive: Opus 4.6 (adaptive), GPT-5.4 (high reasoning), Gemini (Deep Think Mini), Grok (0.9)
 *
 * Single toggle. Two states. That's it.
 */

export default function ModeToggle({ mode, onChange }) {
  const isOverdrive = mode === "overdrive";

  return (
    <button
      onClick={() => onChange(isOverdrive ? "regular" : "overdrive")}
      style={{
        padding: "6px 14px",
        borderRadius: 16,
        border: `1.5px solid ${isOverdrive ? "#EF4444" : "#27272A"}`,
        background: isOverdrive ? "#EF444415" : "transparent",
        color: isOverdrive ? "#FCA5A5" : "#71717A",
        fontFamily: "inherit",
        fontSize: 11,
        fontWeight: 600,
        cursor: "pointer",
        letterSpacing: "0.04em",
        transition: "all 0.2s",
        whiteSpace: "nowrap",
      }}
    >
      {isOverdrive ? "⚡ MAXIMUM OVERDRIVE" : "● Regular"}
    </button>
  );
}
