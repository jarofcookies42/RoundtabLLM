/**
 * useSSE — Server-Sent Events hook for streaming model responses.
 *
 * SSE event format from backend:
 *   data: {"type": "model_start", "model": "claude", "name": "Claude Sonnet 4.6"}
 *   data: {"type": "token", "model": "claude", "delta": "Hello"}
 *   data: {"type": "model_done", "model": "claude", "content": "full response"}
 *   data: {"type": "model_error", "model": "claude", "error": "timeout"}
 *   data: {"type": "round_done"}
 */
import { useRef, useCallback } from "react";

export default function useSSE({ onModelStart, onToken, onModelDone, onModelError, onRoundDone }) {
  const sourceRef = useRef(null);

  const startStream = useCallback((conversationId, { mode, anchor, protocol, enabled_models, debate_roles }) => {
    // Close any existing stream
    if (sourceRef.current) {
      sourceRef.current.close();
    }

    const token = localStorage.getItem("roundtable_token") || "";
    const params = new URLSearchParams({
      mode,
      anchor,
      protocol: protocol || "roundtable",
      enabled_models: enabled_models.join(","),
      token,
    });
    if (debate_roles) {
      params.set("debate_roles", JSON.stringify(debate_roles));
    }

    const url = `/chat/stream/${conversationId}?${params}`;
    const source = new EventSource(url);
    sourceRef.current = source;

    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        switch (data.type) {
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
            onRoundDone?.();
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
  }, [onModelStart, onToken, onModelDone, onModelError, onRoundDone]);

  return { startStream };
}
