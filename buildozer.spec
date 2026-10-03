[app]
title = MEXC Sniper Mobile
package.name = mexcsniper
package.domain = org.mexcsniper
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,json,txt,csv,proto
version = 1.0.0
requirements = python3,kivy,requests,pydantic,pydantic-settings,python-dotenv,websockets,protobuf,httpx
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 35
android.minapi = 23

[buildozer]
log_level = 2
warn_on_root = 1

[python-for-android]
bootstrap = sdl2
requirements = python3,kivy,requests,pydantic,pydantic-settings,python-dotenv,websockets,protobuf,httpx
