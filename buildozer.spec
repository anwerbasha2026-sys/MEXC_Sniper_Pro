[app]
title = MEXC Sniper Mobile
package.name = mexcsniper
package.domain = org.mexcsniper
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,json,txt,csv,proto
source.exclude_dirs = .git,.buildozer,bin,__pycache__
version = 1.3.1
requirements = python3==3.11.5,hostpython3==3.11.5,kivy==2.3.1,requests==2.32.5,httpx,websockets,protobuf==7.36.2,python-dotenv,pydantic,pydantic-settings
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE,WAKE_LOCK,FOREGROUND_SERVICE,POST_NOTIFICATIONS,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 23
android.ndk = 25b
android.ndk_api = 23
android.archs = armeabi-v7a
android.enable_androidx = True
android.accept_sdk_license = True
android.private_storage = True
android.debug_artifact = apk
android.logcat_filters = *:S python:I AndroidRuntime:E SDLThread:E

# IMPORTANT: services belongs in [app]. Placing it under [buildozer]
# does not declare a Python-for-Android service, so ServiceSniperd was absent
# from the APK and the UI received ClassNotFoundException/JavaException.
services = sniperd:service.py:foreground:sticky

[buildozer]
log_level = 2
warn_on_root = 1

p4a.bootstrap = sdl2
p4a.branch = v2024.01.21
