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


def buffer_api(query, retries=2):
    """Retry transient Buffer reads; createPost callers explicitly disable retries."""
    attempts = max(1, int(retries) + 1)
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.post(
                BUFFER_URL,
                headers={"Authorization": f"Bearer {_need('BUFFER_API_KEY')}", "Content-Type": "application/json"},
                json={"query": query}, timeout=45,
            )
            if response.status_code in (408, 425, 429) or response.status_code >= 500:
                last_error = RuntimeError(f"Temporary Buffer HTTP {response.status_code}: {response.text[:300]}")
                if attempt + 1 < attempts:
                    import time
                    time.sleep(min(2 ** attempt, 8))
                    continue
            response.raise_for_status()
            data = response.json()
            if data.get("errors"):
                raise RuntimeError("Buffer GraphQL: " + "; ".join(x.get("message", "error") for x in data["errors"]))
            if "data" not in data:
                raise RuntimeError(f"Unexpected Buffer response: {data}")
            return data["data"]
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                import time
                time.sleep(min(2 ** attempt, 8))
                continue
            raise RuntimeError(f"Buffer connection failed after retries: {exc}") from exc
    raise RuntimeError(f"Buffer API failed after retries: {last_error}")


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


def next_publish_time(reserved_slots=None):
    """Return the earliest unused Pakistan-time slot, avoiding same-time queue collisions."""
    tz = ZoneInfo("Asia/Karachi")
    now = datetime.now(tz)
    slots = (dt_time(9, 0), dt_time(13, 0), dt_time(17, 0), dt_time(21, 0))
    reserved = set()
    for value in (reserved_slots or []):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            reserved.add(parsed.astimezone(timezone.utc).replace(microsecond=0))
        except (TypeError, ValueError):
            continue

    # Search far enough ahead that a burst of manual/workflow runs cannot
    # collapse onto one slot or exhaust the candidate window.
    for day_offset in range(0, 15):
        target_date = now.date() + timedelta(days=day_offset)
        for slot in slots:
            candidate = datetime.combine(target_date, slot, tzinfo=tz)
            if candidate <= now + timedelta(minutes=5):
                continue
            candidate_utc = candidate.astimezone(timezone.utc).replace(microsecond=0)
            if candidate_utc not in reserved:
                return candidate_utc.isoformat(timespec="seconds").replace("+00:00", "Z")
    raise RuntimeError("Could not find an unused Facebook publishing slot in the next 15 days.")


def queue_facebook_reel(video_url, caption, reserved_slots=None):
    verify_channel()
    channel_id = _need("BUFFER_CHANNEL_ID")
    is_cloudinary = video_url.startswith("https://res.cloudinary.com/")
    is_github_release = (
        video_url.startswith("https://github.com/")
        and "/releases/download/" in video_url
    )
    if not (is_cloudinary or is_github_release):
        raise RuntimeError("Only a public Cloudinary or GitHub Release HTTPS video URL may be queued.")
    due_at = next_publish_time(reserved_slots)
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
    # Never retry createPost automatically: an accepted request with a lost
    # response could otherwise create a duplicate scheduled post.
    result = buffer_api(mutation, retries=0).get("createPost") or {}
    if result.get("message"):
        raise RuntimeError("Buffer rejected Facebook Reel: " + result["message"])
    post = result.get("post")
    if not post or not post.get("id"):
        raise RuntimeError(f"Buffer did not confirm Reel queue creation: {result}")
    if post.get("channelId") and post["channelId"] != channel_id:
        raise RuntimeError("SAFETY STOP: Buffer returned an unexpected destination channel.")
    post.setdefault("dueAt", due_at)
    return post
