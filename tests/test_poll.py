import asyncio
import unittest

from app.poll import PollManager


class TestPollManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.poll_manager = PollManager()
        self.title = "Siapa karakter terbaik?"
        self.candidates = [
            {"name": "Alice", "image_url": "http://img/alice.jpg"},
            {"name": "Bob", "image_url": ""}
        ]

    async def test_start_and_get_status(self):
        await self.poll_manager.start_poll(self.title, self.candidates)
        status = await self.poll_manager.get_status()

        self.assertTrue(status["is_active"])
        self.assertEqual(status["title"], self.title)
        self.assertEqual(status["total_votes"], 0)
        self.assertEqual(len(status["candidates"]), 2)
        
        # Candidate 1: Alice
        self.assertEqual(status["candidates"][0]["id"], "1")
        self.assertEqual(status["candidates"][0]["name"], "Alice")
        self.assertEqual(status["candidates"][0]["image_url"], "http://img/alice.jpg")
        self.assertEqual(status["candidates"][0]["votes"], 0)
        self.assertEqual(status["candidates"][0]["percentage"], 0.0)

        # Candidate 2: Bob
        self.assertEqual(status["candidates"][1]["id"], "2")
        self.assertEqual(status["candidates"][1]["name"], "Bob")
        self.assertEqual(status["candidates"][1]["image_url"], "")
        self.assertEqual(status["candidates"][1]["votes"], 0)
        self.assertEqual(status["candidates"][1]["percentage"], 0.0)

    async def test_vote_by_id_and_prevention_of_double_voting(self):
        await self.poll_manager.start_poll(self.title, self.candidates)

        # Vote for Candidate 1 (Alice) using ID "1"
        success = await self.poll_manager.record_vote("user1", "1")
        self.assertTrue(success)

        # Try to vote again from the same user (should be rejected)
        success = await self.poll_manager.record_vote("user1", "2")
        self.assertFalse(success)

        # Vote from another user for Candidate 1 using ID "#1" (with hash prefix)
        success = await self.poll_manager.record_vote("user2", " #1 ")
        self.assertTrue(success)

        status = await self.poll_manager.get_status()
        self.assertEqual(status["total_votes"], 2)
        self.assertEqual(status["candidates"][0]["votes"], 2)  # Alice has 2 votes
        self.assertEqual(status["candidates"][0]["percentage"], 100.0)
        self.assertEqual(status["candidates"][1]["votes"], 0)  # Bob has 0 votes

    async def test_vote_by_name_case_insensitive(self):
        # Adding a short candidate named 'Yo'
        candidates = [
            {"name": "Alice", "image_url": ""},
            {"name": "Bob", "image_url": ""},
            {"name": "Yo", "image_url": ""}
        ]
        await self.poll_manager.start_poll(self.title, candidates)

        # 1. Vote by name mention (Alice is in 'pilih alice')
        success = await self.poll_manager.record_vote("user1", "  pilih alice  ")
        self.assertTrue(success)

        # 2. Vote by name mention (Bob is in 'BOB dong')
        success = await self.poll_manager.record_vote("user2", "BOB dong")
        self.assertTrue(success)

        # 3. Short candidate name (Yo <= 2 chars): 'Yo' exact match should work
        success = await self.poll_manager.record_vote("user3", "yo")
        self.assertTrue(success)

        # 4. Short candidate name (Yo <= 2 chars): 'Ayo' mention should NOT match Yo
        success = await self.poll_manager.record_vote("user4", "ayo")
        self.assertFalse(success)

        # 5. Ambiguous comment mentioning both Alice and Bob should fail
        success = await self.poll_manager.record_vote("user5", "alice vs bob")
        self.assertFalse(success)

        status = await self.poll_manager.get_status()
        self.assertEqual(status["candidates"][0]["votes"], 1)  # Alice gets 1
        self.assertEqual(status["candidates"][1]["votes"], 1)  # Bob gets 1
        self.assertEqual(status["candidates"][2]["votes"], 1)  # Yo gets 1
        self.assertEqual(status["total_votes"], 3)

    async def test_stop_poll(self):
        await self.poll_manager.start_poll(self.title, self.candidates)
        await self.poll_manager.record_vote("user1", "1")
        
        await self.poll_manager.stop_poll()
        status = await self.poll_manager.get_status()
        self.assertFalse(status["is_active"])

        # Try to vote in stopped poll
        success = await self.poll_manager.record_vote("user2", "2")
        self.assertFalse(success)

        status_after = await self.poll_manager.get_status()
        self.assertEqual(status_after["total_votes"], 1)  # Stays 1 vote

    async def test_poll_timer_and_expiration(self):
        # Start a poll with a duration of 1 second
        await self.poll_manager.start_poll(self.title, self.candidates, duration_seconds=1)
        status = await self.poll_manager.get_status()
        self.assertTrue(status["is_active"])
        self.assertIsNotNone(status["expires_at"])
        self.assertGreaterEqual(status["time_left"], 0)

        # Vote should succeed immediately
        success = await self.poll_manager.record_vote("user1", "1")
        self.assertTrue(success)

        # Wait for the timer loop to sleep and stop the poll automatically
        await asyncio.sleep(1.2)
        
        status_after = await self.poll_manager.get_status()
        self.assertFalse(status_after["is_active"])
        self.assertIsNone(status_after["expires_at"])
        self.assertIsNone(status_after["time_left"])

        # Vote should fail because poll is now stopped/expired
        success = await self.poll_manager.record_vote("user2", "2")
        self.assertFalse(success)

    async def test_gift_voting_fast_track(self):
        candidates = [
            {"name": "Alice", "image_url": "http://img/alice.jpg", "gift_name": "Rose"},
            {"name": "Bob", "image_url": "", "gift_name": "Finger Heart"}
        ]
        await self.poll_manager.start_poll(self.title, candidates)
        status = await self.poll_manager.get_status()
        self.assertEqual(status["candidates"][0]["gift_name"], "Rose")
        self.assertEqual(status["candidates"][1]["gift_name"], "Finger Heart")

        # 1. Send gift 'Rose' with 1 diamond (Alice gets 1 vote)
        success, name, votes = await self.poll_manager.record_gift_vote("Rose", 1)
        self.assertTrue(success)
        self.assertEqual(name, "Alice")
        self.assertEqual(votes, 1)

        # 2. Send gift 'Rose' with 15 diamonds (Alice gets 15 more votes)
        success, name, votes = await self.poll_manager.record_gift_vote("Rose", 15)
        self.assertTrue(success)
        self.assertEqual(name, "Alice")
        self.assertEqual(votes, 15)

        # 3. Send gift 'Finger Heart' with 5 diamonds (Bob gets 5 votes)
        success, name, votes = await self.poll_manager.record_gift_vote("Finger Heart", 5)
        self.assertTrue(success)
        self.assertEqual(name, "Bob")
        self.assertEqual(votes, 5)

        # 4. Check status totals
        status_after = await self.poll_manager.get_status()
        self.assertEqual(status_after["candidates"][0]["votes"], 16)  # 1 + 15 = 16
        self.assertEqual(status_after["candidates"][1]["votes"], 5)   # 5
        self.assertEqual(status_after["total_votes"], 21)             # 16 + 5 = 21

        # 5. Unrelated gift should do nothing
        success, name, votes = await self.poll_manager.record_gift_vote("Ice Cream", 1)
        self.assertFalse(success)

if __name__ == "__main__":
    unittest.main()
