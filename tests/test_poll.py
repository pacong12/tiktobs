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

    async def test_every_comment_counts_even_from_same_user(self):
        await self.poll_manager.start_poll(self.title, self.candidates)

        # Vote for Candidate 1 (Alice) using ID "1"
        success = await self.poll_manager.record_vote("user1", "1")
        self.assertTrue(success)

        # Same user votes again for Candidate 2 -> counted again.
        success = await self.poll_manager.record_vote("user1", "2")
        self.assertTrue(success)

        # Same user votes for Alice by name -> counted again.
        success = await self.poll_manager.record_vote("user1", "alice")
        self.assertTrue(success)

        # Vote from another user for Candidate 1 using ID "#1" (with hash prefix)
        success = await self.poll_manager.record_vote("user2", " #1 ")
        self.assertTrue(success)

        status = await self.poll_manager.get_status()
        self.assertEqual(status["total_votes"], 4)
        self.assertEqual(status["candidates"][0]["votes"], 3)  # Alice: "1", "alice", "#1"
        self.assertEqual(status["candidates"][1]["votes"], 1)  # Bob: "2"
        self.assertEqual(status["unique_voters"], 2)

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
        success, name, votes, _via = await self.poll_manager.record_gift_vote("Rose", 1)
        self.assertTrue(success)
        self.assertEqual(name, "Alice")
        self.assertEqual(votes, 1)

        # 2. Send gift 'Rose' with 15 diamonds (Alice gets 15 more votes)
        success, name, votes, _via = await self.poll_manager.record_gift_vote("Rose", 15)
        self.assertTrue(success)
        self.assertEqual(name, "Alice")
        self.assertEqual(votes, 15)

        # 3. Send gift 'Finger Heart' with 5 diamonds (Bob gets 5 votes)
        success, name, votes, _via = await self.poll_manager.record_gift_vote("Finger Heart", 5)
        self.assertTrue(success)
        self.assertEqual(name, "Bob")
        self.assertEqual(votes, 5)

        # 4. Check status totals
        status_after = await self.poll_manager.get_status()
        self.assertEqual(status_after["candidates"][0]["votes"], 16)  # 1 + 15 = 16
        self.assertEqual(status_after["candidates"][1]["votes"], 5)   # 5
        self.assertEqual(status_after["total_votes"], 21)             # 16 + 5 = 21

        # 5. Unrelated gift from a sender with no vote comment does nothing
        success, name, votes, _via = await self.poll_manager.record_gift_vote("Ice Cream", 1, username="random_viewer")
        self.assertFalse(success)

    async def test_vote_by_sequence_number_with_leading_zeros(self):
        candidates = [
            {"name": "Alice", "image_url": ""},
            {"name": "Bob", "image_url": ""},
            {"name": "Charlie", "image_url": ""},
        ]
        await self.poll_manager.start_poll(self.title, candidates)

        # "01" -> candidate #1 (Alice)
        self.assertTrue(await self.poll_manager.record_vote("u1", "01"))
        # "#02" -> candidate #2 (Bob)
        self.assertTrue(await self.poll_manager.record_vote("u2", "#02"))
        # " 003 " -> candidate #3 (Charlie)
        self.assertTrue(await self.poll_manager.record_vote("u3", " 003 "))
        # Out-of-range number -> no match
        self.assertFalse(await self.poll_manager.record_vote("u4", "99"))
        # Not a pure number -> no match
        self.assertFalse(await self.poll_manager.record_vote("u5", "1a"))

        status = await self.poll_manager.get_status()
        self.assertEqual(status["candidates"][0]["votes"], 1)
        self.assertEqual(status["candidates"][1]["votes"], 1)
        self.assertEqual(status["candidates"][2]["votes"], 1)
        self.assertEqual(status["total_votes"], 3)

    async def test_repeat_voter_across_formats(self):
        await self.poll_manager.start_poll(self.title, self.candidates)

        # Every matching comment counts, in any format...
        self.assertTrue(await self.poll_manager.record_vote("user1", "01"))
        self.assertTrue(await self.poll_manager.record_vote("user1", "bob"))
        self.assertTrue(await self.poll_manager.record_vote("user1", "2"))
        # ...even from username casing/whitespace variants of the same user.
        self.assertTrue(await self.poll_manager.record_vote(" User1 ", "2"))
        self.assertTrue(await self.poll_manager.record_vote("USER1", "alice"))

        status = await self.poll_manager.get_status()
        self.assertEqual(status["total_votes"], 5)
        self.assertEqual(status["candidates"][0]["votes"], 2)  # "01" + "alice"
        self.assertEqual(status["candidates"][1]["votes"], 3)  # "bob" + "2" + "2"
        self.assertEqual(status["unique_voters"], 1)

    async def test_gift_matching_is_strict_and_normalized(self):
        candidates = [
            {"name": "Alice", "image_url": "", "gift_name": "Rose"},
            {"name": "Bob", "image_url": "", "gift_name": "Finger Heart"},
        ]
        await self.poll_manager.start_poll(self.title, candidates)

        # Case + surrounding whitespace still match.
        success, name, _, _via = await self.poll_manager.record_gift_vote("  ROSE ", 1)
        self.assertTrue(success)
        self.assertEqual(name, "Alice")

        # Emoji decoration on the live gift name still matches.
        success, name, _, _via = await self.poll_manager.record_gift_vote("Rose \U0001f339", 2)
        self.assertTrue(success)
        self.assertEqual(name, "Alice")

        # Collapsed whitespace matches multi-word gifts.
        success, name, _, _via = await self.poll_manager.record_gift_vote("finger  heart", 3)
        self.assertTrue(success)
        self.assertEqual(name, "Bob")

        # Any other gift from a sender with NO vote comment counts for
        # NOBODY (no leak to Alice or Bob).
        success, name, votes, _via = await self.poll_manager.record_gift_vote("Doughnut", 30, username="no_comment_user")
        self.assertFalse(success)
        self.assertIsNone(name)
        self.assertEqual(votes, 0)
        success, name, votes, _via = await self.poll_manager.record_gift_vote("Galaxy", 1000, username="no_comment_user")
        self.assertFalse(success)

    async def test_duplicate_gift_assignment_rejected(self):
        candidates = [
            {"name": "Alice", "image_url": "", "gift_name": "Rose"},
            {"name": "Bob", "image_url": "", "gift_name": "rose \U0001f339"},
        ]
        with self.assertRaises(ValueError):
            await self.poll_manager.start_poll(self.title, candidates)
        # The failed start must not leave a poll running.
        status = await self.poll_manager.get_status()
        self.assertFalse(status["is_active"])


    async def test_candidate_color_passthrough(self):
        """Per-candidate accent color is stored and exposed in the status."""
        candidates = [
            {"name": "Alice", "color": "#00e5ff"},
            {"name": "Bob"},  # no color -> empty string (overlay palette fallback)
        ]
        await self.poll_manager.start_poll(self.title, candidates)
        status = await self.poll_manager.get_status()
        self.assertEqual(status["candidates"][0]["color"], "#00e5ff")
        self.assertEqual(status["candidates"][1]["color"], "")

    async def test_gift_fallback_to_last_vote_comment(self):
        """A gift that matches no candidate's gift is credited to the
        candidate the sender last voted for by comment this round."""
        candidates = [
            {"name": "Alice", "image_url": "", "gift_name": "Rose"},
            {"name": "Bob", "image_url": "", "gift_name": "Galaxy"},
        ]
        await self.poll_manager.start_poll(self.title, candidates)

        # Sultan comments "02" -> +1 vote for Bob AND intent towards Bob.
        self.assertTrue(await self.poll_manager.record_vote("sultan", "02"))

        # Unmatched gift is credited to Bob via the comment (1 diamond = 1 vote).
        success, name, votes, via = await self.poll_manager.record_gift_vote("Rocket", 5000, username="sultan")
        self.assertTrue(success)
        self.assertEqual(name, "Bob")
        self.assertEqual(votes, 5000)
        self.assertEqual(via, "02")

        # A directly-matching gift never needs the fallback.
        success, name, votes, via = await self.poll_manager.record_gift_vote("Rose", 3, username="sultan")
        self.assertTrue(success)
        self.assertEqual(name, "Alice")
        self.assertEqual(votes, 3)
        self.assertIsNone(via)

        # A sender who never commented gets nothing for an unmatched gift.
        success, name, votes, via = await self.poll_manager.record_gift_vote("Rocket", 100, username="newbie")
        self.assertFalse(success)
        self.assertIsNone(name)
        self.assertEqual(votes, 0)
        self.assertIsNone(via)

        status = await self.poll_manager.get_status()
        self.assertEqual(status["candidates"][0]["votes"], 3)          # Alice: Rose only
        self.assertEqual(status["candidates"][1]["votes"], 1 + 5000)   # Bob: comment + Rocket

    async def test_gift_fallback_follows_latest_vote_comment(self):
        """The intent tracks the sender's LATEST vote comment."""
        candidates = [
            {"name": "Alice", "image_url": "", "gift_name": "Rose"},
            {"name": "Bob", "image_url": "", "gift_name": "Galaxy"},
        ]
        await self.poll_manager.start_poll(self.title, candidates)
        self.assertTrue(await self.poll_manager.record_vote("sultan", "01"))
        self.assertTrue(await self.poll_manager.record_vote("sultan", "02"))

        success, name, votes, via = await self.poll_manager.record_gift_vote("Rocket", 10, username="sultan")
        self.assertTrue(success)
        self.assertEqual(name, "Bob")
        self.assertEqual(via, "02")

        # Non-matching comments ("wkwkwk") do NOT overwrite the intent...
        self.assertFalse(await self.poll_manager.record_vote("sultan", "wkwkwk"))
        success, name, votes, via = await self.poll_manager.record_gift_vote("Rocket", 5, username="sultan")
        self.assertTrue(success)
        self.assertEqual(name, "Bob")
        self.assertEqual(via, "02")

        # ...but a vote comment by candidate name does.
        self.assertTrue(await self.poll_manager.record_vote("sultan", "alice"))
        success, name, votes, via = await self.poll_manager.record_gift_vote("Rocket", 5, username="SULTAN")
        self.assertTrue(success)
        self.assertEqual(name, "Alice")
        self.assertEqual(via, "alice")

    async def test_gift_fallback_intent_resets_between_rounds(self):
        """Comments from a previous round never steer the next round."""
        candidates = [
            {"name": "Alice", "image_url": "", "gift_name": "Rose"},
            {"name": "Bob", "image_url": "", "gift_name": "Galaxy"},
        ]
        await self.poll_manager.start_poll("round 1", candidates)
        self.assertTrue(await self.poll_manager.record_vote("sultan", "01"))
        await self.poll_manager.stop_poll(archive=False)

        await self.poll_manager.start_poll("round 2", candidates)
        # Intent from round 1 is gone: unmatched gift counts for nobody.
        success, name, votes, via = await self.poll_manager.record_gift_vote("Rocket", 50, username="sultan")
        self.assertFalse(success)
        self.assertIsNone(name)
        self.assertEqual(votes, 0)

        # A fresh comment in the new round re-enables the fallback.
        self.assertTrue(await self.poll_manager.record_vote("sultan", "02"))
        success, name, votes, via = await self.poll_manager.record_gift_vote("Rocket", 50, username="sultan")
        self.assertTrue(success)
        self.assertEqual(name, "Bob")
        self.assertEqual(votes, 50)

    async def test_gift_fallback_requires_username(self):
        """Without a sender (e.g. legacy calls) the fallback cannot apply."""
        candidates = [
            {"name": "Alice", "image_url": "", "gift_name": "Rose"},
            {"name": "Bob", "image_url": "", "gift_name": "Galaxy"},
        ]
        await self.poll_manager.start_poll(self.title, candidates)
        self.assertTrue(await self.poll_manager.record_vote("sultan", "01"))
        success, name, votes, via = await self.poll_manager.record_gift_vote("Rocket", 50)
        self.assertFalse(success)
        self.assertIsNone(name)
        self.assertEqual(votes, 0)


if __name__ == "__main__":
    unittest.main()
