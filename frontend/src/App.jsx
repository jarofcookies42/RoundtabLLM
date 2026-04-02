/**
 * RoundtabLLM — Main App Shell
 *
 * State lives here and flows down to children:
 *   - messages[]         current conversation messages
 *   - mode               "regular" | "overdrive"
 *   - anchor             "knowledge" | "abstract"
 *   - contextMode        "full" | "select" | "none"
 *   - selectedTopics[]   topic keys for select mode
 *   - enabledModels[]    which model keys are active
 *   - activeModel        which model is currently generating (null when idle)
 *   - tab                "chat" | "context"
 *   - conversationId     current conversation DB id
 *
 * Theme: dark background (#08080B), monospace chat, Sora headings.
 * Model colors: claude=#D97706, gpt=#10B981, gemini=#6366F1, grok=#EC4899
 */
import { useState, useRef, useCallback } from "react";
import ChatView from "./components/ChatView";
import ModeToggle from "./components/ModeToggle";
import AnchorToggle from "./components/AnchorToggle";
import ModelChips from "./components/ModelChips";
import ProtocolToggle from "./components/ProtocolToggle";
import ContextModeToggle from "./components/ContextModeToggle";
import ContextEditor from "./components/ContextEditor";
import useSSE from "./hooks/useSSE";
import { sendMessage, exportConversation } from "./api";

const TABS = [
  { id: "chat", label: "Chat" },
  { id: "context", label: "Memory / Context" },
];

// Model metadata (display only — actual configs live on the backend)
export const MODEL_META = {
  claude: { name: "Claude", color: "#D97706", accent: "#FBBF24", icon: "◈" },
  gpt:    { name: "GPT-5.4", color: "#10B981", accent: "#6EE7B7", icon: "◉" },
  gemini: { name: "Gemini 3.1 Pro", color: "#6366F1", accent: "#A5B4FC", icon: "◆" },
  grok:   { name: "Grok 4.20", color: "#EC4899", accent: "#F9A8D4", icon: "✕" },
};

