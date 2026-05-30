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
import { useState, useRef, useCallback, useEffect } from "react";
import ChatView from "./components/ChatView";
import ModeToggle from "./components/ModeToggle";
import AnchorToggle from "./components/AnchorToggle";
import ModelChips from "./components/ModelChips";
import ProtocolToggle from "./components/ProtocolToggle";
import ContextModeToggle from "./components/ContextModeToggle";
import ContextEditor from "./components/ContextEditor";
import useSSE from "./hooks/useSSE";
import { sendMessage, exportConversation, getConversation, deleteMessage } from "./api";
import ConversationSidebar from "./components/ConversationSidebar";
import ModelSettingsPanel from "./components/ModelSettingsPanel";
import DissentToggle from "./components/DissentToggle";

const TABS = [
  { id: "chat", label: "Chat" },
  { id: "context", label: "Memory / Context" },
];

export const MODEL_META = {
  claude: { name: "Claude", color: "#D97706", accent: "#FBBF24", icon: "◈" },
  gpt:    { name: "GPT", color: "#10B981", accent: "#6EE7B7", icon: "◉" },
  gemini: { name: "Gemini", color: "#6366F1", accent: "#A5B4FC", icon: "◆" },
  grok:   { name: "Grok", color: "#EC4899", accent: "#F9A8D4", icon: "✕" },
  ollama: { name: "Ollama", color: "#8B5CF6", accent: "#C084FC", icon: "🖳" },
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
  const [refreshSidebar, setRefreshSidebar] = useState(0);
  const conversationIdRef = useRef(null);
  const [showModelSettings, setShowModelSettings] = useState(false);
  const [modelOverrides, setModelOverrides] = useState({
    claude: {},
    gpt: {},
    gemini: {},
    grok: {},
    ollama: {},
  });
  const [forcedDissent, setForcedDissent] = useState(false);

  useEffect(() => {
    conversationIdRef.current = conversationId;
  }, [conversationId]);

  const handleSelectConversation = useCallback(async (id) => {
    try {
      const data = await getConversation(id);
      const conv = data.conversation;
      setConversationId(conv.id);
      setProtocol(conv.protocol || "roundtable");
      setMode(conv.mode || "regular");
      setAnchor(conv.anchor || "knowledge");
      setContextMode(conv.context_mode || "full");
      setSelectedTopics(conv.selected_topics ? JSON.parse(conv.selected_topics) : []);
      setForcedDissent(conv.forced_dissent || false);
      setMessages(data.messages || []);
      setLoadedTopics([]);
      setContextTokens(0);
      setCompactionNotice(null);
    } catch (err) {
      console.error("Failed to load conversation:", err);
    }
  }, []);

  const handleNewChat = useCallback(() => {
    setMessages([]);
    setConversationId(null);
    setSending(false);
    setActiveModel(null);
    setLoadedTopics([]);
    setContextTokens(0);
    setCompactionNotice(null);
    setForcedDissent(false);
  }, []);

  const { startStream, stopStream } = useSSE({
    onModelStart: (model, name, protocolRole) => {
      setActiveModel(model);
      setMessages(prev => {
        if (prev.some(m => m.model === model && m._streaming)) {
          return prev;
        }
        return [...prev, {
          role: "assistant", model,
          name: MODEL_META[model]?.name || name || model,
          content: "", _streaming: true, protocolRole,
          id: Date.now() + Math.random(),
        }];
      });
    },
    onToken: (model, delta) => {
      setMessages(prev =>
        prev.map(m =>
          m.model === model && m._streaming
            ? { ...m, content: m.content + delta }
            : m
        )
      );
    },
    onThinkingToken: (model, delta) => {
      setMessages(prev =>
        prev.map(m =>
          m.model === model && m._streaming
            ? { ...m, thinking_content: (m.thinking_content || "") + delta }
            : m
        )
      );
    },
    onModelDone: (model, content, protocolRole, thinkingContent) => {
      setActiveModel(null);
      const trust_tier = protocolRole === "synthesis" ? "derived" : "model";
      setMessages(prev => {
        const hasStreaming = prev.some(m => m.model === model && m._streaming);
        if (hasStreaming) {
          return prev.map(m =>
            m.model === model && m._streaming
              ? { ...m, content: content || "⚠ Empty response", _streaming: false, protocolRole, trust_tier, thinking_content: thinkingContent }
              : m
          );
        } else {
          return [...prev, {
            role: "assistant", model,
            name: MODEL_META[model]?.name || model,
            content: content || "⚠ Empty response", _streaming: false,
            protocolRole, trust_tier, thinking_content: thinkingContent,
            id: Date.now() + Math.random(),
          }];
        }
      });
    },
    onModelError: (model, error, details) => {
      setActiveModel(null);
      let displayError = error ? `⚠ ${error}` : "⚠ Connection or streaming error";
      if (details && details.provider_message) {
        const typeStr = details.type ? ` [Type: ${details.type.replace("_", " ")}]` : "";
        displayError = `⚠ Error: ${details.provider_message}${typeStr}`;
      }
      setMessages(prev => {
        const hasStreaming = prev.some(m => m.model === model && m._streaming);
        if (hasStreaming) {
          return prev.map(m =>
            m.model === model && m._streaming
              ? { ...m, content: displayError, isError: true, _streaming: false, trust_tier: "system" }
              : m
          );
        }
        return [...prev, {
          role: "assistant", model,
          name: MODEL_META[model]?.name || model,
          content: displayError, isError: true,
          trust_tier: "system",
          id: Date.now() + Math.random(),
        }];
      });
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
      
      const currentId = conversationIdRef.current;
      if (currentId) {
        getConversation(currentId).then(data => {
          if (data && data.messages) {
            setMessages(data.messages);
          }
        }).catch(err => console.error("Error hydrating message IDs:", err));
      }
      
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
        forced_dissent: forcedDissent,
      });

      const isNew = !conversationId;
      setConversationId(res.conversation_id);
      if (isNew) {
        setRefreshSidebar(prev => prev + 1);
      }

      const activeOverrides = {};
      for (const key of enabledModels) {
        if (modelOverrides[key] && Object.keys(modelOverrides[key]).length > 0) {
          activeOverrides[key] = modelOverrides[key];
        }
      }

      startStream(res.conversation_id, {
        mode: res.mode,
        anchor: res.anchor,
        protocol: res.protocol,
        enabled_models: enabledModels,
        debate_roles: res.protocol === "debate" ? effectiveDebateRoles : undefined,
        context_mode: contextMode,
        selected_topics: contextMode === "select" ? selectedTopics : undefined,
        model_overrides: activeOverrides,
        forced_dissent: res.forced_dissent || forcedDissent,
      });
    } catch (err) {
      setSending(false);
      console.error("Send failed:", err);
    }
  }, [sending, conversationId, mode, anchor, protocol, enabledModels, effectiveDebateRoles, contextMode, selectedTopics, modelOverrides, forcedDissent, startStream]);

  const handleStop = useCallback(() => {
    stopStream();
    setSending(false);
    setActiveModel(null);
  }, [stopStream]);

  const handleRegenerate = useCallback(async (msg) => {
    if (sending || !conversationId) return;
    setSending(true);
    
    let dbMessageId = msg.id;
    if (typeof dbMessageId === "number" && dbMessageId > 10000000000) {
      try {
        const data = await getConversation(conversationId);
        const serverMsg = data.messages?.find(
          m => m.model === msg.model && !m.compacted && Math.abs(new Date(m.created_at).getTime() - msg.id) < 600000
        ) || data.messages?.reverse().find(m => m.model === msg.model && !m.compacted);
        
        if (serverMsg) {
          dbMessageId = serverMsg.id;
        }
      } catch (err) {
        console.error("Failed to find db message ID for regeneration:", err);
      }
    }
    
    try {
      if (typeof dbMessageId === "number" && dbMessageId < 10000000000) {
        await deleteMessage(dbMessageId);
      }
      
      setMessages(prev => prev.filter(m => m.id !== msg.id));
      
      const activeOverrides = {};
      if (modelOverrides[msg.model] && Object.keys(modelOverrides[msg.model]).length > 0) {
        activeOverrides[msg.model] = modelOverrides[msg.model];
      }

      startStream(conversationId, {
        mode,
        anchor,
        protocol,
        enabled_models: [msg.model],
        debate_roles: protocol === "debate" ? effectiveDebateRoles : undefined,
        context_mode: contextMode,
        selected_topics: contextMode === "select" ? selectedTopics : undefined,
        model_overrides: activeOverrides,
        forced_dissent: forcedDissent,
      });
    } catch (err) {
      setSending(false);
      console.error("Regeneration failed:", err);
    }
  }, [sending, conversationId, mode, anchor, protocol, effectiveDebateRoles, contextMode, selectedTopics, modelOverrides, forcedDissent, startStream]);

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
      display: "flex", flexDirection: "row", overflow: "hidden",
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

      <ConversationSidebar
        currentId={conversationId}
        onSelect={handleSelectConversation}
        onNewChat={handleNewChat}
        refreshTrigger={refreshSidebar}
      />

      {/* Main chat layout */}
      <div style={{
        flex: 1, display: "flex", flexDirection: "column", overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{
          padding: "12px 20px", borderBottom: "1px solid #141418",
          display: "flex", alignItems: "center", gap: 12, background: "#0C0C0F", flexShrink: 0,
          flexWrap: "wrap",
        }}>
          <span style={{ fontSize: 20, color: "#D97706" }}>⬡</span>
          <button
            onClick={handleNewChat}
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
          <ProtocolToggle protocol={protocol} onChange={setProtocol} disabled={conversationId !== null} />
          <ModeToggle mode={mode} onChange={setMode} disabled={conversationId !== null} />
          <AnchorToggle anchor={anchor} onChange={setAnchor} disabled={conversationId !== null} />
          <DissentToggle enabled={forcedDissent} onChange={setForcedDissent} disabled={conversationId !== null} />
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
          <button
            onClick={() => setShowModelSettings(prev => !prev)}
            style={{
              padding: "4px 8px",
              borderRadius: 6,
              border: "1px solid #27272A",
              background: showModelSettings ? "#D9770618" : "transparent",
              color: showModelSettings ? "#D97706" : "#71717A",
              fontFamily: "inherit",
              fontSize: 11,
              cursor: "pointer",
              marginLeft: "auto",
              display: "flex",
              alignItems: "center",
              gap: 4,
              transition: "all 0.2s",
            }}
            onMouseEnter={e => {
              if (!showModelSettings) {
                e.target.style.borderColor = "#D97706";
                e.target.style.color = "#D97706";
              }
            }}
            onMouseLeave={e => {
              if (!showModelSettings) {
                e.target.style.borderColor = "#27272A";
                e.target.style.color = "#71717A";
              }
            }}
          >
            <span>⚙</span> Config
          </button>
        </div>

        {showModelSettings && (
          <ModelSettingsPanel
            enabledModels={enabledModels}
            overrides={modelOverrides}
            onChange={(key, newOverrides) => {
              setModelOverrides(prev => ({
                ...prev,
                [key]: newOverrides,
              }));
            }}
            mode={mode}
          />
        )}

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
              sending={sending} onSend={handleSend} onRegenerate={handleRegenerate} onStop={handleStop}
              inputRef={inputRef} enabledModels={enabledModels}
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
    </div>
  );
}
