import json
import os
import requests
from datetime import datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

BUFFER_URL = "https://api.buffer.com"


def _need(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required GitHub Secret/Variable is missing: {name}")
    return value


def buffer_api(query):
    response = requests.post(
        BUFFER_URL,
        headers={"Authorization": f"Bearer {_need('BUFFER_API_KEY')}", "Content-Type": "application/json"},
        json={"query": query}, timeout=45,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errors"):
        raise RuntimeError("Buffer GraphQL: " + "; ".join(x.get("message", "error") for x in data["errors"]))
    if "data" not in data:
        raise RuntimeError(f"Unexpected Buffer response: {data}")
    return data["data"]


def verify_channel():
    channel_id = _need("BUFFER_CHANNEL_ID")
    expected = os.getenv("BUFFER_EXPECTED_CHANNEL_NAME", "").strip()
    query = f'''query VerifyFacebookDestination {{
      channel(input: {{ id: {json.dumps(channel_id)} }}) {{
        id name displayName service isDisconnected isLocked isQueuePaused
      }}
    }}'''
    channel = buffer_api(query).get("channel")
    if not channel:
        raise RuntimeError("Buffer did not return the configured channel.")
    names = {str(channel.get("name") or "").strip().casefold(),
             str(channel.get("displayName") or "").strip().casefold()}
    if expected and expected.casefold() not in names:
        raise RuntimeError(f"SAFETY STOP: channel mismatch; expected '{expected}', got '{channel.get('name')}' / '{channel.get('displayName')}'.")
    if str(channel.get("service", "")).casefold() != "facebook":
        raise RuntimeError("SAFETY STOP: configured Buffer destination is not Facebook.")
    if channel.get("isDisconnected") or channel.get("isLocked") or channel.get("isQueuePaused"):
        raise RuntimeError("SAFETY STOP: Facebook channel is disconnected, locked, or queue-paused.")
    return channel


def next_publish_time():
    """Return the next fixed Pakistan-time publishing slot as a UTC ISO timestamp."""
    tz = ZoneInfo("Asia/Karachi")
    now = datetime.now(tz)
    slots = (dt_time(9, 0), dt_time(13, 0), dt_time(17, 0), dt_time(21, 0))
    candidates = []
    for day_offset in (0, 1):
        target_date = now.date() + timedelta(days=day_offset)
        for slot in slots:
            candidate = datetime.combine(target_date, slot, tzinfo=tz)
            # Leave a small buffer so rendering/upload finishing close to a slot
            # does not result in a past-due schedule.
            if candidate > now + timedelta(minutes=5):
                candidates.append(candidate)
    if not candidates:
        raise RuntimeError("Could not calculate the next Facebook publishing slot.")
    target = min(candidates)
    return target.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def queue_facebook_reel(video_url, caption):
    verify_channel()
    channel_id = _need("BUFFER_CHANNEL_ID")
    if not video_url.startswith("https://res.cloudinary.com/"):
        raise RuntimeError("Only a public Cloudinary HTTPS video URL may be queued.")
    due_at = next_publish_time()
    mutation = f'''mutation QueueMovieFacebookReel {{
      createPost(input: {{
        text: {json.dumps(caption, ensure_ascii=False)}
        channelId: {json.dumps(channel_id)}
        schedulingType: automatic
        mode: customScheduled
        dueAt: {json.dumps(due_at)}
        assets: [{{ video: {{ url: {json.dumps(video_url)} }} }}]
        metadata: {{ facebook: {{ type: reel }} }}
        aiAssisted: false
      }}) {{
        ... on PostActionSuccess {{ post {{ id status dueAt channelId }} }}
        ... on MutationError {{ message }}
      }}
    }}'''
    result = buffer_api(mutation).get("createPost") or {}
    if result.get("message"):
        raise RuntimeError("Buffer rejected Facebook Reel: " + result["message"])
    post = result.get("post")
    if not post or not post.get("id"):
        raise RuntimeError(f"Buffer did not confirm Reel queue creation: {result}")
    if post.get("channelId") and post["channelId"] != channel_id:
        raise RuntimeError("SAFETY STOP: Buffer returned an unexpected destination channel.")
    return post
