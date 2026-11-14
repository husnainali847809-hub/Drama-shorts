#!/usr/bin/env python3
"""Create a standalone, original 2D animated-drama demo. No source footage or publishing integrations."""
from PIL import Image, ImageDraw, ImageFont
import math, os, subprocess, tempfile

W, H, FPS, SECONDS = 720, 1280, 24, 18
OUT = "animated_drama_demo.mp4"
os.makedirs("demo_output", exist_ok=True)
OUT = "demo_output/animated_drama_demo.mp4"

def font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def rounded(draw, xy, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

def character(draw, x, y, outfit, skin, hair, facing, talking=False, bob=0):
    # Original, deliberately stylized fictional adult character.
    y += bob
    draw.ellipse((x-92, y+270, x+92, y+300), fill=(20, 24, 38, 90))
    rounded(draw, (x-76, y+125, x+76, y+285), 42, outfit)
    # neck and head
    rounded(draw, (x-22, y+95, x+22, y+150), 12, skin)
    draw.ellipse((x-66, y-5, x+66, y+130), fill=skin)
    # hair
    if facing == "right":
        draw.pieslice((x-70, y-18, x+70, y+100), 180, 355, fill=hair)
    else:
        draw.pieslice((x-70, y-18, x+70, y+100), 185, 360, fill=hair)
    eye_x = x + (22 if facing == "right" else -22)
    draw.ellipse((eye_x-6, y+55, eye_x+6, y+68), fill=(35, 30, 30))
    # nose and mouth
    draw.arc((x-16, y+68, x+18, y+100), 5, 170, fill=(110, 55, 55), width=3)
    if talking:
        draw.ellipse((x-12, y+88, x+12, y+105), fill=(90, 35, 45))
    else:
        draw.arc((x-15, y+82, x+15, y+103), 5, 170, fill=(90, 35, 45), width=3)
    # simple garment details
    draw.line((x, y+150, x, y+275), fill=(235, 225, 210), width=3)
    draw.line((x-45, y+180, x+45, y+180), fill=(235, 225, 210), width=2)

def draw_frame(t, frame):
    im = Image.new("RGB", (W, H), (18, 27, 48))
    d = ImageDraw.Draw(im, "RGBA")
    # dusk window and room
    d.rectangle((0, 0, W, 760), fill=(29, 43, 70))
    d.rectangle((45, 100, 310, 570), fill=(53, 87, 125))
    d.rectangle((60, 115, 295, 555), fill=(84, 127, 164))
    d.line((177, 115, 177, 555), fill=(225, 218, 195), width=10)
    d.line((60, 330, 295, 330), fill=(225, 218, 195), width=10)
    d.ellipse((220, 155, 275, 210), fill=(246, 218, 153))
    d.rectangle((0, 760, W, H), fill=(69, 52, 52))
    # wall art and sofa
    rounded(d, (420, 145, 650, 390), 12, (45, 54, 74), (196, 174, 142), 6)
    d.ellipse((485, 205, 585, 305), fill=(202, 143, 103))
    rounded(d, (65, 820, 655, 1120), 55, (83, 77, 91))
    rounded(d, (95, 790, 625, 990), 45, (111, 93, 104))
    # two original fictional adult characters
    bob1 = int(4*math.sin(t*2))
    bob2 = int(4*math.sin(t*2+1.2))
    character(d, 245, 500, (27, 133, 133), (190, 128, 94), (43, 31, 28), "right", talking=(5.0 < t < 9.0), bob=bob1)
    character(d, 510, 500, (42, 58, 93), (205, 145, 108), (31, 26, 26), "left", talking=(11.0 < t < 15.0), bob=bob2)
    # gentle cinematic panel
    d.rectangle((0, 0, W, 105), fill=(5, 10, 20, 180))
    d.text((38, 34), "AN ORIGINAL ANIMATED STORY", font=font(28, True), fill=(255, 220, 125))
    # dialogue captions
    if t < 5:
        caption = "A difficult truth was about to come out..."
    elif t < 10:
        caption = "Ayesha: Why did you hide the truth from me?"
    elif t < 16:
        caption = "Hamza: I didn't want to hurt you."
    else:
        caption = "Some truths change everything."
    rounded(d, (34, 1135, 686, 1235), 22, (5, 9, 18, 220))
    # wrap text
    words, lines, line = caption.split(), [], ""
    for word in words:
        test = (line + " " + word).strip()
        if d.textbbox((0,0), test, font=font(25, True))[2] > 600:
            lines.append(line); line = word
        else:
            line = test
    if line: lines.append(line)
    for i, txt in enumerate(lines[:2]):
        d.text((60, 1153+i*35), txt, font=font(25, True), fill=(255,255,255))
    return im.convert("RGB")

def main():
    ffmpeg = "/usr/bin/ffmpeg"
    if not os.path.exists(ffmpeg):
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as td:
        pattern = os.path.join(td, "frame_%05d.png")
        for i in range(FPS*SECONDS):
            frame = draw_frame(i/FPS, i)
            frame.save(pattern % i)
        subprocess.run([ffmpeg, "-y", "-framerate", str(FPS), "-i",
                        os.path.join(td, "frame_%05d.png"), "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    print(f"Created original animated demo: {OUT}")
    print("Duration: 18 seconds | Format: 720x1280 MP4 | Publishing: disabled")

if __name__ == "__main__":
    main()
