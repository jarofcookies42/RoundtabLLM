import os
import sys
import json
import unittest
from datetime import datetime, timedelta

# Override DATABASE_URL to use a temporary SQLite file database for testing
os.environ["DATABASE_URL"] = "sqlite:///test_temp.db"
os.environ["AUTH_TOKEN"] = "test-token"

# Ensure the parent directory is in sys.path so we can import backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, SQLModel, create_engine, select
from fastapi.testclient import TestClient

from backend.config import AUTH_TOKEN, DATABASE_URL
from backend.main import app
from backend.database import engine, init_db
from backend.models import Conversation, Message, MemoryFile, DreamLog
from backend.llm.router import _format_provider_error
from backend.memory.autodream import generate_dream, apply_dream_changes, MEMORY_CAP_CHARS, MEMORY_CAP_LINES


class TestRoundtabLLM(unittest.TestCase):
    def setUp(self):
        # Force dispose of any old connections first
        engine.dispose()
        SQLModel.metadata.drop_all(engine)
        SQLModel.metadata.create_all(engine)
        
        # Populate necessary seed data for testing
        with Session(engine) as session:
            # Seed topic files
            session.add(MemoryFile(key="identity", content="Identity description.", file_type="topic"))
            session.add(MemoryFile(key="thesis", content="Thesis details.", file_type="topic"))
            session.commit()

        # Initialize the test client
        self.client = TestClient(app)
        self.auth_headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}

    def tearDown(self):
        SQLModel.metadata.drop_all(engine)
        engine.dispose()
        if os.path.exists("test_temp.db"):
            try:
                os.remove("test_temp.db")
            except Exception:
                pass

    def test_format_provider_error(self):
        # 1. Test generic exception
        e = Exception("Something went wrong")
        err_info = _format_provider_error(e)
        self.assertEqual(err_info["type"], "unknown")
        self.assertEqual(err_info["provider_message"], "Something went wrong")
        self.assertIsNone(err_info["status"])

        # 2. Test status code extraction from mock attributes
        class CustomAPIError(Exception):
            status_code = 429
            message = "Too Many Requests"
            
        e2 = CustomAPIError("Rate limited")
        err_info2 = _format_provider_error(e2)
        self.assertEqual(err_info2["type"], "rate_limit")
        self.assertEqual(err_info2["status"], 429)

        # 3. Test content policy / filter heuristic
        e3 = Exception("Content safety policy violation detected")
        err_info3 = _format_provider_error(e3)
        self.assertEqual(err_info3["type"], "content_filter")

    def test_stale_dream_lock_timeout(self):
        with Session(engine) as session:
            # Create a stale pending dream
            stale_time = datetime.utcnow() - timedelta(minutes=40)
            stale_dream = DreamLog(status="pending", created_at=stale_time)
            session.add(stale_dream)
            session.commit()
            
            # Run generate_dream — it should clean up the stale dream and fail it,
            # then try to generate a new dream (returning error about no transcripts instead of 'already in progress')
            result = self.client.post("/memory/dream", headers=self.auth_headers)
            self.assertEqual(result.status_code, 400)  # Should return 400 (no new conversations)
            
            # Check database state for the stale dream
            session.refresh(stale_dream)
            self.assertEqual(stale_dream.status, "failed")
            self.assertIn("timed out", stale_dream.summary.lower())

    def test_memory_cap_pre_enforcement(self):
        with Session(engine) as session:
            # 1. Create a dream log with proposed changes that exceed cap
            oversize_content = "x" * (MEMORY_CAP_CHARS + 100)
            proposed_changes = {
                "additions": [{"topic": "identity", "content": oversize_content}],
                "updates": [],
                "deletions": []
            }
            dream = DreamLog(status="pending", proposed_changes=json.dumps(proposed_changes))
            session.add(dream)
            session.commit()
            
            # 2. Attempt to apply the oversize change
            result = apply_dream_changes(session, dream.id, [0])
            self.assertIn("error", result)
            self.assertIn("Applying these changes would exceed memory cap", result["error"])
            
            # Verify status in database
            session.refresh(dream)
            self.assertEqual(dream.status, "failed")
            self.assertIn("would exceed memory cap", dream.summary)

            # 3. Create a valid dream log that does not exceed cap
            valid_changes = {
                "additions": [{"topic": "identity", "content": "Clean addition."}],
                "updates": [],
                "deletions": []
            }
            dream2 = DreamLog(status="pending", proposed_changes=json.dumps(valid_changes))
            session.add(dream2)
            session.commit()

            # 4. Verify successful application of valid changes
            result2 = apply_dream_changes(session, dream2.id, [0])
            self.assertNotIn("error", result2)
            self.assertEqual(result2["status"], "approved")
            
            # Check content updated
            identity_file = session.exec(select(MemoryFile).where(MemoryFile.key == "identity")).first()
            self.assertIn("Clean addition.", identity_file.content)

    def test_conversation_locking_and_mutations(self):
        # 1. Create conversation (first message)
        payload = {
            "message": "Hello, this is thread start",
            "mode": "regular",
            "anchor": "knowledge",
            "protocol": "roundtable",
            "enabled_models": ["claude"]
        }
        res = self.client.post("/chat", json=payload, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        conv_id = data["conversation_id"]
        self.assertEqual(data["mode"], "regular")
        self.assertEqual(data["protocol"], "roundtable")

        # 2. Attempt continuation with different settings (should lock and preserve original)
        payload_cont = {
            "message": "Continuation message",
            "conversation_id": conv_id,
            "mode": "overdrive",
            "anchor": "abstract",
            "protocol": "debate",
            "enabled_models": ["claude"]
        }
        res_cont = self.client.post("/chat", json=payload_cont, headers=self.auth_headers)
        self.assertEqual(res_cont.status_code, 200)
        data_cont = res_cont.json()
        
        # Verify settings were NOT updated to overdrive/debate
        self.assertEqual(data_cont["mode"], "regular")
        self.assertEqual(data_cont["protocol"], "roundtable")

        # 3. Test list conversations endpoint filters out archived ones
        res_list = self.client.get("/conversations", headers=self.auth_headers)
        self.assertEqual(res_list.status_code, 200)
        list_data = res_list.json()
        self.assertEqual(len(list_data), 1)
        self.assertEqual(list_data[0]["title"], "Hello, this is thread start")

        # 4. Test PATCH rename endpoint
        res_patch = self.client.patch(f"/conversations/{conv_id}", json={"title": "Renamed Thread"}, headers=self.auth_headers)
        self.assertEqual(res_patch.status_code, 200)
        
        # Check title changed in list
        res_list2 = self.client.get("/conversations", headers=self.auth_headers)
        self.assertEqual(res_list2.json()[0]["title"], "Renamed Thread")

        # 5. Test DELETE soft archiving endpoint
        res_delete = self.client.delete(f"/conversations/{conv_id}", headers=self.auth_headers)
        self.assertEqual(res_delete.status_code, 200)

        # Check list is now empty (archived)
        res_list3 = self.client.get("/conversations", headers=self.auth_headers)
        self.assertEqual(len(res_list3.json()), 0)

    def test_forced_dissent_and_overrides(self):
        # 1. Create a conversation with forced_dissent=True
        payload = {
            "message": "Verify dissent",
            "mode": "regular",
            "anchor": "knowledge",
            "protocol": "roundtable",
            "enabled_models": ["claude"],
            "forced_dissent": True
        }
        res = self.client.post("/chat", json=payload, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        conv_id = data["conversation_id"]
        self.assertTrue(data["forced_dissent"])

        # 2. Check that list conversations returns it correctly
        res_list = self.client.get("/conversations", headers=self.auth_headers)
        self.assertEqual(res_list.status_code, 200)
        list_data = res_list.json()
        self.assertTrue(list_data[0]["forced_dissent"])

        # 3. Try continuing with locked config check (should lock and warn, keeping True)
        payload_cont = {
            "message": "Continue",
            "conversation_id": conv_id,
            "mode": "regular",
            "anchor": "knowledge",
            "protocol": "roundtable",
            "enabled_models": ["claude"],
            "forced_dissent": False
        }
        res_cont = self.client.post("/chat", json=payload_cont, headers=self.auth_headers)
        self.assertEqual(res_cont.status_code, 200)
        self.assertTrue(res_cont.json()["forced_dissent"])

    def test_resolve_thinking_config(self):
        from backend.llm.claude import resolve_thinking_config
        from backend.config import ModelConfig

        # 1. Non-Opus model with thinking enabled
        cfg_regular = ModelConfig(
            model_id="claude-sonnet-4-6",
            provider="anthropic",
            display_name="Claude Sonnet 4.6",
            color="#D97706",
            icon="◈",
            thinking={"type": "enabled", "budget_tokens": 4096}
        )
        thinking, effort = resolve_thinking_config(cfg_regular)
        self.assertEqual(thinking, {"type": "enabled", "budget_tokens": 4096})
        self.assertIsNone(effort)

        # 2. Opus model with adaptive thinking and effort
        cfg_overdrive = ModelConfig(
            model_id="claude-opus-4-8",
            provider="anthropic",
            display_name="Claude Opus 4.8",
            color="#D97706",
            icon="◈",
            thinking={"type": "adaptive"},
            effort="max"
        )
        thinking2, effort2 = resolve_thinking_config(cfg_overdrive)
        self.assertEqual(thinking2, {"type": "adaptive"})
        self.assertEqual(effort2, "max")

        # 3. Coercion: Opus model but overrides specify type: "enabled" with budget_tokens
        cfg_coerced = ModelConfig(
            model_id="claude-opus-4-8",
            provider="anthropic",
            display_name="Claude Opus 4.8",
            color="#D97706",
            icon="◈",
            thinking={"type": "enabled", "budget_tokens": 8192},
            effort=None
        )
        thinking3, effort3 = resolve_thinking_config(cfg_coerced)
        self.assertEqual(thinking3, {"type": "adaptive"})
        self.assertNotIn("budget_tokens", thinking3)
        self.assertEqual(effort3, "max")  # Defaults to max for Opus if not specified

        # 4. Grok model resolution test
        from backend.llm.grok import resolve_grok_model
        from backend.config import GROK_MODEL_ID, GROK_OVERDRIVE_MODEL_ID

        # Default config without overrides (regular mode)
        cfg_grok_reg = ModelConfig(
            model_id=GROK_MODEL_ID,
            provider="grok",
            display_name="Grok 4.20",
            color="#EC4899",
            icon="✕"
        )
        self.assertEqual(resolve_grok_model(cfg_grok_reg), GROK_MODEL_ID)

        # Default config without overrides (overdrive mode)
        cfg_grok_od = ModelConfig(
            model_id=GROK_OVERDRIVE_MODEL_ID,
            provider="grok",
            display_name="Grok 4.20",
            color="#EC4899",
            icon="✕",
            thinking={"type": "adaptive"}
        )
        self.assertEqual(resolve_grok_model(cfg_grok_od), GROK_OVERDRIVE_MODEL_ID)

        # Override thinking to True
        cfg_grok_thinking = ModelConfig(
            model_id=GROK_MODEL_ID,
            provider="grok",
            display_name="Grok 4.20",
            color="#EC4899",
            icon="✕",
            thinking={"type": "adaptive"}
        )
        self.assertEqual(resolve_grok_model(cfg_grok_thinking), GROK_OVERDRIVE_MODEL_ID)

        # Override thinking to None (disabled)
        cfg_grok_nothinking = ModelConfig(
            model_id=GROK_OVERDRIVE_MODEL_ID,
            provider="grok",
            display_name="Grok 4.20",
            color="#EC4899",
            icon="✕",
            thinking=None
        )
        self.assertEqual(resolve_grok_model(cfg_grok_nothinking), GROK_MODEL_ID)


if __name__ == "__main__":
    unittest.main()
