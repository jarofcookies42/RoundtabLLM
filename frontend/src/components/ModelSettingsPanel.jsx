import React from "react";
import { MODEL_META } from "../App";

export default function ModelSettingsPanel({ enabledModels, overrides, onChange, mode }) {
  const handleClaudeChange = (field, val) => {
    const nextClaude = { ...overrides.claude };
    if (field === "thinking_enabled") {
      if (val) {
        if (mode === "overdrive") {
          nextClaude.thinking = { type: "adaptive" };
          nextClaude.effort = nextClaude.effort || "max";
        } else {
          nextClaude.thinking = { type: "enabled", budget_tokens: 4096 };
        }
      } else {
        nextClaude.thinking = null;
      }
    } else if (field === "budget_tokens") {
      nextClaude.thinking = { type: "enabled", budget_tokens: parseInt(val) };
    } else if (field === "effort") {
      nextClaude.effort = val;
    } else if (field === "temperature") {
      nextClaude.temperature = parseFloat(val);
    }
    onChange("claude", nextClaude);
  };

  const handleGptChange = (field, val) => {
    const nextGpt = { ...overrides.gpt };
    if (field === "reasoning_effort") {
      nextGpt.reasoning_effort = val;
    } else if (field === "temperature") {
      nextGpt.temperature = parseFloat(val);
    }
    onChange("gpt", nextGpt);
  };

  const handleGeminiChange = (field, val) => {
    const nextGemini = { ...overrides.gemini };
    if (field === "thinking_level") {
      nextGemini.thinking_level = val;
    } else if (field === "temperature") {
      nextGemini.temperature = parseFloat(val);
    }
    onChange("gemini", nextGemini);
  };

  const handleGrokChange = (field, val) => {
    const nextGrok = { ...overrides.grok };
    if (field === "temperature") {
      nextGrok.temperature = parseFloat(val);
    } else if (field === "thinking_enabled") {
      nextGrok.thinking = val ? { type: "adaptive" } : null;
    }
    onChange("grok", nextGrok);
  };

  const handleOllamaChange = (field, val) => {
    const nextOllama = { ...overrides.ollama };
    if (field === "model_id") {
      nextOllama.model_id = val;
    } else if (field === "temperature") {
      nextOllama.temperature = parseFloat(val);
    }
    onChange("ollama", nextOllama);
  };

  if (enabledModels.length === 0) return null;

  return (
    <div style={{
      padding: "16px 20px",
      background: "#08080B",
      borderBottom: "1px solid #141418",
      display: "flex",
      flexDirection: "column",
      gap: 16,
      animation: "slide-down 0.2s ease-out",
    }}>
      <style>{`
        @keyframes slide-down { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
        .config-group { display: flex; flex-direction: column; gap: 10px; flex: 1; min-width: 200px; padding: 12px; background: #0C0C0F; border: 1px solid #18181B; border-radius: 8px; }
        .config-title { font-family: 'Sora', sans-serif; font-size: 11px; font-weight: 700; display: flex; align-items: center; gap: 6px; text-transform: uppercase; letter-spacing: 0.05em; }
        .config-label { font-size: 11px; color: #71717A; display: flex; justify-content: space-between; align-items: center; }
        .config-select { background: #18181B; border: 1px solid #27272A; border-radius: 6px; color: #E4E4E7; padding: 6px 10px; font-size: 11px; font-family: inherit; outline: none; cursor: pointer; }
        .config-slider { width: 100%; accent-color: #D97706; cursor: pointer; }
      `}</style>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        {enabledModels.includes("claude") && (
          <div className="config-group" style={{ borderLeft: `2.5px solid ${MODEL_META.claude.color}` }}>
            <div className="config-title" style={{ color: MODEL_META.claude.color }}>
              <span style={{ fontSize: 13 }}>{MODEL_META.claude.icon}</span> Claude Config
            </div>
            
            <div className="config-label">
              <span>Thinking/Reasoning</span>
              <input 
                type="checkbox" 
                checked={overrides.claude?.thinking !== null && (overrides.claude?.thinking?.type === "enabled" || overrides.claude?.thinking?.type === "adaptive" || overrides.claude?.thinking === undefined)}
                onChange={(e) => handleClaudeChange("thinking_enabled", e.target.checked)}
                style={{ accentColor: "#D97706", cursor: "pointer" }}
              />
            </div>

            {mode !== "overdrive" && (overrides.claude?.thinking?.type === "enabled" || overrides.claude?.thinking === undefined) && overrides.claude?.thinking !== null && (
              <div className="config-label" style={{ flexDirection: "column", gap: 4, alignItems: "stretch", width: "100%" }}>
                <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
                  <span>Budget Tokens</span>
                  <span style={{ color: "#D97706", fontWeight: 600 }}>
                    {overrides.claude?.thinking?.budget_tokens ?? 4096}
                  </span>
                </div>
                <input 
                  type="range" 
                  min="1024" 
                  max="16384" 
                  step="1024"
                  value={overrides.claude?.thinking?.budget_tokens ?? 4096}
                  onChange={(e) => handleClaudeChange("budget_tokens", e.target.value)}
                  className="config-slider"
                />
              </div>
            )}

            {mode === "overdrive" && overrides.claude?.thinking !== null && (
              <div className="config-label" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
                <span>Reasoning Effort</span>
                <select 
                  value={overrides.claude?.effort ?? "max"}
                  onChange={(e) => handleClaudeChange("effort", e.target.value)}
                  className="config-select"
                >
                  <option value="low">low</option>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                  <option value="max">max</option>
                </select>
              </div>
            )}

            <div className="config-label" style={{ flexDirection: "column", gap: 4, alignItems: "stretch", width: "100%", marginTop: 4 }}>
              <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
                <span>Temperature</span>
                <span style={{ color: overrides.claude?.thinking !== null && (overrides.claude?.thinking?.type === "enabled" || overrides.claude?.thinking?.type === "adaptive" || overrides.claude?.thinking === undefined) ? "#52525B" : MODEL_META.claude.color, fontWeight: 600 }}>
                  {overrides.claude?.thinking !== null && (overrides.claude?.thinking?.type === "enabled" || overrides.claude?.thinking?.type === "adaptive" || overrides.claude?.thinking === undefined)
                    ? "Locked"
                    : (overrides.claude?.temperature ?? 0.7).toFixed(1)}
                </span>
              </div>
              <input 
                type="range" 
                min="0.0" 
                max="1.0" 
                step="0.1"
                disabled={overrides.claude?.thinking !== null && (overrides.claude?.thinking?.type === "enabled" || overrides.claude?.thinking?.type === "adaptive" || overrides.claude?.thinking === undefined)}
                value={overrides.claude?.thinking !== null && (overrides.claude?.thinking?.type === "enabled" || overrides.claude?.thinking?.type === "adaptive" || overrides.claude?.thinking === undefined) ? 0.0 : (overrides.claude?.temperature ?? 0.7)}
                onChange={(e) => handleClaudeChange("temperature", e.target.value)}
                className="config-slider"
                style={{
                  accentColor: MODEL_META.claude.color,
                  opacity: overrides.claude?.thinking !== null && (overrides.claude?.thinking?.type === "enabled" || overrides.claude?.thinking?.type === "adaptive" || overrides.claude?.thinking === undefined) ? 0.3 : 1
                }}
              />
              {overrides.claude?.thinking !== null && (overrides.claude?.thinking?.type === "enabled" || overrides.claude?.thinking?.type === "adaptive" || overrides.claude?.thinking === undefined) && (
                <div style={{ fontSize: 9, color: "#52525B" }}>
                  Not supported by Anthropic API when reasoning is enabled.
                </div>
              )}
            </div>
          </div>
        )}

        {enabledModels.includes("gpt") && (
          <div className="config-group" style={{ borderLeft: `2.5px solid ${MODEL_META.gpt.color}` }}>
            <div className="config-title" style={{ color: MODEL_META.gpt.color }}>
              <span style={{ fontSize: 13 }}>{MODEL_META.gpt.icon}</span> GPT Config
            </div>
            
            <div className="config-label">
              <span>Reasoning Effort</span>
              <select 
                value={overrides.gpt?.reasoning_effort ?? (mode === "overdrive" ? "high" : "none")}
                onChange={(e) => handleGptChange("reasoning_effort", e.target.value)}
                className="config-select"
              >
                <option value="none">none</option>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </div>

            <div className="config-label" style={{ flexDirection: "column", gap: 4, alignItems: "stretch", width: "100%" }}>
              <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
                <span>Temperature</span>
                <span style={{ color: "#52525B", fontWeight: 600 }}>Locked</span>
              </div>
              <input 
                type="range" 
                min="0.0" 
                max="2.0" 
                step="0.1"
                disabled={true}
                value={1.0}
                className="config-slider"
                style={{ accentColor: MODEL_META.gpt.color, opacity: 0.3 }}
              />
              <div style={{ fontSize: 9, color: "#52525B" }}>
                Locked at 1.0 (reasoning model restriction).
              </div>
            </div>
          </div>
        )}

        {enabledModels.includes("gemini") && (
          <div className="config-group" style={{ borderLeft: `2.5px solid ${MODEL_META.gemini.color}` }}>
            <div className="config-title" style={{ color: MODEL_META.gemini.color }}>
              <span style={{ fontSize: 13 }}>{MODEL_META.gemini.icon}</span> Gemini Config
            </div>
            
            <div className="config-label">
              <span>Thinking Level</span>
              <select 
                value={overrides.gemini?.thinking_level ?? (mode === "overdrive" ? "high" : "low")}
                onChange={(e) => handleGeminiChange("thinking_level", e.target.value)}
                className="config-select"
              >
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </div>

            <div className="config-label" style={{ flexDirection: "column", gap: 4, alignItems: "stretch", width: "100%" }}>
              <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
                <span>Temperature</span>
                <span style={{ color: "#52525B", fontWeight: 600 }}>Locked</span>
              </div>
              <input 
                type="range" 
                min="0.0" 
                max="2.0" 
                step="0.1"
                disabled={true}
                value={1.0}
                className="config-slider"
                style={{ accentColor: MODEL_META.gemini.color, opacity: 0.3 }}
              />
              <div style={{ fontSize: 9, color: "#52525B" }}>
                Locked at 1.0 to prevent generation loops.
              </div>
            </div>
          </div>
        )}

        {enabledModels.includes("grok") && (
          <div className="config-group" style={{ borderLeft: `2.5px solid ${MODEL_META.grok.color}` }}>
            <div className="config-title" style={{ color: MODEL_META.grok.color }}>
              <span style={{ fontSize: 13 }}>{MODEL_META.grok.icon}</span> Grok Config
            </div>

            <div className="config-label">
              <span>Thinking/Reasoning</span>
              <input 
                type="checkbox" 
                checked={
                  overrides.grok?.thinking !== undefined
                    ? overrides.grok.thinking !== null
                    : (mode === "overdrive")
                }
                onChange={(e) => handleGrokChange("thinking_enabled", e.target.checked)}
                style={{ accentColor: MODEL_META.grok.color, cursor: "pointer" }}
              />
            </div>
            
            <div className="config-label" style={{ flexDirection: "column", gap: 4, alignItems: "stretch", width: "100%" }}>
              <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
                <span>Temperature</span>
                <span style={{ color: MODEL_META.grok.color, fontWeight: 600 }}>
                  {(overrides.grok?.temperature ?? (mode === "overdrive" ? 0.9 : 0.7)).toFixed(1)}
                </span>
              </div>
              <input 
                type="range" 
                min="0.0" 
                max="2.0" 
                step="0.1"
                value={overrides.grok?.temperature ?? (mode === "overdrive" ? 0.9 : 0.7)}
                onChange={(e) => handleGrokChange("temperature", e.target.value)}
                className="config-slider"
                style={{ accentColor: MODEL_META.grok.color }}
              />
            </div>
          </div>
        )}

        {enabledModels.includes("ollama") && (
          <div className="config-group" style={{ borderLeft: `2.5px solid ${MODEL_META.ollama.color}` }}>
            <div className="config-title" style={{ color: MODEL_META.ollama.color }}>
              <span style={{ fontSize: 13 }}>{MODEL_META.ollama.icon}</span> Ollama Config
            </div>
            
            <div className="config-label" style={{ flexDirection: "column", gap: 4, alignItems: "stretch", width: "100%" }}>
              <span>Local Model ID</span>
              <input 
                type="text" 
                value={overrides.ollama?.model_id ?? (mode === "overdrive" ? "llama3:8b" : "gemma2:2b")}
                onChange={(e) => handleOllamaChange("model_id", e.target.value)}
                className="config-select"
                style={{ width: "100%", textTransform: "none", fontSize: 11 }}
                placeholder="e.g. llama3"
              />
            </div>
            
            <div className="config-label" style={{ flexDirection: "column", gap: 4, alignItems: "stretch", width: "100%" }}>
              <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
                <span>Temperature</span>
                <span style={{ color: MODEL_META.ollama.color, fontWeight: 600 }}>
                  {(overrides.ollama?.temperature ?? 0.7).toFixed(1)}
                </span>
              </div>
              <input 
                type="range" 
                min="0.0" 
                max="2.0" 
                step="0.1"
                value={overrides.ollama?.temperature ?? 0.7}
                onChange={(e) => handleOllamaChange("temperature", e.target.value)}
                className="config-slider"
                style={{ accentColor: MODEL_META.ollama.color }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
