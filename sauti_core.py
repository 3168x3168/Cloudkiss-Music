"""Cloudkiss Music core logic: scanning, tags, the play queue and the playback controller.

No Kivy or Android imports here, so everything in this file can be tested on any machine.
The same Controller runs inside the Android background service and, on a PC, inside the app.
"""
import json
import math
import os
import random
import re
import time

AUDIO_EXT = ('.mp3', '.m4a', '.aac', '.wav', '.ogg', '.opus', '.flac')

# The app screen and the background service talk over localhost (OSC/UDP).
SERVICE_PORT = 3100   # service listens here (commands from the screen)
APP_PORT = 3101       # screen listens here (state pushed by the service)


# ---------------------------------------------------------------- files

def music_roots():
    """Folders to scan. SAUTI_MUSIC_DIR overrides (handy for testing on a PC)."""
    env = os.environ.get('SAUTI_MUSIC_DIR')
    if env:
        return [p for p in env.split(os.pathsep) if p]
    if os.path.isdir('/storage/emulated/0'):  # Android shared storage
        base = '/storage/emulated/0'
        return [os.path.join(base, d) for d in ('Music', 'Download', 'Documents')]
    return [os.path.expanduser('~/Music')]


def find_audio(roots, limit=5000):
    """Walk the folders and return a sorted list of audio file paths."""
    found = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            for name in filenames:
                if name.startswith('.') or not name.lower().endswith(AUDIO_EXT):
                    continue
                found.add(os.path.join(dirpath, name))
                if len(found) >= limit:
                    return sorted(found)
    return sorted(found)


def parse_name(path):
    """'03 - Artist - Song_Name.mp3' -> ('Song Name', 'Artist')."""
    base = os.path.splitext(os.path.basename(path))[0].replace('_', ' ')
    base = re.sub(r'^\d+[\s.\-)]+', '', base).strip()
    if ' - ' in base:
        artist, title = base.split(' - ', 1)
        return (title.strip() or base), artist.strip()
    return (base or os.path.basename(path)), ''


def read_tags(path):
    """Title, artist and length from the file's tags; falls back to the file name."""
    title, artist = parse_name(path)
    dur = 0.0
    try:
        import mutagen  # pure Python, ships fine inside the APK
        f = mutagen.File(path, easy=True)
        if f is not None:
            length = getattr(f.info, 'length', None)
            if length:
                dur = float(length)
            tags = f.tags or {}
            t = (tags.get('title') or [''])[0]
            a = (tags.get('artist') or [''])[0]
            title = t or title
            artist = a or artist
    except Exception:
        pass
    return {'path': path, 'title': title, 'artist': artist, 'dur': dur}


def fmt_time(seconds):
    if not seconds or not math.isfinite(seconds) or seconds <= 0:
        return '0:00'
    m, s = divmod(int(seconds), 60)
    return '%d:%02d' % (m, s)


# ---------------------------------------------------------------- shared library file
# The screen writes the song list here; the background service reads it, so the
# notification buttons (next / previous) still work after the app is closed.

def data_dir():
    d = (os.environ.get('SAUTI_DATA_DIR') or os.environ.get('ANDROID_PRIVATE')
         or os.path.expanduser('~/.cloudkiss-music'))
    os.makedirs(d, exist_ok=True)
    return d


def library_file():
    return os.path.join(data_dir(), 'library.json')


def save_library(items):
    tmp = library_file() + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(items, f)
    os.replace(tmp, library_file())


def load_library():
    try:
        with open(library_file(), encoding='utf-8') as f:
            items = json.load(f)
        return [d for d in items if isinstance(d, dict) and os.path.exists(d.get('path', ''))]
    except Exception:
        return []


# ---------------------------------------------------------------- queue

