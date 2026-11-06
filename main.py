import argparse, asyncio, base64, json, logging, os, re, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import cloudinary, cloudinary.uploader, edge_tts, requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
WORK, OUTPUT = ROOT / "work", ROOT / "output"
W, H, FPS = 1080, 1920, 30
BUFFER_URL = "https://api.buffer.com"
STATE_PATH = "state/last_queued_date.txt"
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
EXPECTED_PAGE = os.getenv("BUFFER_EXPECTED_CHANNEL_NAME", "Funny Animals Comedy").strip()
VOICE = os.getenv("TTS_VOICE", "en-US-AriaNeural")
log = logging.getLogger("funny_animals")


def need(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required secret/variable: {name}")
    return value


def run(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"Command failed: {' '.join(map(str,args[:4]))}\n{p.stderr[-2500:]}")
    return p.stdout.strip()


def buffer_api(query):
    r = requests.post(BUFFER_URL, headers={
        "Authorization": f"Bearer {need('BUFFER_API_KEY')}",
        "Content-Type": "application/json"
    }, json={"query": query}, timeout=45)
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        raise RuntimeError("Buffer GraphQL: " + "; ".join(x.get("message","error") for x in data["errors"]))
    if "data" not in data:
        raise RuntimeError(f"Unexpected Buffer response: {data}")
    return data["data"]


def verify_channel():
    channel_id = need("BUFFER_CHANNEL_ID")
    query = f'''query VerifyFunnyAnimals {{
      channel(input: {{ id: {json.dumps(channel_id)} }}) {{
        id name displayName service isDisconnected isLocked isQueuePaused
      }}
    }}'''
    channel = buffer_api(query).get("channel")
    if not channel:
        raise RuntimeError("Buffer did not return the configured channel.")
    names = {str(channel.get("name") or "").strip().casefold(),
             str(channel.get("displayName") or "").strip().casefold()}
    if EXPECTED_PAGE.casefold() not in names:
        raise RuntimeError("SAFETY STOP: channel name mismatch. No post created. "
                           f"Expected '{EXPECTED_PAGE}', got '{channel.get('name')}' / "
                           f"'{channel.get('displayName')}'.")
    if str(channel.get("service","")).casefold() != "facebook":
        raise RuntimeError("SAFETY STOP: selected Buffer channel is not Facebook.")
    if channel.get("isDisconnected") or channel.get("isLocked") or channel.get("isQueuePaused"):
        raise RuntimeError("SAFETY STOP: Facebook channel is disconnected, locked, or queue-paused.")
    log.info("Verified Buffer destination: %s (%s)", channel.get("displayName") or channel.get("name"), channel_id)
    return channel


def read_state():
    repo, token = need("GITHUB_REPOSITORY"), need("GITHUB_TOKEN")
    url = f"https://api.github.com/repos/{repo}/contents/{quote(STATE_PATH, safe='/')}"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}",
                                   "Accept": "application/vnd.github+json"}, timeout=30)
    if r.status_code == 404:
        return "never", None
    r.raise_for_status()
    item = r.json()
    return base64.b64decode(item["content"]).decode().strip() or "never", item["sha"]


def write_state(day, sha):
    repo, token = need("GITHUB_REPOSITORY"), need("GITHUB_TOKEN")
    url = f"https://api.github.com/repos/{repo}/contents/{quote(STATE_PATH, safe='/')}"
    body = {"message": f"Record Funny Animals queue date {day}",
            "content": base64.b64encode((day + "\n").encode()).decode(),
            "branch": os.getenv("GITHUB_REF_NAME", "main")}
    if sha:
        body["sha"] = sha
    r = requests.put(url, headers={"Authorization": f"Bearer {token}",
                                   "Accept": "application/vnd.github+json"},
                     json=body, timeout=30)
    r.raise_for_status()
    log.info("Daily duplicate guard updated: %s", day)


