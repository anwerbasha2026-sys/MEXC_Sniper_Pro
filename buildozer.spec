[app]
title = MEXC Sniper Mobile
package.name = mexcsniper
package.domain = org.mexcsniper
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,json,txt,csv,proto
source.exclude_dirs = .git,.buildozer,bin,__pycache__
version = 1.1.0
requirements = python3,kivy==2.3.1,requests==2.32.5,httpx,websockets,protobuf,python-dotenv,pydantic,pydantic-settings
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE,WAKE_LOCK,FOREGROUND_SERVICE,POST_NOTIFICATIONS
android.api = 33
android.minapi = 23
android.ndk = 25b
android.ndk_api = 23
android.archs = armeabi-v7a
android.enable_androidx = True
android.accept_sdk_license = True
android.private_storage = True
android.debug_artifact = apk

[buildozer]
log_level = 2
warn_on_root = 1

p4a.bootstrap = sdl2
services = sniperd:service.py:foreground:sticky