class PlayQueue:
    """Decides what plays next. repeat: 0 = off, 1 = all, 2 = one."""

    def __init__(self):
        self.paths = []
        self.order = []
        self.pos = -1
        self.shuffle = False
        self.repeat = 0

    def set_library(self, paths):
        cur = self.current()
        self.paths = list(paths)
        self.rebuild(cur)

    def rebuild(self, current=None):
        self.order = list(self.paths)
        if self.shuffle:
            random.shuffle(self.order)
            if current in self.order:
                self.order.remove(current)
                self.order.insert(0, current)
        self.pos = self.order.index(current) if current in self.order else -1

    def current(self):
        return self.order[self.pos] if 0 <= self.pos < len(self.order) else None

    def select(self, path):
        if path in self.order:
            self.pos = self.order.index(path)

    def set_shuffle(self, on):
        self.shuffle = bool(on)
        self.rebuild(self.current())

    def next(self, auto=False):
        """auto=True means the song ended by itself (respects repeat off/one)."""
        if not self.order:
            return None
        if auto and self.repeat == 2:
            return self.current()
        p = self.pos + 1
        if p >= len(self.order):
            if auto and self.repeat == 0:
                return None
            p = 0
        self.pos = p
        return self.order[p]

    def prev(self):
        if not self.order:
            return None
        p = self.pos - 1
        if p < 0:
            p = len(self.order) - 1
        self.pos = p
        return self.order[p]


# ---------------------------------------------------------------- controller

class Controller:
    """Playback brain. An 'engine' does the actual audio; it must provide:

        load_and_play(path) -> bool, pause(), resume(), seek(seconds),
        position() -> seconds, duration() -> seconds, is_playing() -> bool, release()
    """

    def __init__(self, engine):
        self.engine = engine
        self.queue = PlayQueue()
        self.library = {}
        self.path = None
        self.playing = False
        self.error = ''
        self.started_at = 0.0
        self.sleep_at = 0.0

    def set_library(self, items):
        self.library = {d['path']: d for d in items}
        self.queue.set_library([d['path'] for d in items])

    def item(self, path=None):
        return self.library.get(path or self.path)

    def _start(self, path):
        self.error = ''
        if not self.engine.load_and_play(path):
            self.path = None
            self.playing = False
            self.error = "Can't play this file"
            return False
        self.path = path
        self.playing = True
        self.started_at = time.time()
        return True

    def play_path(self, path):
        self.queue.select(path)
        return self._start(path)

    def toggle(self):
        if self.path is None:
            path = self.queue.current() or (self.queue.order[0] if self.queue.order else None)
            if path:
                self.queue.select(path)
                self._start(path)
        elif self.playing:
            self.engine.pause()
            self.playing = False
        else:
            self.engine.resume()
            self.playing = True
            self.started_at = time.time()

    def next(self):
        path = self.queue.next(auto=False)
        if path:
            self._start(path)

    def prev(self):
        if self.path and self.playing and self.engine.position() > 3:
            self.engine.seek(0)   # like most players: restart the song first
            return
        path = self.queue.prev()
        if path:
            self._start(path)

    def seek_fraction(self, fraction):
        dur = self.engine.duration() if self.path else 0
        if dur > 0:
            self.engine.seek(max(0.0, min(1.0, fraction)) * dur)

    def set_shuffle(self, on):
        self.queue.set_shuffle(on)

    def set_repeat(self, n):
        self.queue.repeat = int(n) % 3

    def set_sleep(self, minutes):
        self.sleep_at = time.time() + minutes * 60 if minutes else 0.0

    def tick(self):
        """Call about twice a second: sleep timer and 'song finished' detection."""
        now = time.time()
        if self.sleep_at and now >= self.sleep_at:
            self.sleep_at = 0.0
            if self.playing:
                self.engine.pause()
                self.playing = False
        if self.playing and now - self.started_at > 1.0 and not self.engine.is_playing():
            nxt = self.queue.next(auto=True)
            if nxt:
                self._start(nxt)
            else:
                self.engine.release()
                self.playing = False
                self.path = None

    def state(self):
        have = self.path is not None
        now = time.time()
        return {
            'path': self.path or '',
            'playing': bool(self.playing),
            'pos': float(self.engine.position()) if have else 0.0,
            'dur': float(self.engine.duration()) if have else 0.0,
            'shuffle': bool(self.queue.shuffle),
            'repeat': int(self.queue.repeat),
            'error': self.error,
            'sleep_left': max(0, int(self.sleep_at - now)) if self.sleep_at else 0,
            'nlib': len(self.library),
        }
