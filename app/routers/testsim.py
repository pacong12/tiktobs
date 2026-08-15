"""Simulated testing endpoints (can be disabled via TIKTOBS_TEST_ENDPOINTS=0)."""

import os
import random
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app import state
from app.poll import poll_manager

router = APIRouter(prefix="/api/test", tags=["test-simulation"])

TEST_ENDPOINTS_ENABLED = os.getenv("TIKTOBS_TEST_ENDPOINTS", "1").strip().lower() not in ("0", "false", "no", "off")


def _require_test_endpoints():
    if not TEST_ENDPOINTS_ENABLED:
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

    c = random.choice(candidates)
    vote_text = random.choice([c["id"], c["name"]])

    success = await poll_manager.record_vote(user, vote_text)
    if success:
        poll_status = await poll_manager.get_status()
        await state.manager.broadcast({
            "type": "poll_update",
            "poll": poll_status
        })
        return {"status": "success", "username": user, "vote": vote_text, "candidate": c["name"]}
    return {"status": "skipped", "message": "User already voted or match failed"}


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

    success, candidate_name, votes_added = await poll_manager.record_gift_vote(gift_name, diamond_count)
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
                "diamond_count": diamond_count
            }
        }
    }
    await state.manager.broadcast(event_data)
    return {"status": "success", "username": user, "gift": gift_name, "quantity": quantity, "diamonds": diamond_count}
