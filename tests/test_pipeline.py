import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone

from app import database
from app.bus import event_bus
from app.models import TikTokEvent
from app.processor import EventProcessor

# Isolated temp DB so the suite never touches the real data/ directory.
TEST_DB_DIR = tempfile.mkdtemp(prefix="tiktobs_pipeline_")
TEST_DB_PATH = os.path.join(TEST_DB_DIR, "test_tiktok_live.db")

class TestPipeline(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Close any connection opened by earlier test files, then point the
        # shared connection at our isolated test database.
        self._orig_db_path = database.DB_PATH
        await database.close_db()
        database.DB_PATH = TEST_DB_PATH
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
            
        await database.init_db()
        self.processor = EventProcessor()
        self.published_events = []
        
        # Subscribe to event bus
        event_bus.subscribe(self.on_event_published)

    async def asyncTearDown(self):
        # Unsubscribe, release the connection (so the files can be deleted and
        # no aiosqlite worker thread is left behind), restore the DB path.
        event_bus.unsubscribe(self.on_event_published)
        await database.close_db()
        database.DB_PATH = self._orig_db_path
        for suffix in ("", "-shm", "-wal"):
            path = TEST_DB_PATH + suffix
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

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

    async def test_streak_gifts_are_counted_once_via_final_event(self):
        """TikTok streak schema (gift.type == 1).

        A Rose x3 combo emits one event per increment (repeat_end=0 with a
        growing repeat_count) plus a FINAL event (repeat_end=1) carrying the
        full repeat_count. Mid-streak events must still reach the live feed,
        but poll votes and leaderboard totals may only be tallied from the
        final event — otherwise a single combo inflates the numbers.
        """
        from app import processor as processor_module
        from app.poll import PollManager

        local_pm = PollManager()
        orig_pm = processor_module.poll_manager
        processor_module.poll_manager = local_pm
        try:
            session_id = await database.create_session("streak_creator")
            self.processor.set_session_id(session_id)

            await local_pm.start_poll(
                "Streak test",
                [{"name": "Merah", "gift_name": "Rose"}],
            )

            base_ts = int(datetime.now(timezone.utc).timestamp() * 1000)

            def gift_payload(msg_id: str, quantity: int, repeat_end: int) -> dict:
                return {
                    "msg_id": msg_id,
                    "timestamp": base_ts,
                    "user": {"unique_id": "streak_sender", "nickname": "Streak Sender"},
                    "gift_id": 5655,
                    "repeat_count": quantity,
                    "combo_count": quantity,
                    "repeat_end": repeat_end,
                    "gift": {
                        "gift_id": 5655,
                        "name": "Rose",
                        "type": 1,  # streakable
                        "diamond_count": 1,
                    },
                }

            # Mid-streak increments, then the final event with the full count.
            await self.processor.process_raw_event("gift", gift_payload("streak_1", 1, 0))
            await self.processor.process_raw_event("gift", gift_payload("streak_2", 2, 0))
            await self.processor.process_raw_event("gift", gift_payload("streak_final", 3, 1))

            # All three events still reach the live feed/DB.
            self.assertEqual(len(self.published_events), 3)

            # Poll counted only the final event: 3 roses x 1 diamond = 3 votes.
            status = await local_pm.get_status()
            merah = next(c for c in status["candidates"] if c["name"] == "Merah")
            self.assertEqual(merah["votes"], 3)

            # Leaderboard likewise sums only the final event.
            board = await database.get_session_leaderboard(session_id)
            self.assertEqual(len(board), 1)
            self.assertEqual(board[0]["username"], "streak_sender")
            self.assertEqual(board[0]["total_diamonds"], 3)
            self.assertEqual(board[0]["total_gifts"], 3)

            await local_pm.stop_poll()
            await database.close_session(session_id)
        finally:
            processor_module.poll_manager = orig_pm

    async def test_unmatched_gift_during_active_poll_broadcasts_ignored_notice(self):
        """A gift no candidate owns: votes stay at zero for everyone, but the
        processor broadcasts poll_gift_ignored so the sender gets feedback
        instead of silently losing the gift."""
        from app import processor as processor_module
        from app.poll import PollManager

        local_pm = PollManager()
        orig_pm = processor_module.poll_manager
        processor_module.poll_manager = local_pm

        class StubManager:
            def __init__(self):
                self.messages = []

            async def broadcast(self, message):
                self.messages.append(message)

        stub_manager = StubManager()
        orig_manager = processor_module.manager
        processor_module.manager = stub_manager
        try:
            session_id = await database.create_session("gift_ignore_creator")
            self.processor.set_session_id(session_id)

            await local_pm.start_poll(
                "Ignore test",
                [{"name": "Merah", "gift_name": "Rose"}],
            )

            def gift_payload(msg_id: str, name: str, gift_id: int) -> dict:
                return {
                    "msg_id": msg_id,
                    "user": {
                        "unique_id": "generous_viewer",
                        "nickname": "Generous",
                        "avatar_thumb": {"url_list": ["https://cdn/avatar.jpg"]},
                    },
                    "gift_id": gift_id,
                    "gift_name": name,
                    "quantity": 1,
                    "diamond_count": 99,
                    "gift_type": 2,
                    "repeat_end": 1,
                }

            # 1. Unmatched gift: still persisted/published, but zero votes...
            await self.processor.process_raw_event("gift", gift_payload("gift_unmatched_1", "Ice Cream", 700))
            status = await local_pm.get_status()
            merah = next(c for c in status["candidates"] if c["name"] == "Merah")
            self.assertEqual(merah["votes"], 0)
            self.assertEqual(len(self.published_events), 1)

            # ...and a poll_gift_ignored notice goes out with the details.
            ignored_msgs = [m for m in stub_manager.messages if m["type"] == "poll_gift_ignored"]
            self.assertEqual(len(ignored_msgs), 1)
            msg = ignored_msgs[0]
            self.assertEqual(msg["username"], "generous_viewer")
            self.assertEqual(msg["gift_name"], "Ice Cream")
            self.assertEqual(msg["diamond_count"], 99)
            self.assertEqual(msg["reason"], "no_vote_comment")
            self.assertEqual(msg["avatar_url"], "https://cdn/avatar.jpg")
            # No false celebration: no vote broadcast for the unmatched gift.
            self.assertFalse(any(m["type"] == "poll_gift_vote" for m in stub_manager.messages))

            # 2. A matched gift still counts normally and adds no ignored notice.
            await self.processor.process_raw_event("gift", gift_payload("gift_matched_1", "Rose", 5))
            status = await local_pm.get_status()
            merah = next(c for c in status["candidates"] if c["name"] == "Merah")
            self.assertEqual(merah["votes"], 99)
            ignored_msgs = [m for m in stub_manager.messages if m["type"] == "poll_gift_ignored"]
            self.assertEqual(len(ignored_msgs), 1)
            self.assertTrue(any(m["type"] == "poll_gift_vote" for m in stub_manager.messages))

            # 3. With NO active poll, an unmatched gift is just a normal gift:
            # no ignored notice (nothing to warn about).
            await local_pm.stop_poll()
            stub_manager.messages.clear()
            await self.processor.process_raw_event("gift", gift_payload("gift_no_poll", "Galaxy", 900))
            self.assertFalse(any(m["type"] == "poll_gift_ignored" for m in stub_manager.messages))

            await database.close_session(session_id)
        finally:
            processor_module.poll_manager = orig_pm
            processor_module.manager = orig_manager

    async def test_unmatched_gift_falls_back_to_senders_last_comment(self):
        """End-to-end through the processor: a gift that matches no candidate
        is credited to the candidate of the sender's last vote comment."""
        from app import processor as processor_module
        from app.poll import PollManager

        local_pm = PollManager()
        orig_pm = processor_module.poll_manager
        processor_module.poll_manager = local_pm

        class StubManager:
            def __init__(self):
                self.messages = []

            async def broadcast(self, message):
                self.messages.append(message)

        stub_manager = StubManager()
        orig_manager = processor_module.manager
        processor_module.manager = stub_manager
        try:
            session_id = await database.create_session("fallback_creator")
            self.processor.set_session_id(session_id)

            await local_pm.start_poll(
                "Fallback test",
                [
                    {"name": "Merah", "gift_name": "Rose"},
                    {"name": "Biru", "gift_name": "Galaxy"},
                ],
            )

            # Sultan comments "02" -> vote for Biru + intent.
            await self.processor.process_raw_event("comment", {
                "msg_id": "fb_comment_1",
                "user": {"unique_id": "sultan", "nickname": "Sultan"},
                "comment": "02",
            })

            # Sultan sends Rocket (nobody's gift) -> credited to Biru via "02".
            await self.processor.process_raw_event("gift", {
                "msg_id": "fb_gift_1",
                "user": {"unique_id": "sultan", "nickname": "Sultan"},
                "gift_name": "Rocket",
                "quantity": 1,
                "diamond_count": 500,
                "gift_type": 2,
                "repeat_end": 1,
            })

            status = await local_pm.get_status()
            biru = next(c for c in status["candidates"] if c["name"] == "Biru")
            merah = next(c for c in status["candidates"] if c["name"] == "Merah")
            self.assertEqual(biru["votes"], 1 + 500)  # comment + rocket
            self.assertEqual(merah["votes"], 0)

            vote_msgs = [m for m in stub_manager.messages if m["type"] == "poll_gift_vote"]
            self.assertEqual(len(vote_msgs), 1)
            self.assertEqual(vote_msgs[0]["candidate_name"], "Biru")
            self.assertEqual(vote_msgs[0]["votes_added"], 500)
            self.assertEqual(vote_msgs[0]["via_comment"], "02")
            # And no ignored notice was sent for the credited gift.
            self.assertFalse(any(m["type"] == "poll_gift_ignored" for m in stub_manager.messages))

            await local_pm.stop_poll()
            await database.close_session(session_id)
        finally:
            processor_module.poll_manager = orig_pm
            processor_module.manager = orig_manager

    async def test_gift_normalization_captures_streak_fields(self):
        event = self.processor._normalize("gift", {
            "msg_id": "gift_schema_1",
            "user": {"unique_id": "norm_user", "nickname": "Norm"},
            "repeat_count": 7,
            "repeat_end": 1,
            "gift": {"name": "Lion", "type": 2, "diamond_count": 29999},
        })
        self.assertEqual(event.data["quantity"], 7)
        self.assertEqual(event.data["diamond_count"], 29999)
        self.assertEqual(event.data["repeat_end"], 1)
        self.assertEqual(event.data["gift_type"], 2)

        # repeat_end=0 is meaningful and must survive normalization (a truthy
        # `or` chain would have dropped it into None).
        mid = self.processor._normalize("gift", {
            "msg_id": "gift_schema_2",
            "user": {"unique_id": "norm_user"},
            "repeat_count": 2,
            "repeat_end": 0,
            "gift": {"name": "Rose", "type": 1, "diamond_count": 1},
        })
        self.assertEqual(mid.data["repeat_end"], 0)
        self.assertEqual(mid.data["gift_type"], 1)



class TestExtractAvatarUrl(unittest.TestCase):
    """Unit tests for the sender-avatar extraction helper used to feed
    profile pictures into poll_gift_vote / poll_gift_ignored broadcasts."""

    def test_direct_url_field(self):
        from app.processor import _extract_avatar_url
        self.assertEqual(_extract_avatar_url({"avatar_url": "https://a.jpg"}), "https://a.jpg")
        self.assertEqual(_extract_avatar_url({"avatarUrl": "  https://b.jpg  "}), "https://b.jpg")

    def test_proto_image_model(self):
        from app.processor import _extract_avatar_url
        user = {
            "avatar_thumb": {"url_list": ["", "https://thumb.jpg"]},
            "avatar_large": {"urlList": ["https://large.jpg"]},
        }
        self.assertEqual(_extract_avatar_url(user), "https://thumb.jpg")

    def test_no_avatar(self):
        from app.processor import _extract_avatar_url
        self.assertEqual(_extract_avatar_url({}), "")
        self.assertEqual(_extract_avatar_url({"avatar_thumb": {"url_list": []}}), "")
        self.assertEqual(_extract_avatar_url(None), "")


if __name__ == "__main__":
    unittest.main()
