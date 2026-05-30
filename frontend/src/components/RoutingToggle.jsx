/**
 * RoutingToggle — Toggles benchmark-aware dynamic routing.
 */

export default function RoutingToggle({ enabled, onChange, disabled }) {
  return (
    <button
      onClick={() => !disabled && onChange(!enabled)}
      title={disabled ? "Locked for this conversation" : "Toggle benchmark-aware dynamic routing"}
      style={{
        padding: "6px 14px",
        borderRadius: 16,
        border: `1.5px solid ${disabled ? "#27272a" : enabled ? "#6366F1" : "#27272A"}`,
        background: disabled ? "transparent" : enabled ? "#6366F115" : "transparent",
        color: disabled ? "#52525b" : enabled ? "#A5B4FC" : "#71717A",
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
      {enabled ? "✦ Route: Auto" : "✦ Route: Off"}
    </button>
  );
}
