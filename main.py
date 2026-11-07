import argparse, asyncio, base64, io, json, logging, math, os, re, subprocess, sys, time
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


def boss_story():
    """A fixed six-scene animal adaptation of the 'little boss' comedy concept."""
    return {
        "title": "The Monkey Jungle Boss",
        "caption": "Monkey found a big hat and declared himself the jungle boss. Rabbit had other plans! #AnimatedJungle #FunnyAnimals #AnimalComedy",
        "characters": [
            {"name": "Momo", "species": "monkey"},
            {"name": "Bun", "species": "rabbit"}
        ],
        "scenes": [
            {"visual": "Momo discovers a huge fancy hat and puts it on proudly",
             "narration": "Momo found a giant hat, placed it on his head, and announced, I am the boss of this jungle!"},
            {"visual": "Momo gives Rabbit a very serious order",
             "narration": "Momo pointed at Bun and said, First rule, everyone must call me Your Bossness!"},
            {"visual": "Bun asks the new boss to tidy the jungle path",
             "narration": "Bun nodded politely and asked, Great boss, could you please tidy the path for everyone?"},
            {"visual": "Momo tries to avoid the broom and hide behind his hat",
             "narration": "Momo suddenly remembered an important meeting, but Bun handed him a little broom."},
            {"visual": "Momo sweeps leaves while Bun watches with a smile",
             "narration": "The boss swept one leaf, then two, then discovered the whole jungle needed cleaning."},
            {"visual": "The hat slips onto Bun and Momo laughs",
             "narration": "When the hat slipped onto Bun, Momo laughed and said, You can be boss tomorrow!"}
        ]
    }


def local_story_fallback():
    """Use the selected original six-scene boss comedy if the story API is unavailable."""
    log.warning("OpenRouter unavailable; using the built-in Jungle Boss story.")
    return boss_story()

