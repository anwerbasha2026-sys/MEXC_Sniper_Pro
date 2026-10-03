[app]
# MEXC Sniper Stage 26 - Android ARMv7 / Onn GN3
# Windows entry point remains app/main.py. Android uses root main.py.
title = MEXC Sniper Pro
package.name = mexcsniper
package.domain = org.mexcsniper
name = MEXC Sniper
version = 26.1-android

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,proto,txt,csv,db
source.exclude_dirs = .git,.github,.buildozer,bin,__pycache__,tests,test,docs

# Android entry point
orientation = landscape
fullscreen = 0

# Onn GN3 / armeabi-v7a target
android.archs = armeabi-v7a
android.api = 27
android.minapi = 21
android.ndk = 25b
android.ndk_api = 23

# Stable p4a release: Python 3.11, avoiding the Python 3.14/preadv/pwritev
# failure seen on the target tablet.
p4a.branch = v2024.01.21

requirements = python3==3.11.5,kivy==2.3.0,websockets>=15.0,protobuf>=7.36.2,<8,pydantic>=2.0,pydantic-settings>=2.0,python-dotenv>=1.0,httpx>=0.27

# No Android-specific imports are used by the Python entry point.
# The app starts Kivy first, then launches the existing scanner in a worker.
android.permissions = INTERNET,ACCESS_NETWORK_STATE,WAKE_LOCK
android.private_storage = True
android.allow_backup = True

presplash.filename = %(source.dir)s/android/presplash.png
icon.filename = %(source.dir)s/android/icon.png

# Avoid packaging desktop launcher scripts as Python entry points.

[buildozer]
log_level = 2
warn_on_root = 1

# Stable python-for-android release.
p4a.branch = v2024.01.21
