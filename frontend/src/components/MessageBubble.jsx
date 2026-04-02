/**
 * MessageBubble — Single message in the chat.
 * Styled per model with colored left border, icon, and optional badges
 * for anchor, protocol roles (proposal/critic/synthesis).
 */
import { MODEL_META } from "../App";

const PROTOCOL_BADGES = {
  proposal:  { label: "proposal",  bg: "#8B5CF620", color: "#A78BFA" },
  critic:    { label: "critic",    bg: "#F59E0B20", color: "#FCD34D" },
  synthesis: { label: "synthesis", bg: "#06B6D420", color: "#67E8F9" },
};

export default function MessageBubble({ msg, isAnchor }) {
  const isUser = msg.model === "user";
  const meta = MODEL_META[msg.model];
  const color = isUser ? "#D97706" : msg.isError ? "#EF4444" : meta?.color || "#444";
  const badge = msg.protocolRole ? PROTOCOL_BADGES[msg.protocolRole] : null;

  return (
    <div className="msg-enter" style={{
      display: "flex", gap: 10, padding: "12px 14px", borderRadius: 10,
      background: isUser ? "#D9770608" : msg.isError ? "#EF444410" : "#0F0F13",
      borderLeft: `2.5px solid ${color}`,
    }}>
      <div style={{
        width: 28, height: 28, borderRadius: 7, flexShrink: 0,
        background: color + "18",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 14, color,
      }}>
        {isUser ? "▹" : meta?.icon || "?"}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 10, fontWeight: 600, marginBottom: 5, color,
          letterSpacing: "0.07em", textTransform: "uppercase",
          display: "flex", alignItems: "center", gap: 6,
        }}>
          {msg.name}
          {badge && (
            <span style={{
              fontSize: 9, padding: "2px 8px", borderRadius: 10,
              background: badge.bg, color: badge.color,
              fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase",
            }}>
              {badge.label}
            </span>
          )}
          {!isUser && isAnchor && !badge && (
            <span style={{
              fontSize: 9, padding: "2px 8px", borderRadius: 10,
              background: "#D9770625", color: "#FBBF24",
              fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase",
            }}>
              anchor
            </span>
          )}
          {!isUser && msg.trust_tier && msg.trust_tier !== "model" && msg.trust_tier !== "direct" && (
            <span style={{
              fontSize: 9, padding: "2px 8px", borderRadius: 10,
              background: msg.trust_tier === "derived" ? "#06B6D415" : msg.trust_tier === "imported" ? "#8B5CF615" : "#52525B15",
              color: msg.trust_tier === "derived" ? "#67E8F9" : msg.trust_tier === "imported" ? "#A78BFA" : "#71717A",
              fontWeight: 500, letterSpacing: "0.06em", textTransform: "uppercase",
            }}>
              {msg.trust_tier}
            </span>
          )}
          {msg._streaming && (
            <span style={{
              fontSize: 9, padding: "2px 8px", borderRadius: 10,
              background: color + "20", color: color,
              fontWeight: 500,
            }}>
              streaming...
            </span>
          )}
        </div>
        <div style={{
          fontSize: 13, lineHeight: 1.65,
          color: msg.isError ? "#F87171" : "#C4C4CC",
          whiteSpace: "pre-wrap", wordBreak: "break-word",
        }}>
          {msg.content}
        </div>
      </div>
    </div>
  );
}
