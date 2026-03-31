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

export default function ProtocolToggle({ protocol, onChange }) {
  const current = PROTOCOLS.find((p) => p.id === protocol) || PROTOCOLS[0];
  const nextIdx = (PROTOCOLS.findIndex((p) => p.id === protocol) + 1) % PROTOCOLS.length;

  return (
    <button
      onClick={() => onChange(PROTOCOLS[nextIdx].id)}
      title={current.desc}
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
      {current.icon} {current.label}
    </button>
  );
}
