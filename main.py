"""Cloudkiss Music: a simple offline music player for Android, written in Python (Kivy).

On Android the audio lives in a background service (service/playback.py), so music keeps
playing with the screen off and has notification buttons. On a PC the same playback logic
runs inside the app instead, which makes it easy to try.
"""
import math
import os
import threading
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import BooleanProperty, StringProperty
from kivy.resources import resource_add_path
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform

from sauti_core import (APP_PORT, SERVICE_PORT, Controller, find_audio, fmt_time,
                        load_library, music_roots, read_tags, save_library)

DEFAULT_STATE = {'path': '', 'playing': False, 'pos': 0.0, 'dur': 0.0, 'shuffle': False,
                 'repeat': 0, 'error': '', 'sleep_left': 0, 'nlib': 0}

KV = '''
#:import dp kivy.metrics.dp

<FlatButton@Button>:
    background_normal: ''
    background_down: ''
    background_color: 0.14, 0.19, 0.17, 0.9
    color: 0.91, 0.945, 0.93, 1
    font_size: '14sp'

<AccentButton@FlatButton>:
    background_color: 0.95, 0.72, 0.29, 1
    color: 0.11, 0.08, 0.02, 1
    bold: True

<SongRow>:
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(60)
    padding: dp(14), dp(6)
    spacing: dp(10)
    canvas.before:
        Color:
            rgba: (0.086, 0.114, 0.102, 0.85) if root.active else (0, 0, 0, 0)
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        Label:
            text: root.title
            bold: True
            halign: 'left'
            valign: 'middle'
            text_size: self.size
            shorten: True
            shorten_from: 'right'
            color: (0.95, 0.72, 0.29, 1) if root.active else (0.95, 0.97, 0.96, 1)
        Label:
            text: root.artist
            font_size: '13sp'
            halign: 'left'
            valign: 'middle'
            text_size: self.size
            shorten: True
            shorten_from: 'right'
            color: 0.78, 0.85, 0.82, 1
    Label:
        text: root.dur_text
        font_size: '13sp'
        size_hint_x: None
        width: dp(48)
        color: 0.78, 0.85, 0.82, 1

FloatLayout:
    Image:
        source: 'wallpaper.jpg'
        fit_mode: 'cover'
        pos_hint: {'x': 0, 'y': 0}
    Widget:
        pos_hint: {'x': 0, 'y': 0}
        canvas:
            Color:
                rgba: 0.04, 0.06, 0.055, 0.55
            Rectangle:
                pos: self.pos
                size: self.size

    BoxLayout:
        orientation: 'vertical'
        pos_hint: {'x': 0, 'y': 0}

        BoxLayout:
            size_hint_y: None
            height: dp(56)
            padding: dp(16), dp(8)
            spacing: dp(8)
            Label:
                text: 'Cloudkiss Music'
                bold: True
                font_size: '22sp'
                halign: 'left'
                valign: 'middle'
                text_size: self.size
            FlatButton:
                text: 'Rescan'
                size_hint_x: None
                width: dp(90)
                on_release: app.scan()

        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(16), dp(4)
            TextInput:
                id: search
                hint_text: 'Search your songs'
                multiline: False
                write_tab: False
                padding: dp(12), dp(12)
                background_normal: ''
                background_active: ''
                background_color: 0.086, 0.114, 0.102, 0.85
                foreground_color: 0.91, 0.945, 0.93, 1
                hint_text_color: 0.7, 0.78, 0.74, 1
                cursor_color: 0.25, 0.82, 0.63, 1
                on_text: app.refresh_rows()

        Label:
            id: status
            size_hint_y: None
            height: dp(24)
            font_size: '12sp'
            color: 0.85, 0.9, 0.88, 1

        RecycleView:
            id: rv
            viewclass: 'SongRow'
            bar_width: dp(3)
            RecycleBoxLayout:
                default_size: None, dp(60)
                default_size_hint: 1, None
                size_hint_y: None
                height: self.minimum_height
                orientation: 'vertical'

        BoxLayout:
            orientation: 'vertical'
            size_hint_y: None
            height: dp(200)
            padding: dp(14)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0.086, 0.114, 0.102, 0.92
                Rectangle:
                    pos: self.pos
                    size: self.size
            Label:
                id: now_title
                text: 'Nothing playing'
                bold: True
                font_size: '17sp'
                halign: 'left'
                valign: 'middle'
                text_size: self.size
                shorten: True
                shorten_from: 'right'
                size_hint_y: None
                height: dp(26)
            Label:
                id: now_artist
                text: 'Pick a song to start'
                font_size: '13sp'
                halign: 'left'
                valign: 'middle'
                text_size: self.size
                color: 0.7, 0.78, 0.74, 1
                size_hint_y: None
                height: dp(20)
            BoxLayout:
                size_hint_y: None
                height: dp(34)
                spacing: dp(8)
                Label:
                    id: t_cur
                    text: '0:00'
                    font_size: '12sp'
                    size_hint_x: None
                    width: dp(40)
                    color: 0.7, 0.78, 0.74, 1
                Slider:
                    id: seek
                    min: 0
                    max: 1
                    value: 0
                    cursor_size: dp(20), dp(20)
                Label:
                    id: t_dur
                    text: '0:00'
                    font_size: '12sp'
                    size_hint_x: None
                    width: dp(40)
                    color: 0.7, 0.78, 0.74, 1
            BoxLayout:
                size_hint_y: None
                height: dp(52)
                spacing: dp(8)
                FlatButton:
                    id: btn_shuf
                    text: 'Shuffle'
                    on_release: app.toggle_shuffle()
                FlatButton:
                    text: 'Prev'
                    on_release: app.backend.prev()
                AccentButton:
                    id: btn_play
                    text: 'Play'
                    on_release: app.backend.toggle()
                FlatButton:
                    text: 'Next'
                    on_release: app.backend.next()
                FlatButton:
                    id: btn_rep
                    text: 'Repeat: off'
                    on_release: app.cycle_repeat()
            FlatButton:
                id: btn_sleep
                text: 'Sleep timer: off'
                size_hint_y: None
                height: dp(36)
                on_release: app.cycle_sleep()
'''


