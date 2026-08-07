import asyncio
import os
import unittest
from datetime import datetime, timezone

from app import database
from app.bus import event_bus
from app.models import TikTokEvent
from app.processor import EventProcessor

TEST_DB_DIR = "data"
TEST_DB_PATH = os.path.join(TEST_DB_DIR, "test_tiktok_live.db")

class TestPipeline(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Override DB path to test database
        database.DB_PATH = TEST_DB_PATH
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
            
        await database.init_db()
        self.processor = EventProcessor()
        self.published_events = []
        
        # Subscribe to event bus
        event_bus.subscribe(self.on_event_published)

    async def asyncTearDown(self):
        # Unsubscribe and clean up test db
        event_bus.unsubscribe(self.on_event_published)
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except PermissionError:
                # database connection might still be closing asynchronously, wait briefly
                await asyncio.sleep(0.5)
                if os.path.exists(TEST_DB_PATH):
                    os.remove(TEST_DB_PATH)

    async def on_event_published(self, event: TikTokEvent):
        self.published_events.append(event)

    async def test_full_pipeline(self):
        # 1. Create a session
        username = "test_creator"
        session_id = await database.create_session(username)
        self.processor.set_session_id(session_id)
        
        self.assertEqual(self.processor.session_id, session_id)
        
        # 2. Test Comment Normalization, Persistence, and Publish
        comment_payload = {
            "msg_id": "comment_101",
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "user": {
                "unique_id": "alice_test",
                "nickname": "Alice"
            },
            "comment": "Hello World!"
        }
        
        await self.processor.process_raw_event("comment", comment_payload)
        
        # Verify published
        self.assertEqual(len(self.published_events), 1)
        evt = self.published_events[0]
        self.assertEqual(evt.id, "comment_101")
        self.assertEqual(evt.event_type, "comment")
        self.assertEqual(evt.username, "alice_test")
        self.assertEqual(evt.nickname, "Alice")
        self.assertEqual(evt.data["comment"], "Hello World!")
        
        # 3. Test Gift Event
        gift_payload = {
            "msg_id": "gift_202",
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "user": {
                "unique_id": "bob_test",
                "nickname": "Bob"
            },
            "gift": {
                "gift_id": 55,
                "name": "Rose",
                "repeat_count": 5,
                "diamond_count": 2
            }
        }
        await self.processor.process_raw_event("gift", gift_payload)
        self.assertEqual(len(self.published_events), 2)
        gift_evt = self.published_events[1]
        self.assertEqual(gift_evt.id, "gift_202")
        self.assertEqual(gift_evt.event_type, "gift")
        self.assertEqual(gift_evt.data["gift_name"], "Rose")
        self.assertEqual(gift_evt.data["quantity"], 5)
        self.assertEqual(gift_evt.data["diamond_count"], 2)

        # 4. Test Like Event
        like_payload = {
            "msg_id": "like_303",
            "user": {
                "unique_id": "charlie_test",
                "nickname": "Charlie"
            },
            "like_count": 25
        }
        await self.processor.process_raw_event("like", like_payload)
        self.assertEqual(len(self.published_events), 3)
        like_evt = self.published_events[2]
        self.assertEqual(like_evt.data["count"], 25)

        # 5. Test Follow Event
        follow_payload = {
            "msg_id": "follow_404",
            "user": {
                "unique_id": "dave_test",
                "nickname": "Dave"
            }
        }
        await self.processor.process_raw_event("follow", follow_payload)
        self.assertEqual(len(self.published_events), 4)

        # 6. Test Share Event
        share_payload = {
            "msg_id": "share_505",
            "user": {
                "unique_id": "dave_test"
            },
            "share_target": "WhatsApp"
        }
        await self.processor.process_raw_event("share", share_payload)
        self.assertEqual(len(self.published_events), 5)
        share_evt = self.published_events[4]
        self.assertEqual(share_evt.data["share_target"], "WhatsApp")

        # 7. Test Viewer Event (Deterministic ID should be generated)
        viewer_payload = {
            "viewer_count": 120
        }
        await self.processor.process_raw_event("viewer", viewer_payload)
        self.assertEqual(len(self.published_events), 6)
        viewer_evt = self.published_events[5]
        self.assertIsNotNone(viewer_evt.id)
        self.assertEqual(viewer_evt.data["viewer_count"], 120)

        # 8. Test Duplicate Prevention
        # Reprocessing comment_payload with same msg_id "comment_101"
        await self.processor.process_raw_event("comment", comment_payload)
        # Length of published should STILL be 6 (no new publish)
        self.assertEqual(len(self.published_events), 6)
        
        # 9. Verify DB Records Match
        db_events = await database.get_recent_events(limit=10)
        self.assertEqual(len(db_events), 6)
        
        # The list is in descending chronological order
        types = [d["event_type"] for d in db_events]
        self.assertIn("comment", types)
        self.assertIn("gift", types)
        self.assertIn("like", types)
        self.assertIn("follow", types)
        self.assertIn("share", types)
        self.assertIn("viewer", types)

        # 10. Test Comment Fallbacks (display_id and content)
        comment_fallback_payload = {
            "msg_id": "comment_102",
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "user": {
                "display_id": "fallback_alice",
                "nickname": "Alice Fallback"
            },
            "content": "Hello Fallback!"
        }
        await self.processor.process_raw_event("comment", comment_fallback_payload)
        
        self.assertEqual(len(self.published_events), 7)
        fallback_evt = self.published_events[6]
        self.assertEqual(fallback_evt.id, "comment_102")
        self.assertEqual(fallback_evt.username, "fallback_alice")
        self.assertEqual(fallback_evt.data["comment"], "Hello Fallback!")

        # 11. Test Leaderboard Database Aggregation
        charlie_gift_payload = {
            "msg_id": "gift_203",
            "user": {
                "unique_id": "charlie_test",
                "nickname": "Charlie"
            },
            "gift": {
                "gift_id": 102,
                "name": "Lion",
                "repeat_count": 1,
                "diamond_count": 100
            }
        }
        await self.processor.process_raw_event("gift", charlie_gift_payload)
        
        # Query leaderboard from database
        leaderboard = await database.get_session_leaderboard(session_id)
        
        # Charlie should be #1 (100 diamonds), Bob #2 (10 diamonds: 5 qty * 2 diamonds)
        self.assertEqual(len(leaderboard), 2)
        
        self.assertEqual(leaderboard[0]["username"], "charlie_test")
        self.assertEqual(leaderboard[0]["total_diamonds"], 100)
        self.assertEqual(leaderboard[0]["total_gifts"], 1)
        
        self.assertEqual(leaderboard[1]["username"], "bob_test")
        self.assertEqual(leaderboard[1]["total_diamonds"], 10)
        self.assertEqual(leaderboard[1]["total_gifts"], 5)

        # Close session
        await database.close_session(session_id)

if __name__ == "__main__":
    unittest.main()
