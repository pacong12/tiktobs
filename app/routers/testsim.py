"""Simulated testing endpoints.

Disabled by default (production-safe). Enable for local testing/simulation
by setting TIKTOBS_TEST_ENDPOINTS=1 in the environment or .env.
"""

import asyncio
import os
import random
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException

from app import state
from app.poll import poll_manager

router = APIRouter(prefix="/api/test", tags=["test-simulation"])

def _require_test_endpoints():
    enabled = os.getenv("TIKTOBS_TEST_ENDPOINTS", "0").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        raise HTTPException(
            status_code=403,
            detail="Test endpoints are disabled. Set TIKTOBS_TEST_ENDPOINTS=1 to enable them.",
        )


@router.post("/comment-vote")
async def simulate_comment_vote():
    _require_test_endpoints()
    if not poll_manager.is_active:
        raise HTTPException(status_code=400, detail="No active poll to vote on")

    usernames = ["Ronaldo", "Messi", "Neymar", "Mbappe", "Salah", "Lewandowski", "Kane"]
    user = random.choice(usernames)

    candidates = poll_manager.candidates
    if not candidates:
        raise HTTPException(status_code=400, detail="Active poll has no candidates")

    # Vote with the candidate's unique 1-based sequence number rather than
    # their name: duplicate candidate names are ambiguous and get rejected by
    # the poll, which made this simulate button flaky. A sequence number always
    # matches exactly one candidate.
    idx = random.randrange(len(candidates))
    c = candidates[idx]
    vote_text = str(idx + 1)

    success = await poll_manager.record_vote(user, vote_text)
    if success:
        poll_status = await poll_manager.get_status()
        await state.manager.broadcast({
            "type": "poll_update",
            "poll": poll_status
        })
        return {"status": "success", "username": user, "vote": vote_text, "candidate": c["name"]}
    return {"status": "skipped", "message": "Vote match failed"}


@router.post("/gift-vote")
async def simulate_gift_vote():
    _require_test_endpoints()
    if not poll_manager.is_active:
        raise HTTPException(status_code=400, detail="No active poll to vote on")

    usernames = ["GamerGokil", "StreamLover", "SultanChat", "WibuJaya", "PocongImut"]
    user = random.choice(usernames)

    candidates_with_gifts = [c for c in poll_manager.candidates if c.get("gift_name")]
    if not candidates_with_gifts:
        # Dynamically auto-assign mock gift triggers for the sake of the simulation!
        mock_gifts = ["Rose", "TikTok", "Finger Heart", "Doughnut"]
        for idx, c in enumerate(poll_manager.candidates):
            c["gift_name"] = mock_gifts[idx % len(mock_gifts)]
        candidates_with_gifts = poll_manager.candidates

    c = random.choice(candidates_with_gifts)
    gift_name = c["gift_name"]
    diamond_count = random.choice([5, 10, 50, 99, 299])

    success, candidate_name, votes_added, via_comment = await poll_manager.record_gift_vote(gift_name, diamond_count)
    if success:
        poll_status = await poll_manager.get_status()
        await state.manager.broadcast({
            "type": "poll_update",
            "poll": poll_status
        })
        await state.manager.broadcast({
            "type": "poll_gift_vote",
            "username": user,
            "nickname": f"{user} ✨",
            "gift_name": gift_name,
            "diamond_count": diamond_count,
            "candidate_name": candidate_name,
            "votes_added": votes_added
        })
        return {"status": "success", "username": user, "gift": gift_name, "votes": votes_added, "candidate": candidate_name}
    return {"status": "failed"}