def local_story_fallback():
    """Return an original six-scene story when Gemini is temporarily unavailable."""
    stories = [
        {
            "title": "The Great Biscuit Mix-Up",
            "caption": "Two friends, one missing biscuit, and a very silly mystery! #FunnyAnimals #AnimalComedy",
            "characters": [{"name": "Milo", "species": "dog"}, {"name": "Pip", "species": "cat"}],
            "scenes": [
                {"visual": "Milo proudly guards an empty biscuit plate", "narration": "Milo announced that he had saved the last biscuit for a very special guest."},
                {"visual": "Pip examines a few crumbs with a magnifying glass", "narration": "Pip arrived wearing a detective hat and said, this case smells delicious."},
                {"visual": "Milo points toward a trail of crumbs", "narration": "The friends followed tiny crumbs across the room, past a cushion and a toy."},
                {"visual": "Pip discovers crumbs on Milo's nose", "narration": "Pip paused, then noticed a crumb sitting right on Milo's nose."},
                {"visual": "Milo looks surprised while Pip giggles", "narration": "Milo checked his nose and remembered he had taste-tested the biscuit earlier."},
                {"visual": "Both friends share a fresh snack", "narration": "They solved the mystery together and agreed that sharing snacks was best."}
            ]
        },
        {
            "title": "The Very Serious Dance Lesson",
            "caption": "A dance teacher discovers an unexpected talent! #FunnyAnimals #AnimalComedy",
            "characters": [{"name": "Bella", "species": "rabbit"}, {"name": "Rocky", "species": "bear"}],
            "scenes": [
                {"visual": "Bella sets up a tiny dance class", "narration": "Bella opened a dance class and promised to teach one perfect move."},
                {"visual": "Rocky arrives wearing a colorful scarf", "narration": "Rocky arrived early and asked whether dancing required remembering left and right."},
                {"visual": "Bella demonstrates a simple side step", "narration": "Bella showed a gentle side step, followed by a little turn."},
                {"visual": "Rocky turns the wrong way but stays cheerful", "narration": "Rocky turned the other way and accidentally invented a brand-new dance."},
                {"visual": "Bella copies Rocky's funny dance", "narration": "Bella tried the move and discovered it was surprisingly fun."},
                {"visual": "Friends celebrate their new dance", "narration": "They named it the Happy Wobble and performed it together."}
            ]
        },
        {
            "title": "The Tiny Garden Helper",
            "caption": "A little gardening help grows into a big surprise! #FunnyAnimals #AnimalComedy",
            "characters": [{"name": "Sunny", "species": "fox"}, {"name": "Dot", "species": "duck"}],
            "scenes": [
                {"visual": "Sunny prepares a small garden bed", "narration": "Sunny wanted to grow the tallest sunflower in the whole garden."},
                {"visual": "Dot arrives with a tiny watering can", "narration": "Dot offered to help and brought a watering can almost as big as herself."},
                {"visual": "Friends gently water the soil", "narration": "They planted a seed and gave the soil a careful little drink."},
                {"visual": "Dot checks the soil every few moments", "narration": "Dot checked for a flower every minute and asked if it was ready yet."},
                {"visual": "A small green sprout appears", "narration": "At last, a tiny green sprout appeared, and both friends cheered."},
                {"visual": "Friends admire the sprout in sunshine", "narration": "It was not the tallest sunflower yet, but it was their favorite beginning."}
            ]
        }
    ]
    day_number = datetime.now(timezone.utc).date().toordinal()
    story = stories[day_number % len(stories)]
    log.warning("OpenRouter unavailable; using built-in local story fallback.")
    return json.loads(json.dumps(story))

