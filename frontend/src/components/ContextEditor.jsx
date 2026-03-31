/**
 * ContextEditor — View and edit the shared memory/context document.
 *
 * This markdown document gets injected into every model's system prompt.
 * Pre-seeded from jack_context.md (Jack's comprehensive briefing).
 * Editable in-app. Supports importing .txt/.json/.md files to append.
 */
import { useState, useEffect } from "react";
import { getContext, updateContext } from "../api";

export default function ContextEditor() {
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    getContext()
      .then(res => { setContent(res.content); setLoaded(true); })
      .catch(err => console.error("Failed to load context:", err));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateContext(content);
    } catch (err) {
      console.error("Failed to save context:", err);
    }
    setSaving(false);
  };

  const handleImport = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result;
      if (typeof text === "string") {
        setContent(prev => prev + "\n\n---\n# Imported: " + file.name + "\n" + text);
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", padding: 20, gap: 12, overflow: "hidden" }}>
      <div>
        <div style={{ fontFamily: "'Sora', sans-serif", fontWeight: 700, fontSize: 15, marginBottom: 4 }}>
          Shared memory context
        </div>
        <div style={{ fontSize: 11, color: "#52525B", lineHeight: 1.5 }}>
          This document gets injected into every model's system prompt. Edit it to shape what they know about you.
        </div>
      </div>

      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        disabled={!loaded}
        style={{
          flex: 1, background: "#111114", border: "1px solid #27272A", borderRadius: 10,
          color: "#D4D4D8", padding: 16, fontSize: 12.5, fontFamily: "inherit",
          outline: "none", resize: "none", lineHeight: 1.7,
        }}
      />

      <div style={{ display: "flex", gap: 8, flexShrink: 0, alignItems: "center" }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            background: "#D97706", color: "#08080B", border: "none", borderRadius: 8,
            padding: "8px 20px", fontFamily: "inherit", fontSize: 12, fontWeight: 600,
            cursor: saving ? "not-allowed" : "pointer", opacity: saving ? 0.5 : 1,
          }}
        >
          {saving ? "Saving..." : "Save"}
        </button>
        <label style={{
          background: "#1E1E22", border: "1px solid #27272A", borderRadius: 8,
          color: "#71717A", padding: "8px 16px", cursor: "pointer",
          fontFamily: "inherit", fontSize: 11, fontWeight: 500,
        }}>
          Import .txt / .md / .json
          <input type="file" accept=".txt,.json,.md" style={{ display: "none" }} onChange={handleImport} />
        </label>
        <div style={{ flex: 1 }} />
        <div style={{ fontSize: 10, color: "#3F3F46" }}>
          ~{Math.round(content.length / 4)} tokens
        </div>
      </div>
    </div>
  );
}
