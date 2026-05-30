/**
 * ProtocolToggle — Cycles through Roundtable / Blind / Debate protocols.
 * Independent of mode (Regular/Overdrive) and anchor (Knowledge/Abstract).
 */

const PROTOCOLS = [
  {
    id: "roundtable",
    label: "Roundtable",
    icon: "◎",
    desc: "sequential, building on each other",
    color: "#D97706",
  },
  {
    id: "blind",
    label: "Blind",
    icon: "◉",
    desc: "independent answers → synthesis",
    color: "#8B5CF6",
  },
  {
    id: "debate",
    label: "Debate",
    icon: "⚔",
    desc: "propose → critique → synthesize",
    color: "#06B6D4",
  },
];

export default function ProtocolToggle({ protocol, onChange, disabled }) {
  const current = PROTOCOLS.find((p) => p.id === protocol) || PROTOCOLS[0];
  const nextIdx = (PROTOCOLS.findIndex((p) => p.id === protocol) + 1) % PROTOCOLS.length;

  return (
    <button
      onClick={() => !disabled && onChange(PROTOCOLS[nextIdx].id)}
      title={disabled ? `${current.desc} (Locked for this conversation)` : current.desc}
      style={{
        padding: "6px 14px",
        borderRadius: 16,
        border: `1.5px solid ${disabled ? "#27272a" : current.color}40`,
        background: disabled ? "transparent" : current.color + "12",
        color: disabled ? "#52525b" : current.color,
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
      {current.icon} {current.label}
    </button>
  );
}
