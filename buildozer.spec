[app]
title = Cloudkiss Music
package.name = cloudkissmusic
package.domain = org.cloudkiss
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 0.2
requirements = python3,kivy==2.3.0,mutagen,android,pyjnius,oscpy
orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/icon-512.png

# Background playback: a foreground service (its own process) that owns the audio.
# Android 14+ requires the foregroundServiceType on foreground services.
services = playback:service/playback.py:foreground:sticky:foregroundServiceType=mediaPlayback

android.permissions = READ_EXTERNAL_STORAGE,READ_MEDIA_AUDIO,POST_NOTIFICATIONS,FOREGROUND_SERVICE,FOREGROUND_SERVICE_MEDIA_PLAYBACK,WAKE_LOCK
android.api = 34
android.minapi = 26
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
