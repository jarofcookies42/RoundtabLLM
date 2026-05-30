import { useState, useEffect, useRef } from "react";
import { getConversations, renameConversation, deleteConversation } from "../api";

export default function ConversationSidebar({
  currentId,
  onSelect,
  onNewChat,
  refreshTrigger, // Parent can trigger refresh
}) {
  const [conversations, setConversations] = useState([]);
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const editInputRef = useRef(null);

  const fetchList = async () => {
    try {
      const list = await getConversations();
      setConversations(list);
    } catch (err) {
      console.error("Failed to load conversations:", err);
    }
  };

  // Fetch list on mount and when refreshTrigger or currentId changes
  useEffect(() => {
    fetchList();
  }, [refreshTrigger, currentId]);

  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  const handleStartRename = (conv, e) => {
    e.stopPropagation();
    setEditingId(conv.id);
    setEditTitle(conv.title);
  };

  const handleSaveRename = async (id, e) => {
    e.stopPropagation();
    if (!editTitle.trim()) return;
    try {
      await renameConversation(id, editTitle.trim());
      setEditingId(null);
      fetchList();
    } catch (err) {
      console.error("Failed to rename conversation:", err);
    }
  };

  const handleDelete = async (id, e) => {
    e.stopPropagation();
    if (!confirm("Are you sure you want to delete this conversation?")) return;
    try {
      await deleteConversation(id);
      if (currentId === id) {
        onNewChat();
      }
      fetchList();
    } catch (err) {
      console.error("Failed to delete conversation:", err);
    }
  };

  const filtered = conversations.filter((c) =>
    c.title.toLowerCase().includes(search.toLowerCase())
  );

  const formatTime = (dateStr) => {
    if (!dateStr) return "";
    try {
      const cleanStr = dateStr.includes(" ") ? dateStr.replace(" ", "T") : dateStr;
      const d = new Date(cleanStr);
      return d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    } catch (e) {
      return dateStr;
    }
  };

  if (collapsed) {
    return (
      <div style={{
        width: 48, background: "#0C0C0F", borderRight: "1px solid #141418",
        display: "flex", flexDirection: "column", alignItems: "center", padding: "12px 0", gap: 12, flexShrink: 0
      }}>
        <button
          onClick={() => setCollapsed(false)}
          title="Expand sidebar"
          style={{
            background: "transparent", border: "none", color: "#52525B",
            cursor: "pointer", fontSize: 16, fontFamily: "inherit"
          }}
        >
          »
        </button>
        <button
          onClick={onNewChat}
          title="New Chat"
          style={{
            background: "transparent", border: "1px solid #27272A", borderRadius: "50%",
            color: "#D97706", width: 28, height: 28, display: "flex", alignItems: "center",
            justifyContent: "center", cursor: "pointer", fontSize: 16, fontFamily: "inherit"
          }}
        >
          +
        </button>
      </div>
    );
  }

  return (
    <div style={{
      width: 260, background: "#0C0C0F", borderRight: "1px solid #141418",
      display: "flex", flexDirection: "column", flexShrink: 0, overflow: "hidden"
    }}>
      {/* Sidebar Header */}
      <div style={{
        padding: "16px 12px", borderBottom: "1px solid #141418",
        display: "flex", alignItems: "center", justifyContent: "space-between"
      }}>
        <button
          onClick={onNewChat}
          style={{
            flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
            background: "#D9770615", border: "1px solid #D9770640", borderRadius: 8,
            color: "#FBBF24", padding: "8px 12px", fontSize: 12, fontWeight: 600,
            cursor: "pointer", fontFamily: "inherit", transition: "all 0.2s"
          }}
          onMouseEnter={(e) => e.target.style.background = "#D9770625"}
          onMouseLeave={(e) => e.target.style.background = "#D9770615"}
        >
          <span>+</span> New Chat
        </button>
        <button
          onClick={() => setCollapsed(true)}
          title="Collapse sidebar"
          style={{
            background: "transparent", border: "none", color: "#52525B",
            cursor: "pointer", fontSize: 16, fontFamily: "inherit", padding: "0 8px"
          }}
        >
          «
        </button>
      </div>

      {/* Search Input */}
      <div style={{ padding: "8px 12px", borderBottom: "1px solid #141418" }}>
        <div style={{ position: "relative" }}>
          <input
            type="text"
            placeholder="Search threads..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              width: "100%", padding: "6px 8px 6px 26px", background: "#18181B",
              border: "1px solid #27272A", borderRadius: 6, color: "#E4E4E7",
              fontFamily: "inherit", fontSize: 11
            }}
          />
          <span style={{
            position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)",
            color: "#52525B", fontSize: 11
          }}>🔍</span>
        </div>
      </div>

      {/* Conversation List */}
      <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
        {filtered.length === 0 ? (
          <div style={{ padding: "16px", textCenter: "center", color: "#52525B", fontSize: 11, textAlign: "center" }}>
            No history found
          </div>
        ) : (
          filtered.map((conv) => {
            const isActive = conv.id === currentId;
            const isEditing = conv.id === editingId;

            return (
              <div
                key={conv.id}
                onClick={() => !isEditing && onSelect(conv.id)}
                className="sidebar-item"
                style={{
                  padding: "10px 14px", margin: "2px 8px", borderRadius: 6,
                  background: isActive ? "#18181B" : "transparent",
                  cursor: isEditing ? "default" : "pointer",
                  display: "flex", flexDirection: "column", gap: 4,
                  position: "relative", transition: "all 0.15s"
                }}
              >
                <style>{`
                  .sidebar-item:hover { background: #18181B; }
                  .sidebar-item .actions { display: none; }
                  .sidebar-item:hover .actions { display: flex; }
                `}</style>

                {isEditing ? (
                  <div style={{ display: "flex", gap: 4, alignItems: "center" }} onClick={e => e.stopPropagation()}>
                    <input
                      ref={editInputRef}
                      type="text"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleSaveRename(conv.id, e);
                        if (e.key === "Escape") setEditingId(null);
                      }}
                      style={{
                        flex: 1, background: "#09090B", border: "1px solid #D97706",
                        borderRadius: 4, color: "#E4E4E7", fontSize: 11, padding: "2px 4px",
                        fontFamily: "inherit"
                      }}
                    />
                    <button
                      onClick={(e) => handleSaveRename(conv.id, e)}
                      style={{ background: "transparent", border: "none", color: "#10B981", cursor: "pointer", fontSize: 11 }}
                    >
                      ✓
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); setEditingId(null); }}
                      style={{ background: "transparent", border: "none", color: "#EF4444", cursor: "pointer", fontSize: 11 }}
                    >
                      ✗
                    </button>
                  </div>
                ) : (
                  <>
                    <div style={{
                      color: isActive ? "#FAFAFA" : "#D4D4D8", fontSize: 12,
                      fontWeight: isActive ? 600 : 400, overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap", paddingRight: 40
                    }}>
                      {conv.title}
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontSize: 9, color: "#52525B" }}>
                        {formatTime(conv.updated_at)}
                      </span>
                      <span style={{
                        fontSize: 8, padding: "1px 4px", borderRadius: 4,
                        background: conv.mode === "overdrive" ? "#EF444415" : "#27272A50",
                        color: conv.mode === "overdrive" ? "#FCA5A5" : "#71717A",
                        fontWeight: 600
                      }}>
                        {conv.mode === "overdrive" ? "⚡ OD" : "REG"}
                      </span>
                    </div>

                    {/* Actions Menu */}
                    <div
                      className="actions"
                      style={{
                        position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)",
                        gap: 6, alignItems: "center"
                      }}
                      onClick={e => e.stopPropagation()}
                    >
                      <button
                        onClick={(e) => handleStartRename(conv, e)}
                        title="Rename"
                        style={{
                          background: "transparent", border: "none", color: "#A1A1AA",
                          cursor: "pointer", fontSize: 11, padding: 2
                        }}
                        onMouseEnter={e => e.target.style.color = "#FBBF24"}
                        onMouseLeave={e => e.target.style.color = "#A1A1AA"}
                      >
                        ✎
                      </button>
                      <button
                        onClick={(e) => handleDelete(conv.id, e)}
                        title="Delete"
                        style={{
                          background: "transparent", border: "none", color: "#A1A1AA",
                          cursor: "pointer", fontSize: 11, padding: 2
                        }}
                        onMouseEnter={e => e.target.style.color = "#EF4444"}
                        onMouseLeave={e => e.target.style.color = "#A1A1AA"}
                      >
                        🗑
                      </button>
                    </div>
                  </>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