@router.post("/gift-normal")
async def simulate_gift_normal():
    _require_test_endpoints()
    usernames = ["SultanMuda", "BagasGanteng", "RaraKawaii", "DikaGaming", "TiktokUser"]
    user = random.choice(usernames)

    gifts = [
        ("Ice Cream", 1, "🍦"),
        ("TikTok", 1, "🎁"),
        ("Finger Heart", 5, "🫰"),
        ("Doughnut", 30, "🍩"),
        ("Cap", 99, "🧢"),
        ("Rose", 1, "🌹"),
        ("Corgi", 399, "🐶")
    ]

    poll_gifts = [c.get("gift_name").lower() for c in poll_manager.candidates if c.get("gift_name")]
    available_gifts = [g for g in gifts if g[0].lower() not in poll_gifts]
    if not available_gifts:
        available_gifts = gifts

    gift_name, diamond_count, emoji = random.choice(available_gifts)
    quantity = random.choice([1, 1, 2, 5])

    # If a live session is active, route the gift through the real event
    # processor (persist + poll counting). During an active poll this is what
    # exercises the poll_gift_ignored path for gifts no candidate owns.
    # Otherwise broadcast directly so the overlay display can still be tested
    # offline.
    use_processor = bool(state.processor and state.processor.session_id)

    if use_processor:
        raw_event = {
            "msg_id": f"mock-{random.randint(100000, 999999)}",
            "user": {"unique_id": user, "nickname": f"{user} 💎"},
            "gift_name": gift_name,
            "quantity": quantity,
            "diamond_count": diamond_count,
            "gift_type": 2,
            "repeat_end": 1,
        }
        await state.processor.process_raw_event("gift", raw_event)
    else:
        event_data = {
            "type": "event",
            "event": {
                "id": f"mock-{random.randint(100000, 999999)}",
                "event_type": "gift",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "username": user,
                "nickname": f"{user} 💎",
                "data": {
                    "gift_id": random.randint(1000, 9999),
                    "gift_name": gift_name,
                    "quantity": quantity,
                    "diamond_count": diamond_count,
                    "gift_type": 2,
                    "repeat_end": 1
                }
            }
        }
        await state.manager.broadcast(event_data)
    return {"status": "success", "username": user, "gift": gift_name, "quantity": quantity, "diamonds": diamond_count, "via_processor": use_processor}


@router.post("/gift-combo")
async def simulate_gift_combo(payload: dict = Body(default={})):
    """Simulate a full TikTok gift streak / combo.

    Emits one event per increment (gift_type=1, repeat_end=0, growing
    repeat_count) followed by a single FINAL event (repeat_end=1) that
    carries the full count. This mirrors the real TikTok schema and drives
    the combo-consolidation UI on the overlays.

    Optional body: {username, gift_name, count, diamond_count}.
    """
    _require_test_endpoints()

    usernames = ["ComboKing", "RoseSpammer", "GiftMachine", "StreakLord", "HypeBeast"]
    user = payload.get("username") or random.choice(usernames)
    gift_name = payload.get("gift_name") or "Rose"
    diamond_count = int(payload.get("diamond_count") or 1)
    count = max(2, min(int(payload.get("count") or random.randint(3, 8)), 50))

    # If a live session is active, route the streak through the real event
    # processor (persist + poll counting + broadcast). Otherwise broadcast
    # directly so the overlay display can still be tested offline.
    use_processor = bool(state.processor and state.processor.session_id)

    nonce = random.randint(100000, 999999)
    for i in range(1, count + 1):
        is_final = i == count
        timestamp = datetime.now(timezone.utc).isoformat()

        if use_processor:
            raw_event = {
                "msg_id": f"mock-combo-{nonce}-{i}",
                "username": user,
                "nickname": f"{user} 🔥",
                "gift_name": gift_name,
                "quantity": i,
                "diamond_count": diamond_count,
                "gift_type": 1,
                "repeat_end": 1 if is_final else 0,
            }
            await state.processor.process_raw_event("gift", raw_event)
        else:
            event_data = {
                "type": "event",
                "event": {
                    "id": f"mock-combo-{nonce}-{i}",
                    "event_type": "gift",
                    "timestamp": timestamp,
                    "username": user,
                    "nickname": f"{user} 🔥",
                    "data": {
                        "gift_id": "0",
                        "gift_name": gift_name,
                        "quantity": i,
                        "diamond_count": diamond_count,
                        "gift_type": 1,
                        "repeat_end": 1 if is_final else 0,
                    },
                },
            }
            await state.manager.broadcast(event_data)

        if not is_final:
            await asyncio.sleep(0.35)  # pace the increments like a real combo

    return {
        "status": "success",
        "username": user,
        "gift": gift_name,
        "combo_count": count,
        "diamonds_each": diamond_count,
        "via_processor": use_processor,
    }