def make_story():
    """Generate a safe six-scene story through OpenRouter, with a local fallback."""
    api_key = need("OPENROUTER_API_KEY")
    prompt = """Write an original, harmless, family-friendly animal comedy story in English.
Use this exact comedy premise: a cheeky monkey finds an oversized fancy hat and declares
himself the boss of the jungle; a clever rabbit gives him a funny but harmless responsibility,
such as tidying the jungle path; finish with a playful hat-related twist.
No cruelty, violence, dangerous stunts, frightening scenes, copyrighted characters,
brands, celebrities or impersonations. Make it funny and understandable without sound.
Keep the monkey and rabbit as the two characters throughout all six scenes.
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
    cleaned = re.sub(r"^\`\`\`(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\`\`\`$", "", cleaned)
    first, last = cleaned.find("{"), cleaned.rfind("}")
    if first < 0 or last <= first:
        log.warning("OpenRouter did not return a JSON object; using local story.")
        return local_story_fallback()
    try:
        story = json.loads(cleaned[first:last + 1])
    except json.JSONDecodeError:
        log.warning("OpenRouter returned invalid JSON; using local story.")
        return local_story_fallback()

    if (
        not isinstance(story, dict)
        or not isinstance(story.get("characters"), list)
        or not isinstance(story.get("scenes"), list)
        or len(story["characters"]) != 2
        or len(story["scenes"]) != 6
    ):
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



def draw_background(draw, scene_index, frame_no, t):
    palettes = [
        ("#87D8F2", "#E4F8FF", "#7CCB72", "#3E9A61"),
        ("#A7DDF8", "#F1FAFF", "#78C879", "#368B55"),
        ("#F6D38A", "#FFF0C5", "#8CCB78", "#4C9B5B"),
        ("#9ED9F1", "#E9F8FF", "#70BD72", "#347E51"),
        ("#B7DDF4", "#F2FAFF", "#82C978", "#3C965B"),
        ("#F8D99C", "#FFF3D6", "#83C878", "#3D8F56")
    ]
    sky, cloud, hill, ground = palettes[scene_index % len(palettes)]
    for y in range(H):
        q = y / H
        if q < 0.68:
            c1 = tuple(int(sky[i:i+2],16) for i in (1,3,5))
            c2 = tuple(int(cloud[i:i+2],16) for i in (1,3,5))
            k = q / 0.68
            color = tuple(int(c1[j]*(1-k)+c2[j]*k) for j in range(3))
        else:
            c1 = tuple(int(hill[i:i+2],16) for i in (1,3,5))
            c2 = tuple(int(ground[i:i+2],16) for i in (1,3,5))
            k = (q-0.68)/0.32
            color = tuple(int(c1[j]*(1-k)+c2[j]*k) for j in range(3))
        draw.line((0,y,W,y), fill=color)
    # Slow-moving clouds and layered rolling hills create visible parallax.
    for j in range(3):
        x = int((j*470 + frame_no*0.7) % (W+260)) - 130
        y = 250 + j*115
        draw.ellipse((x-100,y-35,x+10,y+35), fill="#FFFFFF")
        draw.ellipse((x-45,y-75,x+55,y+35), fill="#FFFFFF")
        draw.ellipse((x+5,y-40,x+115,y+35), fill="#FFFFFF")
    draw.ellipse((-230,1040,560,1510), fill=hill)
    draw.ellipse((440,1080,1320,1540), fill="#9BD28A")
    # Jungle trees and bushes.
    for side in (0,1):
        tx = 70 if side == 0 else 1010
        draw.rectangle((tx-22,620,tx+22,1320), fill="#8A5837")
        for ox,oy,r in [(-55,650,100),(45,620,120),(0,520,115),(-5,760,95)]:
            draw.ellipse((tx+ox-r,oy-r,tx+ox+r,oy+r), fill="#3C9D62")
        for bx in range(3):
            xx = tx + (bx-1)*75
            draw.ellipse((xx-95,1290,xx+95,1460), fill="#4BA968")
    # Sun and small drifting sparkles.
    draw.ellipse((850,150,1010,310), fill="#FFE27A")
    for j in range(8):
        x = int((j*151 + frame_no*1.4) % W)
        y = 420 + (j%3)*130 + int(8*math.sin(t*2+j))
        draw.ellipse((x-5,y-5,x+5,y+5), fill="#FFFFFF")


def draw_character(draw, x, base_y, species, name, frame_no, t, character_index):
    colors = {"dog":"#C98A52","cat":"#E7A35A","rabbit":"#E8D5C7","fox":"#D96D35",
              "bear":"#8C654C","panda":"#F3F3F3","monkey":"#A96F45","duck":"#F5D447",
              "lion":"#C78B39","pig":"#F2A6A6"}
    fur = colors.get(species, "#91AFC0")
    dark, cream = "#263047", "#FFF0D8"
    phase = t*5.2 + character_index*1.7
    bob = math.sin(phase)*13
    x = int(x + math.sin(t*1.8+character_index)*13)
    y = int(base_y + bob)
    head_y = y-185
    # Tail wiggles behind the body.
    tail_swing = int(math.sin(phase*1.3)*25)
    if species in ("dog","cat","fox","lion","monkey"):
        draw.line((x+105,y+60,x+175+tail_swing,y+5), fill=fur, width=25)
        draw.ellipse((x+158+tail_swing,y-12,x+190+tail_swing,y+22), fill=fur, outline=dark, width=4)
    elif species == "rabbit":
        draw.ellipse((x+105,y+30,x+170,y+95), fill="#FFFFFF", outline=dark, width=4)
    # Feet swing as the character bounces.
    step = int(math.sin(phase*1.5)*17)
    draw.ellipse((x-90,y+235,x-5,y+285+step), fill=dark)
    draw.ellipse((x+5,y+235-step,x+90,y+285), fill=dark)
    # Body and belly.
    draw.ellipse((x-125,y-5,x+125,y+270), fill=fur, outline=dark, width=7)
    draw.ellipse((x-76,y+72,x+76,y+230), fill=cream)
    # Arms move independently to make the character visibly act.
    left_hand = (x-190, y+35+int(math.sin(phase)*48))
    right_hand = (x+190, y+35+int(math.cos(phase)*48))
    draw.line((x-92,y+40,left_hand[0],left_hand[1]), fill=dark, width=31)
    draw.line((x+92,y+40,right_hand[0],right_hand[1]), fill=dark, width=31)
    draw.ellipse((left_hand[0]-25,left_hand[1]-25,left_hand[0]+25,left_hand[1]+25), fill=fur, outline=dark, width=4)
    draw.ellipse((right_hand[0]-25,right_hand[1]-25,right_hand[0]+25,right_hand[1]+25), fill=fur, outline=dark, width=4)
    # Head, ears and species details.
    draw.ellipse((x-137,head_y-130,x+137,head_y+140), fill=fur, outline=dark, width=7)
    if species == "rabbit":
        draw.ellipse((x-105,head_y-300,x-35,head_y-65), fill=fur, outline=dark, width=6)
        draw.ellipse((x+35,head_y-300,x+105,head_y-65), fill=fur, outline=dark, width=6)
        draw.ellipse((x-82,head_y-270,x-55,head_y-95), fill="#F4A9B8")
        draw.ellipse((x+55,head_y-270,x+82,head_y-95), fill="#F4A9B8")
    elif species in ("cat","fox","lion"):
        draw.polygon([(x-115,head_y-55),(x-95,head_y-190),(x-15,head_y-105)], fill=fur, outline=dark)
        draw.polygon([(x+15,head_y-105),(x+95,head_y-190),(x+115,head_y-55)], fill=fur, outline=dark)
        if species == "fox":
            draw.polygon([(x-110,head_y-75),(x-95,head_y-165),(x-48,head_y-110)], fill="#F4B5A0")
            draw.polygon([(x+48,head_y-110),(x+95,head_y-165),(x+110,head_y-75)], fill="#F4B5A0")
    elif species == "dog":
        draw.ellipse((x-155,head_y-90,x-85,head_y+55), fill="#A96E43", outline=dark, width=5)
        draw.ellipse((x+85,head_y-90,x+155,head_y+55), fill="#A96E43", outline=dark, width=5)
    elif species == "bear":
        draw.ellipse((x-145,head_y-145,x-55,head_y-55), fill=fur, outline=dark, width=5)
        draw.ellipse((x+55,head_y-145,x+145,head_y-55), fill=fur, outline=dark, width=5)
    elif species == "panda":
        draw.ellipse((x-120,head_y-95,x-35,head_y+5), fill=dark)
        draw.ellipse((x+35,head_y-95,x+120,head_y+5), fill=dark)
    elif species == "duck":
        draw.ellipse((x-150,head_y-85,x-80,head_y+25), fill=fur, outline=dark, width=4)
        draw.ellipse((x+80,head_y-85,x+150,head_y+25), fill=fur, outline=dark, width=4)
    # Eyes blink briefly; eye direction shifts with the scene.
    blink = (frame_no % 97) < 5
    eye_y = head_y-15
    for side in (-1,1):
        ex = x+side*52
        if blink:
            draw.line((ex-15,eye_y,ex+15,eye_y), fill=dark, width=7)
        else:
            draw.ellipse((ex-18,eye_y-23,ex+18,eye_y+24), fill="white", outline=dark, width=3)
            draw.ellipse((ex-7,eye_y-8,ex+8,eye_y+13), fill=dark)
            draw.ellipse((ex-3,eye_y-7,ex+2,eye_y-2), fill="white")
    # Muzzle and talking mouth.
    if species == "duck":
        draw.polygon([(x-35,head_y+35),(x+35,head_y+35),(x,head_y+75)], fill="#F28A35", outline=dark)
    else:
        draw.ellipse((x-55,head_y+25,x+55,head_y+105), fill=cream, outline=dark, width=3)
        draw.ellipse((x-13,head_y+38,x+13,head_y+58), fill=dark)
        mouth_open = int((math.sin(t*11+character_index)>0.15)*18)
        draw.ellipse((x-17,head_y+65,x+17,head_y+83+mouth_open), fill="#9D4050")
    # Name tag.
    tag_y = y+300
    draw.rounded_rectangle((x-100,tag_y,x+100,tag_y+48), radius=18, fill="#FFFFFF", outline=dark, width=3)
    f = font(26,True)
    box = draw.textbbox((0,0),name,font=f)
    draw.text((x-(box[2]-box[0])/2,tag_y+8),name,font=f,fill=dark)


def draw_story_prop(draw, story, scene, index, frame_no, t):
    bounce = int(math.sin(t*6)*12)
    ink = "#263047"
    title = str(story.get("title","")).lower()
    cue = str(scene.get("visual","")).lower()
    if "boss" in title:
        # Oversized royal hat, jungle-boss sign and simple clean-up props.
        if index == 0:
            draw.ellipse((190,690,445,745),fill="#6C3D91",outline=ink,width=8)
            draw.polygon([(220,700),(245,565),(390,565),(425,700)],fill="#8E5CC2",outline=ink)
            draw.ellipse((270,575,350,650),fill="#FFE16B",outline=ink,width=5)
            draw.text((286,590),"★",font=font(45,True),fill="#8E3A63")
        elif index == 1:
            draw.rounded_rectangle((390,610,690,760),radius=28,fill="#FFE16B",outline=ink,width=7)
            draw.text((435,650),"BOSS",font=font(58,True),fill=ink)
        elif index == 2:
            draw.rounded_rectangle((380,1120,700,1210),radius=24,fill="#8B583A",outline=ink,width=6)
            draw.text((430,1142),"JUNGLE PATH",font=font(30,True),fill="white")
        elif index in (3,4):
            draw.line((600,830,720,1100),fill="#8B583A",width=24)
            draw.polygon([(570,1080),(745,1080),(720,1170),(590,1170)],fill="#E9C46A",outline=ink)
            for j in range(7):
                xx=390+j*48
                yy=1160+int(math.sin(j+t*3)*18)
                draw.ellipse((xx-18,yy-10,xx+18,yy+10),fill="#D98A3A",outline=ink,width=2)
        else:
            draw.ellipse((580,650,840,715),fill="#6C3D91",outline=ink,width=7)
            draw.polygon([(615,665),(645,540),(790,540),(820,665)],fill="#8E5CC2",outline=ink)
            draw.text((655,570),"★",font=font(55,True),fill="#FFE16B")
    elif "dance" in title:
        # Dance-class props: music notes, floor markers and a colorful scarf.
        draw.rounded_rectangle((355,1120,725,1200),radius=30,fill="#F7D66B",outline=ink,width=7)
        for x in (430,535,640):
            draw.ellipse((x-20,1170+bounce,x+20,1210+bounce),fill="#F28A65",outline=ink,width=4)
        draw.arc((455,630,625,800),180,350,fill="#FFFFFF",width=13)
        draw.ellipse((570,635,610,675),fill="#FFFFFF")
        draw.line((610,655,610,770),fill="#FFFFFF",width=12)
        draw.arc((620,700,760,835),190,350,fill="#FFE16B",width=13)
        draw.text((470,850),"♪",font=font(110,True),fill="#FFE16B",stroke_width=3,stroke_fill=ink)
    elif "garden" in title:
        # Gardening props change as the seed grows across the story.
        draw.rounded_rectangle((370,1125,710,1240),radius=28,fill="#8B583A",outline=ink,width=7)
        if index >= 1:
            draw.line((700,700,640,1030),fill="#70C8F4",width=17)
            draw.arc((600,650,780,810),180,350,fill="#70C8F4",width=15)
        if index >= 3:
            draw.line((540,1140,540,920),fill="#348B4B",width=17)
            draw.ellipse((470,930,550,1000),fill="#57B96A",outline=ink,width=4)
            draw.ellipse((535,875,620,950),fill="#78D17A",outline=ink,width=4)
        if index >= 4:
            draw.ellipse((490,820,590,920),fill="#FFE16B",outline="#E59A3C",width=6)
            for a in range(8):
                angle=a*math.pi/4
                px=540+math.cos(angle)*75; py=870+math.sin(angle)*75
                draw.ellipse((px-25,py-25,px+25,py+25),fill="#F58FB1",outline=ink,width=3)
        else:
            draw.ellipse((515,1090,565,1140),fill="#D8A24D",outline=ink,width=4)
    else:
        if index == 0:
            draw.ellipse((385,1160,695,1235), fill="#FFFFFF", outline=ink, width=7)
            draw.ellipse((435,1140+bounce,645,1210+bounce), fill="#D99A52", outline="#8B542C", width=6)
            for x,y in [(490,1170),(545,1160),(590,1180)]:
                draw.ellipse((x-7,y-7+bounce,x+7,y+7+bounce), fill="#70452D")
        elif index == 1:
            draw.ellipse((455,650,620,815), fill="#BDEBFA", outline=ink, width=13)
            draw.line((590,790,690,900), fill="#8A5837", width=27)
            draw.ellipse((500,695,575,770), outline="white", width=6)
        elif index == 2:
            for j in range(8):
                x = 410+j*35
                y = 1110+int(math.sin(j*0.9+t*2)*38)
                r = 8+(j%3)*3
                draw.ellipse((x-r,y-r,x+r,y+r), fill="#B8783D")
        elif index == 3:
            draw.ellipse((520,650,560,690), fill="#B8783D", outline=ink, width=3)
            draw.line((540,610,540,570), fill="#FFE16B", width=8)
            draw.line((510,630,480,610), fill="#FFE16B", width=7)
            draw.line((570,630,600,610), fill="#FFE16B", width=7)
        elif index == 4:
            cx,cy=540,760
            pts=[]
            for j in range(20):
                a=j*math.pi/10
                r=125 if j%2==0 else 75
                pts.append((cx+math.cos(a)*r,cy+math.sin(a)*r))
            draw.polygon(pts, fill="#FFE16B", outline="#F28A35")
            draw.text((cx-47,cy-55),"AHA!",font=font(55,True),fill=ink,stroke_width=2,stroke_fill="white")
        else:
            for x in (455,585):
                draw.ellipse((x-65,1130+bounce,x+65,1215+bounce), fill="#D99A52", outline="#8B542C", width=6)
                for dx in (-25,15):
                    draw.ellipse((x+dx-6,1160+bounce,x+dx+6,1172+bounce), fill="#70452D")

def render_frame(story, scene, index, frame_no, path):
    t = frame_no / FPS
    im = Image.new("RGB",(W,H),"white")
    d = ImageDraw.Draw(im)
    draw_background(d,index,frame_no,t)
    # Branded title banner and scene progress.
    d.rounded_rectangle((38,38,W-38,225),radius=42,fill="#17243C",outline="#FFFFFF",width=5)
    d.text((78,62),"ANIMATED JUNGLE",font=font(62,True),fill="#FFE16B",stroke_width=1,stroke_fill="#17243C")
    title = str(story.get("title","A Funny Animal Story"))[:42]
    d.text((82,145),title,font=font(34,True),fill="white")
    d.rounded_rectangle((850,245,1035,310),radius=25,fill="#FFE16B",outline="#17243C",width=4)
    d.text((885,260),f"{index+1} / 6",font=font(32,True),fill="#17243C")
    # Action cue in a clean readable card.
    cue = wrap(d,str(scene.get("visual","A funny animal moment")),font(30,True),880)[:2]
    d.rounded_rectangle((55,265,805,390),radius=28,fill="#FFFFFF",outline="#17243C",width=4)
    for j,line in enumerate(cue):
        d.text((85,285+j*42),line,font=font(30,True),fill="#263047")
    # Character movement varies across the six story beats.
    drift = math.sin(t*2.5+index)*22
    chars = story["characters"]
    draw_character(d,315-drift,1010,chars[0]["species"],chars[0]["name"],frame_no,t,0)
    draw_character(d,765+drift,1010,chars[1]["species"],chars[1]["name"],frame_no,t,1)
    draw_story_prop(d,story,scene,index,frame_no,t)
    # Comic motion marks emphasize the action.
    for j in range(5):
        x = 180+j*180
        yy = 540 + int(18*math.sin(t*5+j))
        d.line((x,yy,x+22,yy-32),fill="#FFF7C7",width=8)
    # Large, high-contrast subtitles for sound-off viewing.
    narration = str(scene.get("narration","")).strip()
    lines = wrap(d,narration,font(39,True),900)[:3]
    panel_h = 80 + len(lines)*54
    panel_top = H-panel_h-55
    d.rounded_rectangle((45,panel_top,W-45,H-55),radius=35,fill="#17243C",outline="#FFE16B",width=6)
    d.text((82,panel_top+18),"STORY TIME",font=font(22,True),fill="#FFE16B")
    yy = panel_top+55
    for line in lines:
        box=d.textbbox((0,0),line,font=font(39,True))
        d.text(((W-(box[2]-box[0]))//2,yy),line,font=font(39,True),fill="white")
        yy+=52
    path.parent.mkdir(parents=True,exist_ok=True)
    im.save(path,quality=88,optimize=True)


async def speak(text, path):
    await edge_tts.Communicate(text=text, voice=VOICE, rate="+2%").save(str(path))


def render_video(story):
    for cmd in ("ffmpeg","ffprobe"):
        run([cmd,"-version"])
    WORK.mkdir(exist_ok=True); OUTPUT.mkdir(exist_ok=True)
    for p in WORK.iterdir():
        if p.is_file():
            p.unlink()
    segments=[]
    for i,scene in enumerate(story["scenes"]):
        frame_dir=WORK/f"scene_{i}_frames"
        if frame_dir.exists():
            for old in frame_dir.glob("*.jpg"):
                old.unlink()
        frame_dir.mkdir(parents=True,exist_ok=True)
        audio=WORK/f"voice_{i}.mp3"
        segment=WORK/f"segment_{i}.mp4"
        asyncio.run(speak(scene["narration"],audio))
        audio_seconds=float(run(["ffprobe","-v","error","-show_entries","format=duration",
                                 "-of","default=noprint_wrappers=1:nokey=1",str(audio)]))
        seconds=max(3.8,audio_seconds+0.45)
        frame_count=int(math.ceil(seconds*FPS))
        for frame_no in range(frame_count):
            render_frame(story,scene,i,frame_no,frame_dir/f"frame_{frame_no+1:04d}.jpg")
        run(["ffmpeg","-y","-framerate",str(FPS),"-start_number","1","-i",str(frame_dir/"frame_%04d.jpg"),
             "-i",str(audio),"-t",f"{seconds:.2f}","-vf","format=yuv420p",
             "-r",str(FPS),"-c:v","libx264","-preset","veryfast","-crf","22",
             "-c:a","aac","-b:a","128k","-shortest",str(segment)])
        segments.append(segment)
    concat=WORK/"concat.txt"
    concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in segments),encoding="utf-8")
    slug=re.sub(r"[^a-z0-9]+","-",story["title"].lower()).strip("-")[:30] or "animal-comedy"
    out=OUTPUT/f"funny-animals-{datetime.now(timezone.utc):%Y%m%d}-{slug}.mp4"
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),
         "-c:v","libx264","-preset","veryfast","-crf","22","-c:a","aac",
         "-b:a","128k","-movflags","+faststart",str(out)])
    info=json.loads(run(["ffprobe","-v","error","-show_entries","format=duration,size:stream=codec_type,codec_name,width,height",
                         "-of","json",str(out)]))
    v=next((s for s in info.get("streams",[]) if s.get("codec_type")=="video"),None)
    duration=float(info["format"]["duration"])
    if not v or (v.get("width"),v.get("height"))!=(W,H) or not 12<=duration<=180:
        raise RuntimeError("Final MP4 failed dimensions or duration validation.")
    log.info("Rendered animated video %s (%.1f seconds)",out,duration)
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


def upload_test():
    """Verify Cloudinary upload permission with a tiny temporary image; never contacts Buffer."""
    cloudinary.config(cloud_name=need("CLOUDINARY_CLOUD_NAME"),
                      api_key=need("CLOUDINARY_API_KEY"),
                      api_secret=need("CLOUDINARY_API_SECRET"),secure=True)
    image = Image.new("RGB", (16, 16), color=(40, 120, 80))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    public_id = f"upload-permission-test-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    result = cloudinary.uploader.upload(
        buffer, resource_type="image",
        folder=os.getenv("CLOUDINARY_FOLDER", "funny-animals-comedy") + "/connection-tests",
        public_id=public_id, overwrite=False, unique_filename=False, type="upload",
        tags=["temporary-upload-permission-test"])
    asset_id = result.get("public_id")
    if not asset_id or not result.get("secure_url"):
        raise RuntimeError("Cloudinary upload response did not include the expected asset details.")
    log.info("CLOUDINARY_UPLOAD_TEST_SUCCESS: upload/create permission is working.")
    log.info("Temporary test asset: %s", asset_id)
    try:
        cleanup = cloudinary.uploader.destroy(asset_id, resource_type="image", type="upload")
        if cleanup.get("result") == "ok":
            log.info("Temporary test asset cleaned up successfully.")
        else:
            log.warning("Test upload succeeded, but cleanup was not confirmed: %s", cleanup.get("result"))
    except Exception as exc:
        log.warning("Test upload succeeded, but temporary asset cleanup failed: %s", exc)
    log.info("No video was generated and Buffer was not contacted.")


def video_upload_test():
    """Upload and delete a tiny MP4 to verify Cloudinary video/create permission; never contacts Buffer."""
    cloudinary.config(cloud_name=need("CLOUDINARY_CLOUD_NAME"),
                      api_key=need("CLOUDINARY_API_KEY"),
                      api_secret=need("CLOUDINARY_API_SECRET"),secure=True)
    WORK.mkdir(exist_ok=True)
    test_video = WORK / f"cloudinary-video-permission-test-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.mp4"
    public_id = f"video-upload-permission-test-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    try:
        run(["ffmpeg", "-y", "-f", "lavfi", "-i",
             "color=c=blue:s=160x160:r=10:d=1", "-an",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             str(test_video)])
        result = cloudinary.uploader.upload(
            str(test_video), resource_type="video",
            folder=os.getenv("CLOUDINARY_FOLDER", "funny-animals-comedy") + "/connection-tests",
            public_id=public_id, overwrite=False, unique_filename=False, type="upload",
            tags=["temporary-video-upload-permission-test"])
        asset_id = result.get("public_id")
        if not asset_id or not result.get("secure_url"):
            raise RuntimeError("Cloudinary video upload response did not include the expected asset details.")
        log.info("CLOUDINARY_VIDEO_UPLOAD_TEST_SUCCESS: video upload/create permission is working.")
        log.info("Temporary test video asset: %s", asset_id)
        try:
            cleanup = cloudinary.uploader.destroy(asset_id, resource_type="video", type="upload")
            if cleanup.get("result") == "ok":
                log.info("Temporary test video cleaned up successfully.")
            else:
                log.warning("Video upload succeeded, but cleanup was not confirmed: %s", cleanup.get("result"))
        except Exception as exc:
            log.warning("Video upload succeeded, but temporary asset cleanup failed: %s", exc)
        log.info("No Buffer API call was made and no Facebook post was created.")
    finally:
        try:
            test_video.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Could not remove local temporary test video: %s", exc)


def queue_reel(video_url,caption,post_type="reel"):
    if post_type not in ("post", "reel"):
        raise RuntimeError("Unsupported Facebook post type.")
    channel=verify_channel()
    channel_id=need("BUFFER_CHANNEL_ID")
    mutation=f\'''mutation CreateFunnyAnimalsVideo {{
      createPost(input: {{
        text: {json.dumps(caption,ensure_ascii=False)}
        channelId: {json.dumps(channel_id)}
        schedulingType: automatic
        mode: addToQueue
        assets: [{{ video: {{ url: {json.dumps(video_url)} }} }}]
        metadata: {{ facebook: {{ type: {json.dumps(post_type)} }} }}
        aiAssisted: true
      }}) {{
        ... on PostActionSuccess {{ post {{ id status dueAt channelId }} }}
        ... on MutationError {{ message }}
      }}
    }}\'''
    result=buffer_api(mutation).get("createPost") or {}
    if result.get("message"): raise RuntimeError("Buffer rejected Facebook video post: "+result["message"])
    post=result.get("post")
    if not post or not post.get("id"): raise RuntimeError(f"Buffer did not confirm post creation: {result}")
    if post.get("channelId") and post["channelId"]!=channel_id:
        raise RuntimeError("SAFETY STOP: Buffer returned an unexpected destination.")
    log.info("Buffer accepted Facebook %s %s; status=%s dueAt=%s",post_type,post["id"],post.get("status"),post.get("dueAt"))
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
    parser.add_argument("--preview",action="store_true",
                        help="Generate a local animated preview only; does not upload or contact Buffer.")
    parser.add_argument("--upload-test",action="store_true",
                        help="Test Cloudinary image upload only; does not generate video or contact Buffer.")
    parser.add_argument("--video-upload-test",action="store_true",
                        help="Test Cloudinary video upload only; does not contact Buffer or publish.")
    args=parser.parse_args()
    if args.preview:
        # Preview the specifically selected Jungle Boss concept deterministically.
        story=boss_story()
        log.info("Preview story: %s",story["title"])
        video=render_video(story)
        log.info("PREVIEW_ONLY: video saved locally at %s; no Cloudinary upload or Buffer post.",video)
        return
    if args.video_upload_test:
        video_upload_test(); return
    if args.upload_test:
        upload_test(); return
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
    try:
        # Keep diagnostics available; normal publishing uses the long-form workflow.
        if any(flag in sys.argv[1:] for flag in ("--validate", "--upload-test", "--video-upload-test", "--preview")):
            main()
        else:
            from longform import run as run_longform
            run_longform()
    except Exception:
        log.exception("Automation failed safely.")
        sys.exit(1)