class SongRow(ButtonBehavior, BoxLayout):
    title = StringProperty('')
    artist = StringProperty('')
    dur_text = StringProperty('')
    path = StringProperty('')
    active = BooleanProperty(False)

    def on_release(self):
        App.get_running_app().backend.play(self.path)


# ====================================================================== backends
# The screen only talks to a "backend". On Android that is the background service;
# on a PC it is a Controller running inside the app.

class KivyEngine:
    """Audio engine for PC testing, using Kivy's own sound player."""

    def __init__(self):
        self.snd = None
        self.paused_at = None

    def load_and_play(self, path):
        from kivy.core.audio import SoundLoader
        self.release()
        snd = SoundLoader.load(path)
        if snd is None:
            return False
        snd.play()
        self.snd = snd
        return True

    def pause(self):          # Kivy sounds have no pause: remember the spot and stop
        if self.snd:
            self.paused_at = self.snd.get_pos() or 0.0
            self.snd.stop()

    def resume(self):
        if self.snd:
            self.snd.play()
            if self.paused_at:
                self.snd.seek(self.paused_at)
            self.paused_at = None

    def seek(self, seconds):
        if self.snd:
            if self.paused_at is not None:
                self.paused_at = seconds
            else:
                self.snd.seek(seconds)

    def position(self):
        if not self.snd:
            return 0.0
        return self.paused_at if self.paused_at is not None else (self.snd.get_pos() or 0.0)

    def duration(self):
        return max(0.0, self.snd.length or 0.0) if self.snd else 0.0

    def is_playing(self):
        return bool(self.snd) and self.snd.state == 'play'

    def release(self):
        if self.snd:
            try:
                self.snd.stop()
                self.snd.unload()
            except Exception:
                pass
        self.snd = None
        self.paused_at = None


class LocalBackend:
    def __init__(self, on_state):
        self.on_state = on_state
        self.ctl = Controller(KivyEngine())

    def start(self):
        Clock.schedule_interval(self._tick, 0.5)

    def _tick(self, dt):
        self.ctl.tick()
        self._push()

    def _push(self):
        self.on_state(self.ctl.state())

    def set_library(self, items):
        save_library(items)
        self.ctl.set_library(items)
        self._push()

    def play(self, path):
        self.ctl.play_path(path)
        self._push()

    def toggle(self):
        self.ctl.toggle()
        self._push()

    def next(self):
        self.ctl.next()
        self._push()

    def prev(self):
        self.ctl.prev()
        self._push()

    def seek(self, fraction):
        self.ctl.seek_fraction(fraction)

    def set_shuffle(self, on):
        self.ctl.set_shuffle(on)
        self._push()

    def set_repeat(self, n):
        self.ctl.set_repeat(n)
        self._push()

    def set_sleep(self, minutes):
        self.ctl.set_sleep(minutes)
        self._push()


