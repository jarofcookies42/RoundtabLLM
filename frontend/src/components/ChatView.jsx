/**
 * ChatView — Message list with auto-scroll + text input.
 * Supports file attachment via drag-and-drop or click (📎 button).
 * Supported: .md, .txt, .py, .json, .pdf — prepended to message as artifact.
 *
 * Props:
 *   messages[]     - array of {role, model, name, content, isError, id}
 *   activeModel    - model key currently generating (null when idle)
 *   anchorModel    - model key in anchor position (gets badge)
 *   sending        - boolean, disables input while round is active
 *   onSend(text)   - callback when user submits
 *   inputRef       - ref for the input element (for auto-focus)
 *   enabledModels  - list of enabled model keys
 */
import { useState, useEffect, useRef, useCallback } from "react";
import MessageBubble from "./MessageBubble";
import { MODEL_META } from "../App";

const ALLOWED_TEXT_EXTS = [".md", ".txt", ".py", ".json", ".js", ".ts", ".jsx", ".tsx", ".css", ".html", ".yaml", ".yml", ".toml", ".csv"];
const MAX_TEXT_SIZE = 100 * 1024; // 100KB
const MAX_PDF_SIZE = 1 * 1024 * 1024; // 1MB

export default function ChatView({ messages, activeModel, anchorModel, sending, onSend, inputRef, enabledModels }) {
  const chatEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const [attachedFile, setAttachedFile] = useState(null); // { name, content }
  const [dragOver, setDragOver] = useState(false);

  const processFile = useCallback((file) => {
    const ext = "." + file.name.split(".").pop().toLowerCase();
    const isPdf = ext === ".pdf";
    const isText = ALLOWED_TEXT_EXTS.includes(ext);

    if (!isPdf && !isText) {
      alert(`Unsupported file type: ${ext}\nSupported: ${ALLOWED_TEXT_EXTS.join(", ")}, .pdf`);
      return;
    }
    if (isPdf && file.size > MAX_PDF_SIZE) {
      alert(`PDF too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Max 1MB.`);
      return;
    }
    if (isText && file.size > MAX_TEXT_SIZE) {
      alert(`File too large (${(file.size / 1024).toFixed(0)}KB). Max 100KB for text files.`);
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      setAttachedFile({ name: file.name, content: e.target.result });
    };
    if (isPdf) {
      // For PDF, read as text (best effort — actual PDF binary won't be useful, but backend could handle it)
      reader.readAsText(file);
    } else {
      reader.readAsText(file);
    }
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) processFile(file);
  }, [processFile]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => setDragOver(false), []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, activeModel]);

  const buildMessage = (text) => {
    if (!attachedFile) return text;
    const prefix = `[Attached: ${attachedFile.name}]\n\`\`\`\n${attachedFile.content}\n\`\`\`\n\n`;
    return prefix + text;
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend(buildMessage(e.target.value));
      e.target.value = "";
      setAttachedFile(null);
    }
  };

  return (
    <div
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden", position: "relative" }}
    >
      {/* Drag overlay */}
      {dragOver && (
        <div style={{
          position: "absolute", inset: 0, zIndex: 50,
          background: "rgba(217, 119, 6, 0.08)", border: "2px dashed #D97706",
          borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center",
          pointerEvents: "none",
        }}>
          <span style={{ color: "#D97706", fontFamily: "'Sora', sans-serif", fontWeight: 700, fontSize: 15 }}>
            Drop file to attach
          </span>
        </div>
      )}

      {/* Message list */}
      <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px", display: "flex", flexDirection: "column", gap: 5 }}>
        {messages.length === 0 && (
          <div style={{
            flex: 1, display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", gap: 10, textAlign: "center", padding: 32,
          }}>
            <span style={{ fontSize: 44, opacity: 0.25, color: "#D97706" }}>⬡</span>
            <div style={{ fontFamily: "'Sora', sans-serif", fontSize: 16, fontWeight: 700, color: "#3F3F46" }}>
              Start a roundtable
            </div>
            <div style={{ fontSize: 12, color: "#27272A", maxWidth: 360, lineHeight: 1.6 }}>
              Every active model responds in sequence. The last model is the anchor — it synthesizes everyone else's takes.
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} isAnchor={msg.model === anchorModel} />
        ))}

        {/* Typing indicator */}
        {activeModel && (
          <div className="msg-enter" style={{
            display: "flex", gap: 10, padding: "12px 14px", borderRadius: 10,
            background: "#0F0F13",
            borderLeft: `2.5px solid ${MODEL_META[activeModel]?.color || "#444"}`,
          }}>
            <div style={{
              width: 28, height: 28, borderRadius: 7,
              background: (MODEL_META[activeModel]?.color || "#444") + "18",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 14, color: MODEL_META[activeModel]?.color || "#888",
            }}>
              {MODEL_META[activeModel]?.icon || "?"}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{
                fontSize: 10, fontWeight: 600,
                color: MODEL_META[activeModel]?.color,
                letterSpacing: "0.07em", textTransform: "uppercase",
              }}>
                {MODEL_META[activeModel]?.name}
              </span>
              <span style={{ display: "flex", gap: 3 }}>
                {[0, 1, 2].map(i => (
                  <span key={i} style={{
                    width: 4, height: 4, borderRadius: "50%",
                    background: MODEL_META[activeModel]?.accent,
                    animation: `pulse-dot 1.2s ease-in-out ${i * 0.2}s infinite`,
                  }} />
                ))}
              </span>
            </div>
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      {/* Attached file chip */}
      {attachedFile && (
        <div style={{
          padding: "6px 20px", borderTop: "1px solid #141418", background: "#0C0C0F",
          display: "flex", alignItems: "center", gap: 8, flexShrink: 0,
        }}>
          <span style={{
            fontSize: 11, color: "#D97706", background: "#D9770618",
            padding: "3px 10px", borderRadius: 6, display: "flex", alignItems: "center", gap: 6,
          }}>
            <span style={{ fontSize: 13 }}>&#128206;</span>
            {attachedFile.name}
            <button
              onClick={() => setAttachedFile(null)}
              style={{
                background: "none", border: "none", color: "#71717A", cursor: "pointer",
                fontSize: 13, padding: 0, lineHeight: 1, fontFamily: "inherit",
              }}
            >&times;</button>
          </span>
          <span style={{ fontSize: 10, color: "#52525B" }}>
            {(attachedFile.content.length / 1024).toFixed(1)}KB
          </span>
        </div>
      )}

      {/* Input bar */}
      <div style={{
        padding: "12px 20px", borderTop: "1px solid #141418",
        display: "flex", gap: 10, alignItems: "center", background: "#0C0C0F", flexShrink: 0,
      }}>
        <input
          type="file"
          ref={fileInputRef}
          style={{ display: "none" }}
          accept={[...ALLOWED_TEXT_EXTS, ".pdf"].join(",")}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) processFile(file);
            e.target.value = "";
          }}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={sending}
          title="Attach file"
          style={{
            background: "transparent", border: "1px solid #27272A", borderRadius: 8,
            color: attachedFile ? "#D97706" : "#52525B", cursor: "pointer",
            padding: "10px 12px", fontSize: 15, lineHeight: 1, transition: "all 0.2s",
          }}
          onMouseEnter={e => { e.target.style.borderColor = "#D97706"; e.target.style.color = "#D97706"; }}
          onMouseLeave={e => { e.target.style.borderColor = "#27272A"; e.target.style.color = attachedFile ? "#D97706" : "#52525B"; }}
        >&#128206;</button>
        <input
          ref={inputRef}
          placeholder={enabledModels.length === 0 ? "Enable at least one model..." : attachedFile ? `Message about ${attachedFile.name}...` : "Message the roundtable..."}
          onKeyDown={handleKeyDown}
          disabled={sending || enabledModels.length === 0}
          style={{
            flex: 1, background: "#111114", border: "1px solid #27272A", borderRadius: 10,
            color: "#E4E4E7", padding: "13px 16px", fontSize: 13, fontFamily: "inherit",
            outline: "none",
          }}
        />
        <button
          onClick={() => {
            if (inputRef.current) {
              onSend(buildMessage(inputRef.current.value));
              inputRef.current.value = "";
              setAttachedFile(null);
            }
          }}
          disabled={sending || enabledModels.length === 0}
          style={{
            background: "#D97706", color: "#08080B", border: "none", borderRadius: 10,
            padding: "13px 22px", fontFamily: "inherit", fontWeight: 700, fontSize: 12,
            cursor: sending ? "not-allowed" : "pointer", opacity: sending ? 0.35 : 1,
            letterSpacing: "0.06em",
          }}
        >
          {sending ? "···" : "SEND"}
        </button>
      </div>
    </div>
  );
}
