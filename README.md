# Cloudkiss Music

A simple offline music player for Android, written in Python with Kivy.
Music plays from a background service, so it keeps going with the screen off, and the
notification has Previous / Play-Pause / Next buttons.

## Get the APK (no Android Studio needed)

1. Create a free GitHub repository and upload everything in this folder
   (keep the `.github/workflows` folder).
2. Open the repo's **Actions** tab, choose **Build APK**, press **Run workflow**.
3. When it finishes (about 20-40 minutes the first time), download the
   `cloudkiss-music-apk` artifact, unzip it and copy the `.apk` to your phone.
4. Allow "install unknown apps", install, and accept the music and notification permissions.

## Run it on a PC first

    pip install kivy mutagen
    SAUTI_MUSIC_DIR=/path/to/your/music python main.py

On a PC the playback logic runs inside the app (no service). Run the tests with
`python -m unittest`.

## Files

- `main.py` - the Kivy screen, plus the two backends (service on Android, local on PC)
- `service/playback.py` - the Android background service: MediaPlayer, queue, notification
- `sauti_core.py` - scanning, tags, queue and the playback Controller (tested by `test_core.py`)
- `buildozer.spec` - APK settings (name, permissions, the service line)
- `wallpaper.jpg` - the background photo (replace it with any picture, same name)
- `icon-512.png`, `icon-192.png` - app icon

## If something does not work

The service was written without a phone or Android SDK to test on. If you install the APK
and music does not start, connect the phone and run `adb logcat -s python`; lines starting
with `[cloudkiss-service]` and `[cloudkiss]` explain what failed. Send them to me and I
will fix it.

## Known limits

- Songs are found by scanning the Music, Download and Documents folders.
- No playback-speed control (Kivy's audio API does not support it).
- The notification has the three buttons, but it is not a full media card: no seek bar on
  the lock screen, and no Bluetooth or headset-button support (that needs an Android media
  session).
- No audio-focus handling yet: a phone call will not pause the music automatically.
