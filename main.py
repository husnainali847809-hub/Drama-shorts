"""Free local animal video production; publishing is manual only."""
import argparse, os
from pathlib import Path
from animal_ai.pipeline import generate_pilot

def main():
    p=argparse.ArgumentParser(description="Free Animal Stories")
    p.add_argument("--generate",action="store_true")
    p.add_argument("--pilot",action="store_true")
    p.add_argument("--publish-approved",type=Path)
    p.add_argument("--caption",default="An original animal friendship story")
    a=p.parse_args()
    if a.generate and a.pilot:
        generate_pilot()
    elif a.publish_approved:
        if not a.publish_approved.is_file(): raise SystemExit("Approved MP4 path does not exist.")
        if os.getenv("PUBLISH_APPROVED")!="true": raise SystemExit("Safety stop: set PUBLISH_APPROVED=true only after watching and approving.")
        from main_publisher import publish_approved
        publish_approved(a.publish_approved,a.caption)
    else:
        print("No action taken. Run: python main.py --generate --pilot")
if __name__=="__main__": main()
