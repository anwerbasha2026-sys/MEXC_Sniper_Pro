import os, sys

def is_android():
    return sys.platform == "android" or "ANDROID_ARGUMENT" in os.environ

if is_android():
    from app.mobile_main import MEXCSniperMobileApp
    MEXCSniperMobileApp().run()
else:
    from app.dashboard.dashboard import Dashboard
    Dashboard().mainloop()