def make_story():
    """Generate a safe six-scene story through OpenRouter, with a local fallback."""
    api_key = need("OPENROUTER_API_KEY")
    prompt = """Write an original, harmless, family-friendly animal comedy story in English.
No cruelty, violence, dangerous stunts, frightening scenes, copyrighted characters,
brands, celebrities or impersonations. Make it funny and understandable without sound.
Return ONLY valid JSON in this shape:
{"title":"up to 8 words","caption":"1-2 engaging sentences plus 3-5 hashtags",
"characters":[{"name":"name","species":"cat"},{"name":"name","species":"dog"}],
"scenes":[{"visual":"short visual cue","narration":"12-24 spoken words"}]}
Exactly 2 characters and exactly 6 scenes. Keep species and names consistent.
Narration must be short, natural spoken dialogue/story, without stage directions."""

    response_text = None
    for attempt in range(3):
        try:
            log.info("Generating story with OpenRouter free router (attempt %s/3)", attempt + 1)
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "X-Title": "Animated Jungle"
                },
                json={
                    "model": "openrouter/free",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.9,
                    "max_tokens": 1800
                },
                timeout=90
            )
            if response.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(
                    f"Temporary OpenRouter error {response.status_code}: {response.text[:500]}",
                    response=response
                )
            response.raise_for_status()
            payload = response.json()
            response_text = payload["choices"][0]["message"]["content"]
            if isinstance(response_text, list):
                response_text = "".join(
                    part.get("text", "") for part in response_text
                    if isinstance(part, dict)
                )
            if not isinstance(response_text, str) or not response_text.strip():
                raise ValueError("OpenRouter returned an empty story.")
            break
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"OpenRouter request failed: {exc}") from exc
            if attempt == 2:
                log.warning("OpenRouter remained unavailable after retries: %s", exc)
            else:
                delay = 5 * (2 ** attempt)
                log.warning("Temporary OpenRouter error; retrying in %s seconds.", delay)
                time.sleep(delay)
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt == 2:
                log.warning("OpenRouter connection failed after retries: %s", exc)
            else:
                delay = 5 * (2 ** attempt)
                log.warning("OpenRouter connection issue; retrying in %s seconds.", delay)
                time.sleep(delay)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            if attempt == 2:
                log.warning("OpenRouter returned an unusable response: %s", exc)
            else:
                log.warning("OpenRouter response was unusable; retrying.")
                time.sleep(5 * (2 ** attempt))

    if response_text is None:
        return local_story_fallback()

    # Accept JSON wrapped in Markdown fences, while rejecting non-JSON output.
    cleaned = response_text.strip()
    cleaned = re.sub(r"^\`\`\`(?:json)?\\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\\s*\`\`\`$", "", cleaned)
    first, last = cleaned.find("{"), cleaned.rfind("}")
    if first < 0 or last <= first:
        log.warning("OpenRouter did not return a JSON object; using local story.")
        return local_story_fallback()
    try:
        story = json.loads(cleaned[first:last + 1])
    except json.JSONDecodeError:
        log.warning("OpenRouter returned invalid JSON; using local story.")
        return local_story_fallback()

    if not isinstance(story, dict) or len(story.get("characters", [])) != 2 or len(story.get("scenes", [])) != 6:
        log.warning("OpenRouter story did not contain exactly two characters and six scenes; using local story.")
        return local_story_fallback()
    for c in story["characters"]:
        if not isinstance(c, dict):
            return local_story_fallback()
        c["name"] = str(c.get("name", "Pal"))[:24]
        c["species"] = str(c.get("species", "cat")).lower()[:20]
    for s in story["scenes"]:
        if not isinstance(s, dict):
            return local_story_fallback()
        s["visual"] = str(s.get("visual", "A silly animal moment"))[:150]
        s["narration"] = str(s.get("narration", "")).strip()[:350]
        if not s["narration"]:
            return local_story_fallback()
    story["title"] = str(story.get("title", "A Silly Animal Day"))[:70]
    story["caption"] = str(story.get("caption", "A little animal chaos! #FunnyAnimals"))[:450]
    log.info("Story generated successfully with OpenRouter.")
    return story

def font(size, bold=False):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(p, size) if Path(p).exists() else ImageFont.load_default()


def wrap(draw, text, f, width):
    lines, current = [], ""
    for word in text.split():
        test = (current + " " + word).strip()
        if draw.textbbox((0,0), test, font=f)[2] <= width:
            current = test
        else:
            if current: lines.append(current)
            current = word
    if current: lines.append(current)
    return lines


