/**
 * ContextModeToggle — Cycles through Full / Select / None context modes.
 * Controls how much personal context is loaded per round.
 */

const MODES = [
  {
    id: "full",
    label: "Full",
    icon: "◉",
    desc: "auto-detect relevant topics",
    color: "#10B981",
  },
  {
    id: "select",
    label: "Select",
    icon: "◎",
    desc: "manually pick topics",
    color: "#6366F1",
  },
  {
    id: "none",
    label: "None",
    icon: "○",
    desc: "no personal context",
    color: "#71717A",
  },
];

export default function ContextModeToggle({ contextMode, onChange }) {
  const current = MODES.find((m) => m.id === contextMode) || MODES[0];
  const nextIdx = (MODES.findIndex((m) => m.id === contextMode) + 1) % MODES.length;

  return (
    <button
      onClick={() => onChange(MODES[nextIdx].id)}
      title={`Context: ${current.desc}`}
      style={{
        padding: "6px 14px",
        borderRadius: 16,
        border: `1.5px solid ${current.color}40`,
        background: current.color + "12",
        color: current.color,
        fontFamily: "inherit",
        fontSize: 11,
        fontWeight: 600,
        cursor: "pointer",
        letterSpacing: "0.04em",
        transition: "all 0.2s",
        whiteSpace: "nowrap",
      }}
    >
      {current.icon} Ctx: {current.label}
    </button>
  );
}
