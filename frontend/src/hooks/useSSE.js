/**
 * useSSE — Server-Sent Events hook for streaming model responses.
 *
 * SSE event format from backend:
 *   data: {"type": "compaction", "messages_compacted": N, "summary_tokens": T}
 *   data: {"type": "context_loaded", "topics": ["thesis", "projects"]}
 *   data: {"type": "model_start", "model": "claude", "name": "Claude Sonnet 4.6"}
 *   data: {"type": "token", "model": "claude", "delta": "Hello"}
 *   data: {"type": "model_done", "model": "claude", "content": "full response"}
 *   data: {"type": "model_error", "model": "claude", "error": "timeout"}
 *   data: {"type": "round_done", "context_tokens": N, "context_limit": 30000}
 */
import { useRef, useCallback } from "react";

export default function useSSE({ onModelStart, onToken, onModelDone, onModelError, onContextLoaded, onCompaction, onRoundDone }) {
  const sourceRef = useRef(null);

  const startStream = useCallback((conversationId, { mode, anchor, protocol, enabled_models, debate_roles, context_mode, selected_topics }) => {
    if (sourceRef.current) {
      sourceRef.current.close();
    }

    const token = localStorage.getItem("roundtable_token") || "";
    const params = new URLSearchParams({
      mode,
      anchor,
      protocol: protocol || "roundtable",
      enabled_models: enabled_models.join(","),
      context_mode: context_mode || "full",
      token,
    });
    if (debate_roles) {
      params.set("debate_roles", JSON.stringify(debate_roles));
    }
    if (selected_topics && selected_topics.length > 0) {
      params.set("selected_topics", JSON.stringify(selected_topics));
    }

    const url = `/chat/stream/${conversationId}?${params}`;
    const source = new EventSource(url);
    sourceRef.current = source;

    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        switch (data.type) {
          case "compaction":
            onCompaction?.(data);
            break;
          case "context_loaded":
            onContextLoaded?.(data.topics);
            break;
          case "model_start":
            onModelStart?.(data.model, data.name, data.protocol_role);
            break;
          case "token":
            onToken?.(data.model, data.delta);
            break;
          case "model_done":
            onModelDone?.(data.model, data.content, data.protocol_role);
            break;
          case "model_error":
            onModelError?.(data.model, data.error);
            break;
          case "round_done":
            onRoundDone?.(data.context_tokens, data.context_limit);
            source.close();
            sourceRef.current = null;
            break;
        }
      } catch (err) {
        console.error("SSE parse error:", err, event.data);
      }
    };

    source.onerror = () => {
      source.close();
      sourceRef.current = null;
      onRoundDone?.();
    };
  }, [onModelStart, onToken, onModelDone, onModelError, onContextLoaded, onCompaction, onRoundDone]);

  return { startStream };
}