def animal(draw, x, y, species, name, idx):
    palette = {"dog":"#C98A52","cat":"#E7A35A","rabbit":"#E8D5C7","fox":"#D96D35",
               "bear":"#8C654C","panda":"#F3F3F3","monkey":"#A96F45","duck":"#F5D447",
               "lion":"#C78B39","pig":"#F2A6A6"}
    fur = palette.get(species, "#9AAFC0")
    dark = "#222222"
    draw.ellipse((x-140,y+60,x+140,y+360), fill=fur, outline=dark, width=7)
    draw.ellipse((x-150,y-150,x+150,y+150), fill=fur, outline=dark, width=7)
    if species == "rabbit":
        draw.ellipse((x-105,y-300,x-35,y-80), fill=fur, outline=dark, width=6)
        draw.ellipse((x+35,y-300,x+105,y-80), fill=fur, outline=dark, width=6)
    elif species in ("cat","fox","dog","bear","lion"):
        for side in (-1,1):
            ex=x+side*105
            draw.ellipse((ex-48,y-230,ex+48,y-85), fill=fur, outline=dark, width=6)
    elif species == "panda":
        for side in (-1,1):
            ex=x+side*105
            draw.ellipse((ex-42,y-190,ex+42,y-100), fill=dark)
            draw.ellipse((x+side*60-35,y-20,x+side*60+35,y+65), fill=dark)
    for side in (-1,1):
        ex=x+side*55
        draw.ellipse((ex-12,y-8,ex+12,y+18), fill=dark)
    draw.ellipse((x-58,y+38,x+58,y+115), fill="#F5D7B8", outline=dark, width=4)
    draw.ellipse((x-12,y+58,x+12,y+78), fill=dark)
    draw.arc((x-35,y+65,x+35,y+125), 5, 175, fill=dark, width=5)
    f=font(28,True)
    tw=draw.textbbox((0,0),name,font=f)[2]
    draw.rounded_rectangle((x-tw//2-16,y+375,x+tw//2+16,y+425), radius=15, fill="white", outline=dark, width=3)
    draw.text((x-tw//2,y+382),name,font=f,fill=dark)


def render_frame(story, scene, index, path):
    colors=[("#F9DDB2","#F2B8A0"),("#CBE8E3","#A9D2C8"),("#E5D8F4","#C5B4E8"),
            ("#F7E7A7","#F4C76B"),("#D6E6F7","#A9C8EA"),("#F5D2D7","#ECAEB9")]
    top,bottom=colors[index%len(colors)]
    im=Image.new("RGB",(W,H),top); d=ImageDraw.Draw(im)
    d.rectangle((0,1180,W,H),fill=bottom)
    for i in range(8):
        x=(i*161+index*47)%W; y=260+(i%3)*180
        d.ellipse((x-28,y-28,x+28,y+28),fill="#FFFFFF")
    d.rounded_rectangle((55,55,W-55,190),radius=35,fill="#202A44")
    d.text((90,78),"FUNNY ANIMALS",font=font(58,True),fill="white")
    d.text((92,145),f"ORIGINAL COMEDY  •  SCENE {index+1}/6",font=font(25,True),fill="#FFD85A")
    cue=wrap(d,scene["visual"],font(30,True),900)[:2]
    yy=245
    for line in cue:
        d.text((80,yy),line,font=font(30,True),fill="#26344D"); yy+=43
    c=story["characters"]
    animal(d,320,850,c[0]["species"],c[0]["name"],index)
    animal(d,760,850,c[1]["species"],c[1]["name"],index+1)
    d.text((470,510),"?!" if index%2==0 else "★",font=font(100,True),fill="#F06B48",stroke_width=3,stroke_fill="white")
    lines=wrap(d,scene["narration"],font(42,True),850)[:4]
    panel_top=1450
    d.rounded_rectangle((55,panel_top,W-55, min(H-55,panel_top+110+len(lines)*58)),
                        radius=32,fill="#202A44",outline="white",width=5)
    yy=panel_top+35
    for line in lines:
        tw=d.textbbox((0,0),line,font=font(42,True))[2]
        d.text(((W-tw)//2,yy),line,font=font(42,True),fill="white"); yy+=58
    d.text((70,H-90),"FOLLOW FOR MORE ANIMAL LAUGHS",font=font(25,True),fill="#202A44")
    im.save(path,quality=94)


async def speak(text, path):
    await edge_tts.Communicate(text=text, voice=VOICE, rate="+2%").save(str(path))


def render_video(story):
    for cmd in ("ffmpeg","ffprobe"): run([cmd,"-version"])
    WORK.mkdir(exist_ok=True); OUTPUT.mkdir(exist_ok=True)
    for p in WORK.iterdir():
        if p.is_file(): p.unlink()
    segments=[]
    for i,scene in enumerate(story["scenes"]):
        frame=WORK/f"scene_{i}.jpg"; audio=WORK/f"voice_{i}.mp3"; segment=WORK/f"segment_{i}.mp4"
        render_frame(story,scene,i,frame)
        asyncio.run(speak(scene["narration"],audio))
        seconds=float(run(["ffprobe","-v","error","-show_entries","format=duration",
                           "-of","default=noprint_wrappers=1:nokey=1",str(audio)]))
        seconds=max(3.0,seconds+0.25)
        run(["ffmpeg","-y","-loop","1","-framerate",str(FPS),"-i",str(frame),"-i",str(audio),
             "-t",f"{seconds:.2f}","-vf","scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='min(zoom+0.001,1.08)':d=1:s=1080x1920:fps=30,format=yuv420p",
             "-r",str(FPS),"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac",
             "-b:a","128k","-shortest",str(segment)])
        segments.append(segment)
    concat=WORK/"concat.txt"
    concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in segments),encoding="utf-8")
    slug=re.sub(r"[^a-z0-9]+","-",story["title"].lower()).strip("-")[:30] or "animal-comedy"
    out=OUTPUT/f"funny-animals-{datetime.now(timezone.utc):%Y%m%d}-{slug}.mp4"
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy","-movflags","+faststart",str(out)])
    info=json.loads(run(["ffprobe","-v","error","-show_entries","format=duration,size:stream=codec_type,codec_name,width,height",
                         "-of","json",str(out)]))
    v=next((s for s in info.get("streams",[]) if s.get("codec_type")=="video"),None)
    duration=float(info["format"]["duration"])
    if not v or (v.get("width"),v.get("height"))!=(W,H) or not 12<=duration<=180:
        raise RuntimeError("Final MP4 failed dimensions or duration validation.")
    log.info("Rendered %s (%.1f seconds)",out,duration)
    return out


def upload_video(path):
    cloudinary.config(cloud_name=need("CLOUDINARY_CLOUD_NAME"),
                      api_key=need("CLOUDINARY_API_KEY"),
                      api_secret=need("CLOUDINARY_API_SECRET"),secure=True)
    result=cloudinary.uploader.upload(
        str(path),resource_type="video",
        folder=os.getenv("CLOUDINARY_FOLDER","funny-animals-comedy"),
        public_id=f"funny-animals-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}",
        overwrite=False,unique_filename=False,type="upload")
    url=result.get("secure_url","")
    if not url.startswith("https://res.cloudinary.com/"):
        raise RuntimeError("Cloudinary did not return a public HTTPS video URL.")
    r=requests.get(url,stream=True,timeout=45); r.raise_for_status(); r.close()
    return url


def queue_reel(video_url,caption):
    channel=verify_channel()
    channel_id=need("BUFFER_CHANNEL_ID")
    mutation=f'''mutation CreateFunnyAnimalsReel {{
      createPost(input: {{
        text: {json.dumps(caption,ensure_ascii=False)}
        channelId: {json.dumps(channel_id)}
        schedulingType: automatic
        mode: addToQueue
        assets: [{{ video: {{ url: {json.dumps(video_url)} }} }}]
        metadata: {{ facebook: {{ type: reel }} }}
        aiAssisted: true
      }}) {{
        ... on PostActionSuccess {{ post {{ id status dueAt channelId }} }}
        ... on MutationError {{ message }}
      }}
    }}'''
    result=buffer_api(mutation).get("createPost") or {}
    if result.get("message"): raise RuntimeError("Buffer rejected Reel: "+result["message"])
    post=result.get("post")
    if not post or not post.get("id"): raise RuntimeError(f"Buffer did not confirm post creation: {result}")
    if post.get("channelId") and post["channelId"]!=channel_id:
        raise RuntimeError("SAFETY STOP: Buffer returned an unexpected destination.")
    log.info("Buffer accepted Reel %s; status=%s dueAt=%s",post["id"],post.get("status"),post.get("dueAt"))
    log.info("Accepted/queued is NOT the same as confirmed published on Facebook.")
    return post


def validate():
    for key in ("OPENROUTER_API_KEY","CLOUDINARY_CLOUD_NAME","CLOUDINARY_API_KEY","CLOUDINARY_API_SECRET"):
        need(key)
    verify_channel()
    run(["ffmpeg","-version"]); run(["ffprobe","-version"])
    log.info("Validation passed. No video generated, uploaded, or posted.")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--validate",action="store_true")
    args=parser.parse_args()
    if args.validate:
        validate(); return
    today=datetime.now(timezone.utc).date().isoformat()
    previous,sha=read_state()
    if previous==today:
        log.info("Already queued one video for %s; skipping duplicate.",today); return
    verify_channel()
    story=make_story()
    log.info("Story: %s",story["title"])
    video=render_video(story)
    public_url=upload_video(video)
    post=queue_reel(public_url,story["caption"])
    write_state(today,sha)
    log.info("COMPLETE: Buffer accepted post %s. Publication still needs confirmation.",post["id"])


if __name__=="__main__":
    logging.basicConfig(level=logging.INFO,format="%(asctime)s | %(levelname)s | %(message)s")
    try: main()
    except Exception:
        log.exception("Automation failed safely.")
        sys.exit(1)
