"""Cloudkiss Music playback service (Android only).

Runs in its own process so music keeps playing with the screen off or the app closed.
It owns the MediaPlayer and the play queue, shows a notification with Previous /
Play-Pause / Next buttons, and talks to the app screen over OSC on localhost.

NOTE: this file could not be run while it was written (no Android device or SDK was
available). Every risky step is wrapped so a failure is printed to logcat (tag: python)
and the service keeps going without that feature.
"""
import os
import sys
import threading
import time
import traceback

try:  # make sure sauti_core.py (in the app root) is importable
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
except Exception:
    pass

from jnius import PythonJavaClass, autoclass, java_method
from oscpy.client import OSCClient
from oscpy.server import OSCThreadServer

from sauti_core import APP_PORT, SERVICE_PORT, Controller, load_library


def log(*args):
    print('[cloudkiss-service]', *args, flush=True)


# ------------------------------------------------------------------ Android classes
PythonService = autoclass('org.kivy.android.PythonService')
service = PythonService.mService           # the running Service (a Context)
PKG = service.getPackageName()

Context = autoclass('android.content.Context')
Intent = autoclass('android.content.Intent')
IntentFilter = autoclass('android.content.IntentFilter')
PendingIntent = autoclass('android.app.PendingIntent')
Notification = autoclass('android.app.Notification')
NotificationBuilder = autoclass('android.app.Notification$Builder')
MediaStyle = autoclass('android.app.Notification$MediaStyle')
NotificationChannel = autoclass('android.app.NotificationChannel')
NotificationManager = autoclass('android.app.NotificationManager')
MediaPlayer = autoclass('android.media.MediaPlayer')
AudioAttributesBuilder = autoclass('android.media.AudioAttributes$Builder')
Drawable = autoclass('android.R$drawable')
SDK = autoclass('android.os.Build$VERSION').SDK_INT

CHANNEL_ID = 'cloudkiss_playback'
NOTIF_ID = 4217
ACT_PREV = PKG + '.CK_PREV'
ACT_TOGGLE = PKG + '.CK_TOGGLE'
ACT_NEXT = PKG + '.CK_NEXT'


# ------------------------------------------------------------------ audio engine
class AndroidEngine:
    """Plays one file at a time with android.media.MediaPlayer."""

    def __init__(self):
        self.mp = None

    def load_and_play(self, path):
        self.release()
        mp = None
        try:
            mp = MediaPlayer()
            mp.setAudioAttributes(AudioAttributesBuilder().setContentType(2).setUsage(1).build())
            mp.setDataSource(path)
            try:
                mp.setWakeMode(service, 1)    # PARTIAL_WAKE_LOCK: keep playing with screen off
            except Exception:
                log('wake lock unavailable')
            mp.prepare()
            mp.start()
            self.mp = mp
            return True
        except Exception:
            log('could not play', path, traceback.format_exc())
            try:
                if mp is not None:
                    mp.release()
            except Exception:
                pass
            return False

    def pause(self):
        try:
            self.mp.pause()
        except Exception:
            pass

    def resume(self):
        try:
            self.mp.start()
        except Exception:
            pass

    def seek(self, seconds):
        try:
            self.mp.seekTo(int(seconds * 1000))
        except Exception:
            pass

    def position(self):
        try:
            return self.mp.getCurrentPosition() / 1000.0
        except Exception:
            return 0.0

    def duration(self):
        try:
            return max(0, self.mp.getDuration()) / 1000.0
        except Exception:
            return 0.0

    def is_playing(self):
        try:
            return bool(self.mp.isPlaying())
        except Exception:
            return False

    def release(self):
        try:
            if self.mp is not None:
                self.mp.release()
        except Exception:
            pass
        self.mp = None


lock = threading.RLock()
ctl = Controller(AndroidEngine())
last_ui = time.time()
_keep_alive = []     # Java callback objects must not be garbage collected


# ------------------------------------------------------------------ notification
def _pending(action, code):
    intent = Intent(action)
    intent.setPackage(PKG)
    flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
    return PendingIntent.getBroadcast(service, code, intent, flags)


def build_notification(title, text, playing):
    b = NotificationBuilder(service, CHANNEL_ID)
    icon = service.getApplicationInfo().icon or Drawable.ic_media_play
    b.setSmallIcon(icon)
    b.setContentTitle(title)
    b.setContentText(text)
    b.setOngoing(True)
    b.setOnlyAlertOnce(True)
    b.setShowWhen(False)
    b.setVisibility(Notification.VISIBILITY_PUBLIC)   # show buttons on the lock screen
    try:
        launch = service.getPackageManager().getLaunchIntentForPackage(PKG)
        if launch is not None:
            flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
            b.setContentIntent(PendingIntent.getActivity(service, 0, launch, flags))
    except Exception:
        log('content intent failed', traceback.format_exc())
    if receiver_ok:
        b.addAction(Drawable.ic_media_previous, 'Previous', _pending(ACT_PREV, 1))
        b.addAction(Drawable.ic_media_pause if playing else Drawable.ic_media_play,
                    'Pause' if playing else 'Play', _pending(ACT_TOGGLE, 2))
        b.addAction(Drawable.ic_media_next, 'Next', _pending(ACT_NEXT, 3))
        try:
            style = MediaStyle()
            style.setShowActionsInCompactView([0, 1, 2])
            b.setStyle(style)
        except Exception:
            log('media style failed', traceback.format_exc())
    return b.build()


