# kaiagotchi/ui/faces.py

# Core Faces
NEUTRAL = "(◕‿‿◕)"
HAPPY = "(•‿‿•)"
CURIOUS = "(◉_◉)"
BORED = "(¬_¬)"
SAD = "(╥☁╥ )"
FRUSTRATED = "(ಠ_ಠ)"
SLEEPY = "(≖‿‿≖)"
CONFIDENT = "(⌐■_■)"
BROKEN = "(☓‿‿☓)"
ANGRY = "(-_-')"
AWAKE = "(•_•)"
DEBUG = "(#_#)"

# Position metadata
PNG = False
POSITION_X = 0
POSITION_Y = 40

_FACE_MAP = {
    "neutral": NEUTRAL,
    "calm": NEUTRAL,
    "happy": HAPPY,
    "curious": CURIOUS,
    "bored": BORED,
    "sad": SAD,
    "frustrated": FRUSTRATED,
    "sleepy": SLEEPY,
    "confident": CONFIDENT,
    "broken": BROKEN,
    "angry": ANGRY,
    "debug": DEBUG,
}

def get_face(mood: str) -> str:
    if not mood:
        return NEUTRAL
    key = str(mood).strip().lower()
    return _FACE_MAP.get(key, NEUTRAL)

class Faces:
    """Legacy export for static access."""
    NEUTRAL = NEUTRAL
    HAPPY = HAPPY
    CURIOUS = CURIOUS
    BORED = BORED
    SAD = SAD
    FRUSTRATED = FRUSTRATED
    SLEEPY = SLEEPY
    CONFIDENT = CONFIDENT
    BROKEN = BROKEN
    ANGRY = ANGRY
    DEBUG = DEBUG