class ServiceBackend:
    """Android: sends commands to the playback service and shows the state it pushes back."""

    def __init__(self, on_state):
        self.on_state = on_state
        self.state = dict(DEFAULT_STATE)
        self.ready = False        # have we heard from the service?
        self.started = False      # did we ask Android to start it?
        self.pending = []         # commands waiting for the service to come up
        self.opts = {'shuffle': 0, 'repeat': 0}
        self.n_library = 0
        self.last_seen = 0.0
        self._lib_sent = 0.0
        self.client = None
        self.server = None

    def start(self):
        from oscpy.client import OSCClient
        from oscpy.server import OSCThreadServer
        self.client = OSCClient('127.0.0.1', SERVICE_PORT, encoding='utf8')
        self.server = OSCThreadServer(encoding='utf8')
        self.server.listen(address='127.0.0.1', port=APP_PORT, default=True)
        self.server.bind(b'/state', self._on_osc)
        Clock.schedule_interval(self._watch, 1.0)
        self._raw(b'/hello')      # is the service already running from before?

    # -- plumbing
    def _raw(self, addr, *args):
        try:
            self.client.send_message(addr, list(args) or [1])
        except Exception as e:
            print('[cloudkiss] osc send failed:', e)

    def _cmd(self, addr, *args):
        if self.ready:
            self._raw(addr, *args)
            return
        if addr == b'/play':
            self.pending = [p for p in self.pending if p[0] != b'/play']
        self.pending.append((addr, args))
        if not self.started:
            self._start_service()

    def _start_service(self):
        self.started = True
        try:
            from jnius import autoclass
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            cls = autoclass(activity.getPackageName() + '.ServicePlayback')
            try:
                cls.start(activity, '')
            except Exception:
                cls.start(activity, 'icon', 'Cloudkiss Music', 'Starting...', '')
        except Exception as e:
            print('[cloudkiss] could not start playback service:', e)
            self.started = False
            self.pending = []
            self.state['error'] = 'Could not start the playback service'
            self.on_state(self.state)

    def _on_osc(self, *args):       # runs on the OSC thread
        vals = args[0] if len(args) == 1 and isinstance(args[0], (list, tuple)) else args
        try:
            st = {'path': vals[0], 'playing': bool(vals[1]), 'pos': float(vals[2]),
                  'dur': float(vals[3]), 'shuffle': bool(vals[4]), 'repeat': int(vals[5]),
                  'error': vals[6], 'sleep_left': int(vals[7]), 'nlib': int(vals[8])}
        except Exception:
            return
        Clock.schedule_once(lambda dt: self._apply(st))

    def _apply(self, st):
        self.last_seen = time.time()
        first = not self.ready
        self.ready = True
        if self.n_library and st['nlib'] != self.n_library and time.time() - self._lib_sent > 3:
            self._lib_sent = time.time()
            self._raw(b'/lib')
        if first:
            if self.started:    # we launched it: push our options, then run queued commands
                self._raw(b'/shuffle', self.opts['shuffle'])
                self._raw(b'/repeat', self.opts['repeat'])
                st['shuffle'], st['repeat'] = bool(self.opts['shuffle']), self.opts['repeat']
            else:               # it was already running: adopt its options
                self.opts = {'shuffle': int(st['shuffle']), 'repeat': st['repeat']}
            for addr, args in self.pending:
                self._raw(addr, *args)
            self.pending = []
        self.state = st
        self.on_state(st)

    def _watch(self, dt):
        if self.ready and time.time() - self.last_seen > 6:     # service went away
            self.ready = False
            self.started = False
        if self.started and not self.ready:
            self._raw(b'/hello')

    # -- commands from the screen
    def set_library(self, items):
        self.n_library = len(items)
        save_library(items)
        if self.ready:
            self._raw(b'/lib')

    def play(self, path):
        self._cmd(b'/play', path)

    def toggle(self):
        self._cmd(b'/toggle')

    def next(self):
        self._cmd(b'/next')

    def prev(self):
        self._cmd(b'/prev')

    def seek(self, fraction):
        if self.ready:
            self._raw(b'/seek', float(fraction))

    def set_shuffle(self, on):
        self.opts['shuffle'] = int(bool(on))
        self.state['shuffle'] = bool(on)
        if self.ready:
            self._raw(b'/shuffle', self.opts['shuffle'])
        self.on_state(self.state)

    def set_repeat(self, n):
        self.opts['repeat'] = int(n) % 3
        self.state['repeat'] = self.opts['repeat']
        if self.ready:
            self._raw(b'/repeat', self.opts['repeat'])
        self.on_state(self.state)

    def set_sleep(self, minutes):
        if self.ready:
            self._raw(b'/sleep', int(minutes))


