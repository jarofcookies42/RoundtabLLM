/**
 * ModelChips — Toggleable chips for each model.
 * Shows model name, icon, current model variant based on mode,
 * and debate role assignment when in Debate protocol.
 */
import { MODEL_META } from "../App";

const MODE_LABELS = {
  regular: {
    claude: "Sonnet 4.6",
    gpt: "none reasoning",
    gemini: "low think",
    grok: "t=0.7",
  },
  overdrive: {
    claude: "Opus 4.6",
    gpt: "high reasoning",
    gemini: "Deep Think",
    grok: "reasoning",
  },
};

const ROLE_STYLES = {
  proposer:    { label: "P", color: "#A78BFA", bg: "#8B5CF620" },
  critic:      { label: "C", color: "#FCD34D", bg: "#F59E0B20" },
  synthesizer: { label: "S", color: "#67E8F9", bg: "#06B6D420" },
};

const ROLE_CYCLE = ["proposer", "critic", "synthesizer"];

export default function ModelChips({ enabledModels, onToggle, mode, protocol, debateRoles, onRoleChange }) {
  return (
    <>
      {Object.entries(MODEL_META).map(([key, meta]) => {
        const active = enabledModels.includes(key);
        const label = MODE_LABELS[mode]?.[key] || "";
        const role = protocol === "debate" && active ? debateRoles[key] : null;
        const roleStyle = role ? ROLE_STYLES[role] : null;

        return (
          <div key={key} style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
            <button
              onClick={() => onToggle(key)}
              style={{
                padding: "5px 12px",
                borderRadius: role ? "16px 4px 4px 16px" : 16,
                border: `1.5px solid ${active ? meta.color : "#27272A"}`,
                background: active ? meta.color + "12" : "transparent",
                color: active ? meta.accent : "#52525B",
                fontFamily: "inherit",
                fontSize: 11,
                fontWeight: 500,
                cursor: "pointer",
                transition: "all 0.2s",
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                letterSpacing: "0.03em",
              }}
            >
              <span style={{ fontSize: 13 }}>{meta.icon}</span>
              {meta.name}
              {active && label && (
                <span style={{ fontSize: 9, opacity: 0.6, marginLeft: 2 }}>
                  {label}
                </span>
              )}
            </button>
            {roleStyle && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  const nextIdx = (ROLE_CYCLE.indexOf(role) + 1) % ROLE_CYCLE.length;
                  onRoleChange(key, ROLE_CYCLE[nextIdx]);
                }}
                title={`${role} — click to change`}
                style={{
                  padding: "5px 8px",
                  borderRadius: "4px 16px 16px 4px",
                  border: `1.5px solid ${roleStyle.color}50`,
                  background: roleStyle.bg,
                  color: roleStyle.color,
                  fontFamily: "inherit",
                  fontSize: 10,
                  fontWeight: 700,
                  cursor: "pointer",
                  transition: "all 0.2s",
                  letterSpacing: "0.06em",
                  lineHeight: 1,
                  minWidth: 24,
                  textAlign: "center",
                }}
              >
                {roleStyle.label}
              </button>
            )}
          </div>
        );
      })}
    </>
  );
}
