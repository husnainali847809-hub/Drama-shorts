"""Free local Blender + Edge TTS + FFmpeg pipeline; no paid API and no auto-publishing."""
import asyncio, json, os, shutil, subprocess
from pathlib import Path
import edge_tts
from animal_ai.story import SCENES, TITLE, CAPTION
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"output"/"animal_pilot"
OUT.mkdir(parents=True,exist_ok=True)
SCRIPT=ROOT/"scripts"/"blender_pilot.py"

def run(cmd,timeout=21600):
    print("Running:", " ".join(map(str,cmd)),flush=True)
    subprocess.run(list(map(str,cmd)),check=True,timeout=timeout)

def find_blender():
    exe=os.getenv("BLENDER_EXE")
    if exe and Path(exe).is_file(): return exe
    exe=shutil.which("blender")
    if exe: return exe
    raise RuntimeError("Blender not found. Install Blender and add it to PATH, or set BLENDER_EXE to the full blender.exe path.")

async def create_voice():
    chunks=[]
    for i,s in enumerate(SCENES,1):
        for lang,line in (("en",s["en"]),("ur",s["ur"])):
            voice=os.getenv("TTS_EN_VOICE" if lang=="en" else "TTS_UR_VOICE",
                "en-US-GuyNeural" if lang=="en" else "ur-PK-AsadNeural")
            f=OUT/f"voice_{i:02d}_{lang}.mp3"
            await edge_tts.Communicate(line,voice).save(str(f))
            chunks.append(f)
    listing=OUT/"voice_concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in chunks),encoding="utf-8")
    target=OUT/"bilingual_voice.mp3"
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",listing,"-c:a","libmp3lame","-q:a","3",target])
    return target

def generate_pilot():
    blender=find_blender()
    clips=[]
    for i,s in enumerate(SCENES,1):
        clip=OUT/f"scene_{i:02d}.mp4"
        run([blender,"-b","--threads",os.getenv("BLENDER_THREADS","2"),"--python",SCRIPT,"--","--scene-index",i,"--seconds",s["seconds"],"--output",clip])
        if not clip.is_file() or clip.stat().st_size<10000: raise RuntimeError(f"Blender did not create scene {i}.")
        clips.append(clip)
    listing=OUT/"video_concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in clips),encoding="utf-8")
    silent=OUT/"joined_silent.mp4"
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",listing,"-c:v","libx264","-preset","ultrafast","-crf","24","-pix_fmt","yuv420p","-movflags","+faststart",silent])
    voice=asyncio.run(create_voice())
    final=OUT/"PILOT_Timo_and_Bunny_REVIEW_ONLY.mp4"
    total=sum(s["seconds"] for s in SCENES)
    run(["ffmpeg","-y","-i",silent,"-i",voice,"-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac","-b:a","128k","-af","apad","-t",total,"-movflags","+faststart",final])
    probe=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration:stream=width,height","-of","json",final],capture_output=True,text=True,check=True)
    data=json.loads(probe.stdout); duration=float(data["format"]["duration"])
    video=next(x for x in data["streams"] if x.get("width"))
    if not 60<=duration<=90: raise RuntimeError(f"Duration {duration:.1f}s outside 60–90s.")
    if (video["width"],video["height"])!=(720,1280): raise RuntimeError("Output resolution is not 720x1280.")
    (OUT/"review_metadata.json").write_text(json.dumps({"title":TITLE,"caption":CAPTION,"duration_seconds":round(duration,2),"resolution":"720x1280","fps":24,"status":"REVIEW_REQUIRED_NOT_PUBLISHED","generation":"local_blender_procedural_3d","scenes":[s["name"] for s in SCENES]},indent=2),encoding="utf-8")
    print(f"REVIEW FILE: {final}\nNOT PUBLISHED. Watch and approve manually.")
    return final
