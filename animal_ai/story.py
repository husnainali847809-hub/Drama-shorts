"""Pilot episode: original animal story and shot prompts."""

STYLE = (
    "premium cinematic 3D family animation, original character design, "
    "high-end feature-animation quality, physically based fur, detailed expressive eyes, "
    "natural anatomy, beautiful global illumination, volumetric jungle light, "
    "cinematic depth of field, rich but natural color grading, vertical 9:16 composition"
)
NEGATIVE = (
    "low resolution, blurry, plastic toy look, flat lighting, deformed anatomy, "
    "extra limbs, duplicate characters, inconsistent fur pattern, text, watermark, logo"
)

CHARACTERS = {
    "timo": (
        "Timo, a small adorable orange-gold tiger cub with soft detailed fur, "
        "three distinctive dark stripes on each cheek, round amber eyes, tiny rounded ears, "
        "cream muzzle and chest, childlike proportions; keep this exact design"
    ),
    "bunny": (
        "Bunny, a tiny warm-white rabbit with soft detailed fur, long ears with pale pink "
        "inner ears, large gentle blue eyes, small pink nose; keep this exact design"
    ),
}

SCENES = [
    {
        "name": "lost_in_the_rain",
        "seconds": 10,
        "visual": "At twilight in a lush tropical jungle after gentle rain, Bunny stands alone beside a giant fern, looking frightened as distant thunder rolls. Slow cinematic camera push-in.",
        "en": "Deep in the jungle, a tiny rabbit had lost his way.",
        "ur": "Gehre jungle mein ek nanha khargosh apna raasta bhool gaya tha.",
        "motion": "The rabbit's ears tremble slightly, raindrops fall from leaves, subtle breathing, slow camera push-in. Preserve face and body design.",
    },
    {
        "name": "timo_hears_a_sound",
        "seconds": 10,
        "visual": "Timo the tiger cub pauses on a mossy jungle trail and turns toward a faint frightened sound coming from behind the ferns. Low-angle cinematic shot.",
        "en": "Nearby, Timo heard a tiny voice calling for help.",
        "ur": "Qareeb hi Timo ne madad ke liye ek halki si awaaz suni.",
        "motion": "The tiger cub gently turns his head and ears toward the sound, takes one careful step, leaves sway in a breeze, smooth tracking camera.",
    },
    {
        "name": "first_meeting",
        "seconds": 10,
        "visual": "Timo carefully parts the broad fern leaves and discovers Bunny. The tiny rabbit looks up with hopeful eyes. Both original characters visible, warm cinematic medium shot.",
        "en": "He found Bunny, who was scared and all alone.",
        "ur": "Usay Bunny mila, jo dara hua aur bilkul akela tha.",
        "motion": "Tiger lowers his head kindly, rabbit looks up and relaxes a little, natural blinking and breathing, gentle dolly movement. Keep both character designs exact.",
    },
    {
        "name": "the_river",
        "seconds": 10,
        "visual": "The two friends reach a shallow jungle stream swollen by rain. Bunny hesitates at the slippery stones while Timo studies a safe crossing. Cinematic wide shot.",
        "en": "But the way home was blocked by a rushing stream.",
        "ur": "Lekin ghar ka raasta tez behte paani ne rok diya tha.",
        "motion": "Water flows naturally around stones, tiger looks across the stream, rabbit takes a hesitant half-step, camera pans slowly.",
    },
    {
        "name": "a_brave_plan",
        "seconds": 10,
        "visual": "Timo finds a sturdy fallen branch and carefully pushes it across two rocks to make a small safe bridge for Bunny. Detailed close-up, cinematic lighting.",
        "en": "Timo made a little bridge and showed Bunny where to step.",
        "ur": "Timo ne ek chhota pul banaya aur Bunny ko sambhal kar chalna sikhaya.",
        "motion": "Tiger gently nudges the branch into place, leaves flutter, rabbit watches with growing confidence, smooth close-up camera move.",
    },
    {
        "name": "safe_together",
        "seconds": 10,
        "visual": "Bunny carefully crosses the branch bridge and reaches Timo on the other side. They share a relieved happy look beneath glowing fireflies. Emotional cinematic shot.",
        "en": "Step by step, Bunny crossed safely to the other side.",
        "ur": "Aahista aahista Bunny mehfooz doosri taraf pohanch gaya.",
        "motion": "Rabbit takes careful small steps, tiger remains still and encouraging, fireflies drift gently, camera tracks with the rabbit. No sudden movement.",
    },
    {
        "name": "friendship_ending",
        "seconds": 10,
        "visual": "Under a golden sunrise in a peaceful jungle clearing, Bunny and Timo walk side by side toward home, smiling. A beautiful cinematic wide shot with warm rim light.",
        "en": "That day, a brave tiger and a little rabbit became friends.",
        "ur": "Us din ek bahadur tiger aur nanha khargosh dost ban gaye.",
        "motion": "Both friends walk slowly side by side, tails and ears move naturally, warm sunrise rays, gentle crane-back ending shot.",
    },
]

TITLE = "Timo & Bunny: A Little Bridge of Friendship"
CAPTION = (
    "A little kindness can turn a frightening day into a beautiful friendship. "
    "Meet Timo and Bunny in this original animated jungle story. 🐯🐰"
)