def make_channel():
    nm = service.getSystemService(Context.NOTIFICATION_SERVICE)
    channel = NotificationChannel(CHANNEL_ID, 'Playback', NotificationManager.IMPORTANCE_LOW)
    channel.setShowBadge(False)
    nm.createNotificationChannel(channel)
    return nm


class _ReceiverCallback(PythonJavaClass):
    """Bridges Android broadcasts (notification buttons) into Python."""
    __javainterfaces__ = ['org/kivy/android/GenericBroadcastReceiverCallback']
    __javacontext__ = 'app'

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    @java_method('(Landroid/content/Context;Landroid/content/Intent;)V')
    def onReceive(self, context, intent):
        try:
            self.fn(intent.getAction())
        except Exception:
            log(traceback.format_exc())


def on_action(action):
    with lock:
        if action == ACT_TOGGLE:
            ctl.toggle()
        elif action == ACT_NEXT:
            ctl.next()
        elif action == ACT_PREV:
            ctl.prev()
    push_state()
    refresh_notification(force=True)


def register_receiver():
    callback = _ReceiverCallback(on_action)
    receiver = autoclass('org.kivy.android.GenericBroadcastReceiver')(callback)
    flt = IntentFilter()
    for a in (ACT_PREV, ACT_TOGGLE, ACT_NEXT):
        flt.addAction(a)
    if SDK >= 33:
        service.registerReceiver(receiver, flt, Context.RECEIVER_NOT_EXPORTED)
    else:
        service.registerReceiver(receiver, flt)
    _keep_alive.extend([callback, receiver])


receiver_ok = False
try:
    register_receiver()
    receiver_ok = True
except Exception:
    log('notification buttons unavailable:', traceback.format_exc())

nm = None
try:
    nm = make_channel()
except Exception:
    log('notification channel failed', traceback.format_exc())

_last_key = None


def refresh_notification(force=False):
    global _last_key
    if nm is None:
        return
    with lock:
        st = ctl.state()
        item = ctl.item()
    key = (st['path'], st['playing'])
    if key == _last_key and not force:
        return
    _last_key = key
    title = item['title'] if item else 'Cloudkiss Music'
    text = (item['artist'] or 'Unknown artist') if item else 'Ready to play'
    try:
        nm.notify(NOTIF_ID, build_notification(title, text, st['playing']))
    except Exception:
        log('notification update failed', traceback.format_exc())


def promote_foreground():
    """Swap p4a's plain foreground notification for ours (needed on Android 14)."""
    try:
        notif = build_notification('Cloudkiss Music', 'Ready to play', False)
        if SDK >= 29:
            service.startForeground(NOTIF_ID, notif, 2)   # 2 = media playback
        else:
            service.startForeground(NOTIF_ID, notif)
    except Exception:
        log('startForeground failed', traceback.format_exc())


# ------------------------------------------------------------------ talking to the screen
client = OSCClient('127.0.0.1', APP_PORT, encoding='utf8')


def push_state():
    with lock:
        st = ctl.state()
    try:
        client.send_message(b'/state', [
            st['path'], int(st['playing']), float(st['pos']), float(st['dur']),
            int(st['shuffle']), int(st['repeat']), st['error'],
            int(st['sleep_left']), int(st['nlib'])])
    except Exception:
        pass


def _flat(args):
    if len(args) == 1 and isinstance(args[0], (list, tuple)):
        return list(args[0])
    return list(args)


def on_command(name):
    def handler(*args):
        global last_ui
        last_ui = time.time()
        a = _flat(args)
        try:
            with lock:
                if name == 'lib':
                    ctl.set_library(load_library())
                elif name == 'play':
                    ctl.play_path(a[0])
                elif name == 'toggle':
                    ctl.toggle()
                elif name == 'next':
                    ctl.next()
                elif name == 'prev':
                    ctl.prev()
                elif name == 'seek':
                    ctl.seek_fraction(float(a[0]))
                elif name == 'shuffle':
                    ctl.set_shuffle(int(a[0]))
                elif name == 'repeat':
                    ctl.set_repeat(int(a[0]))
                elif name == 'sleep':
                    ctl.set_sleep(int(a[0]))
        except Exception:
            log('command failed', name, traceback.format_exc())
        push_state()
        refresh_notification()
    return handler


osc = OSCThreadServer(encoding='utf8')
osc.listen(address='127.0.0.1', port=SERVICE_PORT, default=True)
for _name in ('hello', 'lib', 'play', 'toggle', 'next', 'prev', 'seek', 'shuffle', 'repeat', 'sleep'):
    osc.bind(('/' + _name).encode(), on_command(_name))


# ------------------------------------------------------------------ main loop
def main():
    with lock:
        ctl.set_library(load_library())
    promote_foreground()
    log('service ready, songs:', len(ctl.library), 'buttons:', receiver_ok)
    idle_since = None
    while True:
        time.sleep(0.5)
        with lock:
            ctl.tick()
            playing = ctl.playing
        push_state()
        refresh_notification()
        now = time.time()
        if playing:
            idle_since = None
        else:
            idle_since = idle_since or now
            # nothing playing for 10 minutes and the app is gone: stop, drop the notification
            if now - idle_since > 600 and now - last_ui > 120:
                log('idle, stopping service')
                ctl.engine.release()
                try:
                    service.stopForeground(True)
                    service.stopSelf()
                except Exception:
                    pass
                break


main()
