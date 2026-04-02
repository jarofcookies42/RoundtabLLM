/**
 * ContextEditor — Memory topic cards, AutoDream UI, and legacy raw context.
 *
 * Three sub-tabs:
 *   "Memory Topics" — card-based topic editor with expand/edit/save per topic
 *   "AutoDream" — trigger dream passes, review/approve/reject proposed changes
 *   "Raw Context" — legacy monolithic textarea (backward compat)
 */
import { useState, useEffect, useCallback } from "react";
import { getMemory, updateMemoryTopic, getContext, updateContext, triggerDream, listDreams, applyDream, rejectDream } from "../api";

const MODE_INFO = {
  full: { label: "Full Context", color: "#10B981", desc: "Relevance detection auto-selects 1-3 topics per round based on your message." },
  select: { label: "Select Context", color: "#6366F1", desc: "Only checked topics load, regardless of message content." },
  none: { label: "No Context", color: "#71717A", desc: "Models get no personal context — blank slate for fresh threads." },
};

const BADGE_STYLES = {
  add: { label: "ADD", color: "#10B981", bg: "#10B98118" },
  update: { label: "UPDATE", color: "#D97706", bg: "#D9770618" },
  delete: { label: "DELETE", color: "#EF4444", bg: "#EF444418" },
};

const STATUS_COLORS = {
  pending: "#D97706",
  approved: "#10B981",
  partially_approved: "#6366F1",
  rejected: "#EF4444",
  failed: "#71717A",
};