export default function App() {
  const [authed, setAuthed] = useState(!!localStorage.getItem("roundtable_token"));
  const [tokenInput, setTokenInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [mode, setMode] = useState("regular");
  const [anchor, setAnchor] = useState("knowledge");
  const [enabledModels, setEnabledModels] = useState(["claude", "gpt", "gemini", "grok"]);
  const [activeModel, setActiveModel] = useState(null);
  const [sending, setSending] = useState(false);
  const [protocol, setProtocol] = useState("roundtable");
  const [debateRoles, setDebateRoles] = useState({});
  const [contextMode, setContextMode] = useState("full");
  const [selectedTopics, setSelectedTopics] = useState([]);
  const [loadedTopics, setLoadedTopics] = useState([]);
  const [contextTokens, setContextTokens] = useState(0);
  const [contextLimit, setContextLimit] = useState(30000);
  const [compactionNotice, setCompactionNotice] = useState(null);
  const [tab, setTab] = useState("chat");
  const [conversationId, setConversationId] = useState(null);
  const inputRef = useRef(null);

  const { startStream } = useSSE({
    onModelStart: (model, name, protocolRole) => setActiveModel(model),
    onToken: (model, delta) => {
      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last && last.model === model && last._streaming) {
          return [...prev.slice(0, -1), { ...last, content: last.content + delta }];
        }
        return [...prev, {
          role: "assistant", model,
          name: MODEL_META[model]?.name || model,
          content: delta, _streaming: true,
          id: Date.now() + Math.random(),
        }];
      });
    },
    onModelDone: (model, content, protocolRole) => {
      setActiveModel(null);
      const trust_tier = protocolRole === "synthesis" ? "derived" : "model";
      setMessages(prev =>
        prev.map(m =>
          m.model === model && m._streaming
            ? { ...m, content, _streaming: false, protocolRole, trust_tier }
            : m
        )
      );
    },
    onModelError: (model, error) => {
      setActiveModel(null);
      setMessages(prev => [...prev, {
        role: "assistant", model,
        name: MODEL_META[model]?.name || model,
        content: `⚠ ${error}`, isError: true,
        trust_tier: "system",
        id: Date.now() + Math.random(),
      }]);
    },
    onContextLoaded: (topics) => setLoadedTopics(topics || []),
    onCompaction: (data) => {
      setCompactionNotice(`Compacted ${data.messages_compacted} older messages`);
      setTimeout(() => setCompactionNotice(null), 5000);
    },
    onRoundDone: (ctxTokens, ctxLimit) => {
      setSending(false);
      setActiveModel(null);
      if (ctxTokens) setContextTokens(ctxTokens);
      if (ctxLimit) setContextLimit(ctxLimit);
      setTimeout(() => inputRef.current?.focus(), 100);
    },
  });

  // --- Anchor order for display ---
  const anchorOrder = anchor === "knowledge"
    ? ["grok", "gpt", "gemini", "claude"]
    : ["grok", "gpt", "claude", "gemini"];
  const activeOrder = anchorOrder.filter(k => enabledModels.includes(k));
  const anchorModel = activeOrder[activeOrder.length - 1];

  // --- Default debate role assignment ---
  const getDefaultDebateRoles = (order) => {
    if (order.length < 3) return {};
    const roles = {};
    roles[order[0]] = "proposer";
    roles[order[1]] = "critic";
    roles[order[2]] = "proposer";
    roles[order[order.length - 1]] = "synthesizer";
    if (order.length === 3) roles[order[2]] = "synthesizer";
    return roles;
  };

  const effectiveDebateRoles = (() => {
    if (protocol !== "debate") return {};
    const enabledRoles = {};
    for (const k of activeOrder) {
      if (debateRoles[k]) enabledRoles[k] = debateRoles[k];
    }
    if (Object.keys(enabledRoles).length === activeOrder.length && activeOrder.length >= 3) {
      return enabledRoles;
    }
    return getDefaultDebateRoles(activeOrder);
  })();

  const handleSend = useCallback(async (text) => {
    if (!text.trim() || sending) return;
    setSending(true);
    setLoadedTopics([]);

    const userMsg = {
      role: "user", model: "user", name: "Jack",
      content: text.trim(), id: Date.now(),
    };
    setMessages(prev => [...prev, userMsg]);

    try {
      const res = await sendMessage({
        message: text.trim(),
        conversation_id: conversationId,
        mode, anchor, protocol,
        enabled_models: enabledModels,
        debate_roles: protocol === "debate" ? effectiveDebateRoles : undefined,
        context_mode: contextMode,
        selected_topics: contextMode === "select" ? selectedTopics : undefined,
      });
      setConversationId(res.conversation_id);
      startStream(res.conversation_id, {
        mode, anchor, protocol, enabled_models: enabledModels,
        debate_roles: protocol === "debate" ? effectiveDebateRoles : undefined,
        context_mode: contextMode,
        selected_topics: contextMode === "select" ? selectedTopics : undefined,
      });
    } catch (err) {
      setSending(false);
      console.error("Send failed:", err);
    }
  }, [sending, conversationId, mode, anchor, protocol, enabledModels, effectiveDebateRoles, contextMode, selectedTopics, startStream]);

  // --- Auth gate ---
  if (!authed) {
    return (
      <div style={{
        height: "100vh", background: "#08080B", color: "#E4E4E7",
        fontFamily: "'JetBrains Mono', monospace",
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 16,
      }}>
        <span style={{ fontSize: 32, color: "#D97706" }}>⬡</span>
        <div style={{ fontFamily: "'Sora', sans-serif", fontWeight: 800, fontSize: 18 }}>RoundtabLLM</div>
        <form onSubmit={(e) => {
          e.preventDefault();
          if (tokenInput.trim()) {
            localStorage.setItem("roundtable_token", tokenInput.trim());
            setAuthed(true);
          }
        }} style={{ display: "flex", gap: 8 }}>
          <input type="password" placeholder="Auth token" value={tokenInput}
            onChange={e => setTokenInput(e.target.value)} autoFocus
            style={{ padding: "8px 14px", background: "#18181B", border: "1px solid #27272A",
              borderRadius: 8, color: "#E4E4E7", fontFamily: "inherit", fontSize: 13, width: 240 }} />
          <button type="submit" style={{ padding: "8px 16px", background: "#D97706", color: "#000",
            border: "none", borderRadius: 8, fontFamily: "inherit", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>Enter</button>
        </form>
      </div>
    );
  }

  return (
    <div style={{
      height: "100vh", background: "#08080B", color: "#E4E4E7",
      fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #27272A; border-radius: 3px; }
        @keyframes pulse-dot { 0%,100% { opacity:.3; } 50% { opacity:1; } }
        @keyframes slide-up { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
        .msg-enter { animation: slide-up 0.25s ease-out; }
      `}</style>

      {/* Header */}
      <div style={{
        padding: "12px 20px", borderBottom: "1px solid #141418",
        display: "flex", alignItems: "center", gap: 12, background: "#0C0C0F", flexShrink: 0,
        flexWrap: "wrap",
      }}>
        <span style={{ fontSize: 20, color: "#D97706" }}>⬡</span>
        <button
          onClick={() => { setMessages([]); setConversationId(null); setSending(false); setActiveModel(null); setLoadedTopics([]); setContextTokens(0); setCompactionNotice(null); }}
          title="New chat"
          style={{ background: "transparent", border: "1px solid #27272A", borderRadius: 6,
            color: "#71717A", cursor: "pointer", padding: "4px 8px", fontSize: 13,
            fontFamily: "inherit", lineHeight: 1, transition: "all 0.2s" }}
          onMouseEnter={e => { e.target.style.borderColor = "#D97706"; e.target.style.color = "#D97706"; }}
          onMouseLeave={e => { e.target.style.borderColor = "#27272A"; e.target.style.color = "#71717A"; }}
        >+</button>
        {conversationId && (
          <button onClick={() => exportConversation(conversationId)} title="Export as markdown"
            style={{ background: "transparent", border: "1px solid #27272A", borderRadius: 6,
              color: "#71717A", cursor: "pointer", padding: "4px 8px", fontSize: 11,
              fontFamily: "inherit", lineHeight: 1, transition: "all 0.2s" }}
            onMouseEnter={e => { e.target.style.borderColor = "#D97706"; e.target.style.color = "#D97706"; }}
            onMouseLeave={e => { e.target.style.borderColor = "#27272A"; e.target.style.color = "#71717A"; }}
          >Export</button>
        )}
        <div style={{ marginRight: "auto" }}>
          <div style={{ fontFamily: "'Sora', sans-serif", fontWeight: 800, fontSize: 15, color: "#FAFAFA" }}>
            RoundtabLLM
          </div>
          <div style={{ fontSize: 10, color: "#52525B" }}>
            {activeOrder.length} model{activeOrder.length !== 1 ? "s" : ""} · {MODEL_META[anchorModel]?.name} anchors
            {loadedTopics.length > 0 && ` · ctx: ${loadedTopics.join(", ")}`}
          </div>
        </div>
        <ContextModeToggle contextMode={contextMode} onChange={setContextMode} />
        <ProtocolToggle protocol={protocol} onChange={setProtocol} />
        <ModeToggle mode={mode} onChange={setMode} />
        <AnchorToggle anchor={anchor} onChange={setAnchor} />
      </div>

      {/* Model chips */}
      <div style={{
        padding: "10px 20px", borderBottom: "1px solid #141418",
        display: "flex", gap: 6, flexWrap: "wrap", background: "#0C0C0F", flexShrink: 0,
        alignItems: "center",
      }}>
        <ModelChips
          enabledModels={enabledModels}
          onToggle={(key) => setEnabledModels(prev =>
            prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
          )}
          mode={mode}
          protocol={protocol}
          debateRoles={effectiveDebateRoles}
          onRoleChange={(key, newRole) => {
            setDebateRoles(prev => {
              const next = { ...effectiveDebateRoles, [key]: newRole };
              const models = activeOrder.filter(k => k !== key);
              const counts = { proposer: 0, critic: 0, synthesizer: 0 };
              counts[newRole] = 1;
              for (const k of models) { if (next[k]) counts[next[k]]++; }
              const targetProposers = activeOrder.length >= 4 ? 2 : 1;
              const target = { proposer: targetProposers, critic: 1, synthesizer: 1 };
              const over = Object.keys(counts).find(r => counts[r] > target[r]);
              const under = Object.keys(counts).find(r => counts[r] < target[r]);
              if (over && under) {
                const victim = models.find(k => next[k] === over);
                if (victim) next[victim] = under;
              }
              return next;
            });
          }}
        />
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid #141418", background: "#0C0C0F", flexShrink: 0 }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            style={{
              padding: "8px 18px", border: "none", background: "transparent",
              color: tab === t.id ? "#D97706" : "#52525B",
              fontFamily: "inherit", fontSize: 11, fontWeight: 600, cursor: "pointer",
              letterSpacing: "0.08em", textTransform: "uppercase",
              borderBottom: tab === t.id ? "2px solid #D97706" : "2px solid transparent",
            }}
          >{t.label}</button>
        ))}
      </div>

      {/* Main content */}
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {tab === "chat" && (
          <ChatView messages={messages} activeModel={activeModel} anchorModel={anchorModel}
            sending={sending} onSend={handleSend} inputRef={inputRef} enabledModels={enabledModels}
            contextTokens={contextTokens} contextLimit={contextLimit} compactionNotice={compactionNotice} />
        )}
        {tab === "context" && (
          <ContextEditor
            contextMode={contextMode}
            selectedTopics={selectedTopics}
            onSelectedTopicsChange={setSelectedTopics}
          />
        )}
      </div>
    </div>
  );
}