# ====================================================================== the app
class SautiApp(App):
    title = 'Cloudkiss Music'

    def build(self):
        resource_add_path(os.path.dirname(os.path.abspath(__file__)))
        Window.clearcolor = (0.059, 0.078, 0.071, 1)
        self.library = []
        self.st = dict(DEFAULT_STATE)
        self.dragging = False
        self.last_path = None
        self.backend = (ServiceBackend(self.on_state) if platform == 'android'
                        else LocalBackend(self.on_state))
        root = Builder.load_string(KV)
        root.ids.seek.bind(on_touch_down=self._seek_down, on_touch_up=self._seek_up)
        return root

    def on_start(self):
        cached = load_library()          # show the last list straight away
        if cached:
            self._set_library(cached)
        self.backend.start()
        if platform == 'android':
            try:
                from android.permissions import request_permissions
                request_permissions(
                    ['android.permission.READ_MEDIA_AUDIO',
                     'android.permission.READ_EXTERNAL_STORAGE',
                     'android.permission.POST_NOTIFICATIONS'],
                    lambda perms, grants: Clock.schedule_once(lambda dt: self.scan(), 0))
                return
            except Exception:
                pass
        self.scan()

    # Keep the app process alive in the background; the service plays the audio anyway.
    def on_pause(self):
        return True

    def on_resume(self):
        pass

    # ---------- library ----------
    def scan(self):
        self.root.ids.status.text = 'Scanning for music...'
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        items = [read_tags(p) for p in find_audio(music_roots())]
        items.sort(key=lambda d: d['title'].casefold())
        Clock.schedule_once(lambda dt: self._set_library(items))

    def _set_library(self, items):
        self.library = items
        self.backend.set_library(items)
        n = len(items)
        self.root.ids.status.text = (
            '%d song%s' % (n, '' if n == 1 else 's') if n
            else 'No songs found. Put music in your Music or Download folder, then tap Rescan.')
        self.refresh_rows()

    def refresh_rows(self):
        q = self.root.ids.search.text.strip().lower()
        cur = self.st.get('path')
        self.root.ids.rv.data = [
            {'title': d['title'], 'artist': d['artist'] or 'Unknown artist',
             'dur_text': fmt_time(d['dur']) if d['dur'] else '', 'path': d['path'],
             'active': d['path'] == cur}
            for d in self.library
            if not q or q in (d['title'] + ' ' + d['artist']).lower()]

    def _item(self, path):
        return next((d for d in self.library if d['path'] == path), None)

    # ---------- state from the backend ----------
    def on_state(self, st):
        ids = self.root.ids
        self.st = st
        item = self._item(st['path'])
        ids.now_title.text = item['title'] if item else 'Nothing playing'
        ids.now_artist.text = st['error'] or (
            (item['artist'] or 'Unknown artist') if item else 'Pick a song to start')
        ids.btn_play.text = 'Pause' if st['playing'] else 'Play'
        ids.t_dur.text = fmt_time(st['dur'])
        if not self.dragging:
            ids.t_cur.text = fmt_time(st['pos'])
            ids.seek.value = min(1.0, st['pos'] / st['dur']) if st['dur'] > 0 else 0
        ids.btn_shuf.text = 'Shuffle: on' if st['shuffle'] else 'Shuffle'
        ids.btn_rep.text = 'Repeat: ' + ('off', 'all', 'one')[st['repeat'] % 3]
        left = st['sleep_left']
        ids.btn_sleep.text = ('Sleep timer: %d min' % math.ceil(left / 60)
                              if left else 'Sleep timer: off')
        if st['path'] != self.last_path:
            self.last_path = st['path']
            self.refresh_rows()

    # ---------- seek bar ----------
    def _seek_down(self, slider, touch):
        if slider.collide_point(*touch.pos):
            self.dragging = True
        return False

    def _seek_up(self, slider, touch):
        if self.dragging:
            self.dragging = False
            self.backend.seek(slider.value)
        return False

    # ---------- buttons ----------
    def toggle_shuffle(self):
        self.backend.set_shuffle(not self.st['shuffle'])

    def cycle_repeat(self):
        self.backend.set_repeat((self.st['repeat'] + 1) % 3)

    def cycle_sleep(self):
        options = (0, 15, 30, 60)
        left = math.ceil(self.st['sleep_left'] / 60) if self.st['sleep_left'] else 0
        bucket = next((o for o in options if o >= left), 60)
        self.backend.set_sleep(options[(options.index(bucket) + 1) % len(options)])


if __name__ == '__main__':
    SautiApp().run()