export default function ContextEditor({ contextMode, selectedTopics, onSelectedTopicsChange }) {
  const [subTab, setSubTab] = useState("topics");
  const [index, setIndex] = useState("");
  const [topics, setTopics] = useState({});
  const [topicMeta, setTopicMeta] = useState({});
  const [stats, setStats] = useState(null);
  const [expanded, setExpanded] = useState({});
  const [editing, setEditing] = useState({});
  const [saving, setSaving] = useState({});
  const [rawContent, setRawContent] = useState("");
  const [rawSaving, setRawSaving] = useState(false);

  // Dream state
  const [dreaming, setDreaming] = useState(false);
  const [dreamResult, setDreamResult] = useState(null);
  const [dreamError, setDreamError] = useState(null);
  const [dreamChecked, setDreamChecked] = useState({});
  const [applying, setApplying] = useState(false);
  const [dreamHistory, setDreamHistory] = useState([]);
  const [historyExpanded, setHistoryExpanded] = useState(false);

  const loadMemory = useCallback(() => {
    getMemory().then(data => {
      setIndex(data.index || "");
      setTopics(data.topics || {});
      setTopicMeta(data.topic_meta || {});
      setStats(data.stats || null);
    }).catch(err => console.error("Failed to load memory:", err));
  }, []);

  useEffect(() => { loadMemory(); }, [loadMemory]);

  useEffect(() => {
    if (subTab === "raw") {
      getContext().then(data => setRawContent(data.content || "")).catch(console.error);
    }
    if (subTab === "dream") {
      listDreams().then(setDreamHistory).catch(console.error);
    }
  }, [subTab]);

  const handleSaveTopic = useCallback(async (key) => {
    const content = editing[key];
    if (content === undefined) return;
    setSaving(prev => ({ ...prev, [key]: true }));
    try {
      await updateMemoryTopic(key, content);
      setTopics(prev => ({ ...prev, [key]: content }));
      setEditing(prev => { const next = { ...prev }; delete next[key]; return next; });
    } catch (err) { console.error("Failed to save topic:", err); }
    setSaving(prev => ({ ...prev, [key]: false }));
  }, [editing]);

  const handleToggleTopic = useCallback((key) => {
    if (!onSelectedTopicsChange) return;
    onSelectedTopicsChange(prev => prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]);
  }, [onSelectedTopicsChange]);

  const handleRawSave = useCallback(async () => {
    setRawSaving(true);
    try { await updateContext(rawContent); } catch (err) { console.error("Failed to save:", err); }
    setRawSaving(false);
  }, [rawContent]);

  // Dream handlers
  const handleDream = useCallback(async () => {
    setDreaming(true);
    setDreamError(null);
    setDreamResult(null);
    try {
      const result = await triggerDream();
      setDreamResult(result);
      // Check all by default
      const changes = result.proposed_changes || {};
      const total = (changes.additions?.length || 0) + (changes.updates?.length || 0) + (changes.deletions?.length || 0);
      const checked = {};
      for (let i = 0; i < total; i++) checked[i] = true;
      setDreamChecked(checked);
    } catch (err) {
      if (err.message === "DREAM_LOCKED") {
        setDreamError("A dream is already in progress.");
      } else {
        setDreamError(err.message);
      }
    }
    setDreaming(false);
  }, []);

  const handleApplyDream = useCallback(async () => {
    if (!dreamResult?.dream_id) return;
    setApplying(true);
    const indices = Object.entries(dreamChecked).filter(([, v]) => v).map(([k]) => parseInt(k));
    try {
      await applyDream(dreamResult.dream_id, indices);
      setDreamResult(null);
      setDreamChecked({});
      loadMemory();
      listDreams().then(setDreamHistory).catch(console.error);
    } catch (err) { console.error("Failed to apply dream:", err); }
    setApplying(false);
  }, [dreamResult, dreamChecked, loadMemory]);

  const handleRejectDream = useCallback(async () => {
    if (!dreamResult?.dream_id) return;
    try {
      await rejectDream(dreamResult.dream_id);
      setDreamResult(null);
      setDreamChecked({});
      listDreams().then(setDreamHistory).catch(console.error);
    } catch (err) { console.error("Failed to reject dream:", err); }
  }, [dreamResult]);

  const topicKeys = Object.keys(topics).sort();
  const modeInfo = MODE_INFO[contextMode] || MODE_INFO.full;

  // Build combined changes list for rendering
  const dreamChanges = dreamResult?.proposed_changes || {};
  const allChanges = [
    ...(dreamChanges.additions || []).map(c => ({ ...c, type: "add" })),
    ...(dreamChanges.updates || []).map(c => ({ ...c, type: "update" })),
    ...(dreamChanges.deletions || []).map(c => ({ ...c, type: "delete" })),
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
      {/* Sub-tab switcher */}
      <div style={{ display: "flex", borderBottom: "1px solid #141418", background: "#0A0A0D", flexShrink: 0 }}>
        {[{ id: "topics", label: "Memory Topics" }, { id: "dream", label: "AutoDream" }, { id: "raw", label: "Raw Context" }].map(t => (
          <button key={t.id} onClick={() => setSubTab(t.id)}
            style={{
              padding: "8px 16px", border: "none", background: "transparent",
              color: subTab === t.id ? "#D97706" : "#52525B",
              fontFamily: "inherit", fontSize: 10, fontWeight: 600, cursor: "pointer",
              letterSpacing: "0.08em", textTransform: "uppercase",
              borderBottom: subTab === t.id ? "2px solid #D97706" : "2px solid transparent",
            }}
          >{t.label}</button>
        ))}
      </div>

      {/* ==================== TOPICS PANEL ==================== */}
      {subTab === "topics" && (
        <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ padding: "10px 14px", borderRadius: 8, border: `1px solid ${modeInfo.color}30`, background: modeInfo.color + "08" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: modeInfo.color, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 4 }}>{modeInfo.label}</div>
            <div style={{ fontSize: 11, color: "#71717A", lineHeight: 1.5 }}>{modeInfo.desc}</div>
          </div>

          {/* Memory stats bar */}
          {stats && (
            <div style={{ display: "flex", gap: 12, alignItems: "center", padding: "8px 14px", borderRadius: 8, background: "#111114", border: "1px solid #1E1E22" }}>
              <div style={{ flex: 1 }}>
                <div style={{ height: 4, borderRadius: 2, background: "#1E1E22", overflow: "hidden" }}>
                  <div style={{
                    height: "100%", borderRadius: 2, transition: "width 0.3s",
                    width: `${Math.min(100, (stats.chars / stats.cap_chars) * 100)}%`,
                    background: stats.chars > stats.cap_chars * 0.9 ? "#EF4444" : stats.chars > stats.cap_chars * 0.7 ? "#D97706" : "#10B981",
                  }} />
                </div>
              </div>
              <span style={{ fontSize: 10, color: "#52525B", whiteSpace: "nowrap" }}>
                {stats.chars.toLocaleString()} / {stats.cap_chars.toLocaleString()} chars · {stats.lines} / {stats.cap_lines} lines · {stats.topics} topics
              </span>
            </div>
          )}

          {index && (
            <div style={{ padding: "10px 14px", borderRadius: 8, background: "#111114", border: "1px solid #1E1E22" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#52525B", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>Memory Index</div>
              <div style={{ fontSize: 11, color: "#71717A", lineHeight: 1.7 }}>
                {index.split("\n").filter(l => l.trim()).map((line, i) => {
                  const [key] = line.split(":");
                  return (
                    <div key={i} style={{ display: "flex", gap: 4, alignItems: "baseline" }}>
                      <span style={{ color: "#D97706", fontWeight: 600, minWidth: 80 }}>{key?.trim()}</span>
                      <span>{line.split(":").slice(1).join(":").replace(/See \w+\.md/i, "").trim()}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {topicKeys.map(key => {
            const content = editing[key] !== undefined ? editing[key] : topics[key];
            const isExpanded = expanded[key]; const isSaving = saving[key];
            const isEdited = editing[key] !== undefined;
            const isSelected = selectedTopics?.includes(key);
            const preview = topics[key]?.substring(0, 120)?.replace(/\n/g, " ") + "...";
            const meta = topicMeta[key];
            const derivedInfo = meta?.derived_from ? (() => { try { const d = JSON.parse(meta.derived_from); return d.dream_id ? `dream #${d.dream_id} (${d.conversations?.length || 0} convs)` : null; } catch { return null; } })() : null;
            return (
              <div key={key} style={{ borderRadius: 8, border: `1px solid ${isSelected && contextMode === "select" ? "#6366F1" : "#1E1E22"}`, background: "#0F0F13", overflow: "hidden" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", cursor: "pointer" }}
                  onClick={() => setExpanded(prev => ({ ...prev, [key]: !prev[key] }))}>
                  {contextMode === "select" && (
                    <input type="checkbox" checked={isSelected || false}
                      onChange={(e) => { e.stopPropagation(); handleToggleTopic(key); }}
                      style={{ accentColor: "#6366F1", cursor: "pointer" }} />
                  )}
                  <span style={{ fontSize: 12, fontWeight: 700, color: "#D97706", letterSpacing: "0.04em" }}>{key}</span>
                  <span style={{ fontSize: 10, color: "#3F3F46", marginLeft: "auto" }}>
                    {isExpanded ? "▾" : "▸"} {Math.round((topics[key]?.length || 0) / 4)} tokens
                  </span>
                </div>
                {!isExpanded && <div style={{ padding: "0 14px 10px", fontSize: 11, color: "#52525B", lineHeight: 1.5 }}>{preview}</div>}
                {meta && (meta.source !== "seed" || derivedInfo) && (
                  <div style={{ padding: "0 14px 8px", fontSize: 9, color: "#3F3F46", display: "flex", gap: 8 }}>
                    {meta.source !== "seed" && <span>source: {meta.source}</span>}
                    {meta.last_modified_by !== "user" && <span>by: {meta.last_modified_by}</span>}
                    {derivedInfo && <span>from {derivedInfo}</span>}
                  </div>
                )}
                {isExpanded && (
                  <div style={{ padding: "0 14px 12px" }}>
                    <textarea value={content} onChange={e => setEditing(prev => ({ ...prev, [key]: e.target.value }))}
                      style={{ width: "100%", minHeight: 180, background: "#111114", border: "1px solid #27272A", borderRadius: 6, color: "#D4D4D8", padding: "10px 12px", fontSize: 12, fontFamily: "'JetBrains Mono', monospace", resize: "vertical", outline: "none", lineHeight: 1.6 }} />
                    <div style={{ display: "flex", gap: 8, marginTop: 8, justifyContent: "flex-end" }}>
                      {isEdited && <button onClick={() => setEditing(prev => { const next = { ...prev }; delete next[key]; return next; })}
                        style={{ padding: "6px 14px", background: "transparent", border: "1px solid #27272A", borderRadius: 6, color: "#71717A", fontSize: 11, fontFamily: "inherit", cursor: "pointer" }}>Cancel</button>}
                      <button onClick={() => handleSaveTopic(key)} disabled={!isEdited || isSaving}
                        style={{ padding: "6px 14px", background: isEdited ? "#D97706" : "#27272A", border: "none", borderRadius: 6, color: isEdited ? "#000" : "#52525B", fontSize: 11, fontWeight: 600, fontFamily: "inherit", cursor: isEdited ? "pointer" : "default", opacity: isSaving ? 0.5 : 1 }}>
                        {isSaving ? "Saving..." : "Save"}</button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ==================== AUTODREAM PANEL ==================== */}
      {subTab === "dream" && (
        <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
          {/* Memory stats */}
          {stats && (
            <div style={{ display: "flex", gap: 12, alignItems: "center", padding: "8px 14px", borderRadius: 8, background: "#111114", border: "1px solid #1E1E22" }}>
              <div style={{ flex: 1 }}>
                <div style={{ height: 4, borderRadius: 2, background: "#1E1E22", overflow: "hidden" }}>
                  <div style={{
                    height: "100%", borderRadius: 2, width: `${Math.min(100, (stats.chars / stats.cap_chars) * 100)}%`,
                    background: stats.chars > stats.cap_chars * 0.9 ? "#EF4444" : stats.chars > stats.cap_chars * 0.7 ? "#D97706" : "#10B981",
                  }} />
                </div>
              </div>
              <span style={{ fontSize: 10, color: "#52525B", whiteSpace: "nowrap" }}>
                {stats.chars.toLocaleString()} / {stats.cap_chars.toLocaleString()} chars · {stats.lines} / {stats.cap_lines} lines
              </span>
            </div>
          )}

          {/* Trigger button */}
          <button onClick={handleDream} disabled={dreaming}
            style={{
              padding: "12px 20px", borderRadius: 8,
              background: dreaming ? "#18181B" : "linear-gradient(135deg, #6366F118, #8B5CF618)",
              border: `1px solid ${dreaming ? "#27272A" : "#6366F140"}`,
              color: dreaming ? "#52525B" : "#A5B4FC",
              fontFamily: "inherit", fontSize: 13, fontWeight: 700, cursor: dreaming ? "default" : "pointer",
              letterSpacing: "0.04em", transition: "all 0.2s",
            }}>
            {dreaming ? (
              <span style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "center" }}>
                <span style={{ display: "inline-flex", gap: 3 }}>
                  {[0, 1, 2].map(i => <span key={i} style={{ width: 4, height: 4, borderRadius: "50%", background: "#6366F1", animation: `pulse-dot 1.2s ease-in-out ${i * 0.2}s infinite` }} />)}
                </span>
                Dreaming...
              </span>
            ) : "Run AutoDream"}
          </button>

          {dreamError && (
            <div style={{ padding: "10px 14px", borderRadius: 8, background: "#EF444412", border: "1px solid #EF444430", color: "#FCA5A5", fontSize: 12 }}>
              {dreamError}
            </div>
          )}

          {/* Proposed changes */}
          {dreamResult && !dreamResult.error && allChanges.length > 0 && (
            <>
              <div style={{ padding: "10px 14px", borderRadius: 8, background: "#6366F108", border: "1px solid #6366F130" }}>
                <div style={{ fontSize: 12, color: "#A5B4FC", lineHeight: 1.6 }}>{dreamResult.summary}</div>
                <div style={{ fontSize: 10, color: "#52525B", marginTop: 6 }}>
                  {dreamResult.token_cost} tokens · {dreamResult.conversations_processed?.length || 0} conversations scanned
                </div>
              </div>

              {allChanges.map((change, idx) => {
                const badge = BADGE_STYLES[change.type];
                return (
                  <div key={idx} style={{ borderRadius: 8, background: "#0F0F13", border: "1px solid #1E1E22", padding: "10px 14px", display: "flex", gap: 10 }}>
                    <input type="checkbox" checked={dreamChecked[idx] || false}
                      onChange={() => setDreamChecked(prev => ({ ...prev, [idx]: !prev[idx] }))}
                      style={{ accentColor: badge.color, cursor: "pointer", marginTop: 2, flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                        <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: badge.bg, color: badge.color, letterSpacing: "0.08em" }}>
                          {badge.label}
                        </span>
                        <span style={{ fontSize: 11, color: "#D97706", fontWeight: 600 }}>{change.topic}</span>
                      </div>

                      {change.type === "add" && (
                        <div style={{ fontSize: 11, color: "#6EE7B7", background: "#10B98108", padding: "6px 8px", borderRadius: 4, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                          + {change.content}
                        </div>
                      )}

                      {change.type === "update" && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          <div style={{ fontSize: 11, color: "#FCA5A5", background: "#EF444408", padding: "6px 8px", borderRadius: 4, lineHeight: 1.5, textDecoration: "line-through", whiteSpace: "pre-wrap" }}>
                            {change.old_content}
                          </div>
                          <div style={{ fontSize: 11, color: "#6EE7B7", background: "#10B98108", padding: "6px 8px", borderRadius: 4, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                            {change.new_content}
                          </div>
                        </div>
                      )}

                      {change.type === "delete" && (
                        <div style={{ fontSize: 11, color: "#FCA5A5", background: "#EF444408", padding: "6px 8px", borderRadius: 4, lineHeight: 1.5, textDecoration: "line-through", whiteSpace: "pre-wrap" }}>
                          {change.content}
                        </div>
                      )}

                      <div style={{ fontSize: 10, color: "#52525B", marginTop: 4, fontStyle: "italic" }}>{change.reason}</div>
                    </div>
                  </div>
                );
              })}

              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={handleApplyDream} disabled={applying}
                  style={{ padding: "8px 18px", background: "#10B981", color: "#000", border: "none", borderRadius: 8, fontFamily: "inherit", fontSize: 12, fontWeight: 600, cursor: "pointer", opacity: applying ? 0.5 : 1 }}>
                  {applying ? "Applying..." : `Apply Selected (${Object.values(dreamChecked).filter(Boolean).length})`}
                </button>
                <button onClick={handleRejectDream}
                  style={{ padding: "8px 18px", background: "transparent", border: "1px solid #EF444440", borderRadius: 8, color: "#FCA5A5", fontFamily: "inherit", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                  Reject All
                </button>
              </div>
            </>
          )}

          {dreamResult && dreamResult.proposed_changes?.no_changes_needed && (
            <div style={{ padding: "14px", borderRadius: 8, background: "#10B98108", border: "1px solid #10B98130", color: "#6EE7B7", fontSize: 12, textAlign: "center" }}>
              No changes needed — memory is up to date.
            </div>
          )}

          {/* Dream history */}
          <div style={{ borderRadius: 8, background: "#0F0F13", border: "1px solid #1E1E22", overflow: "hidden" }}>
            <div style={{ padding: "10px 14px", cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}
              onClick={() => setHistoryExpanded(prev => !prev)}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#52525B", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                Dream History
              </span>
              <span style={{ fontSize: 10, color: "#3F3F46", marginLeft: "auto" }}>
                {historyExpanded ? "▾" : "▸"} {dreamHistory.length} passes
              </span>
            </div>
            {historyExpanded && dreamHistory.map(d => (
              <div key={d.id} style={{ padding: "8px 14px", borderTop: "1px solid #1E1E22", display: "flex", gap: 10, alignItems: "baseline" }}>
                <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: (STATUS_COLORS[d.status] || "#71717A") + "18", color: STATUS_COLORS[d.status] || "#71717A", letterSpacing: "0.06em", textTransform: "uppercase", whiteSpace: "nowrap" }}>
                  {d.status.replace("_", " ")}
                </span>
                <span style={{ fontSize: 11, color: "#71717A", flex: 1, lineHeight: 1.4 }}>{d.summary || "No summary"}</span>
                <span style={{ fontSize: 10, color: "#3F3F46", whiteSpace: "nowrap" }}>{new Date(d.created_at).toLocaleDateString()}</span>
              </div>
            ))}
            {historyExpanded && dreamHistory.length === 0 && (
              <div style={{ padding: "12px 14px", borderTop: "1px solid #1E1E22", fontSize: 11, color: "#3F3F46", textAlign: "center" }}>No dream passes yet</div>
            )}
          </div>
        </div>
      )}

      {/* ==================== RAW CONTEXT PANEL ==================== */}
      {subTab === "raw" && (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", padding: "16px 20px", gap: 10 }}>
          <div style={{ fontSize: 11, color: "#52525B", lineHeight: 1.5 }}>
            Legacy monolithic context view. Editing here updates the raw context document, not individual memory topics.
          </div>
          <textarea value={rawContent} onChange={e => setRawContent(e.target.value)}
            style={{ flex: 1, background: "#111114", border: "1px solid #27272A", borderRadius: 8, color: "#D4D4D8", padding: "14px 16px", fontSize: 12, fontFamily: "'JetBrains Mono', monospace", resize: "none", outline: "none", lineHeight: 1.6 }} />
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <button onClick={handleRawSave} disabled={rawSaving}
              style={{ padding: "8px 18px", background: "#D97706", color: "#000", border: "none", borderRadius: 8, fontFamily: "inherit", fontSize: 12, fontWeight: 600, cursor: "pointer", opacity: rawSaving ? 0.5 : 1 }}>
              {rawSaving ? "Saving..." : "Save"}</button>
            <span style={{ fontSize: 10, color: "#3F3F46" }}>~{Math.round(rawContent.length / 4)} tokens</span>
          </div>
        </div>
      )}
    </div>
  );
}
