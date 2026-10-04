# Live Trades Android UI stability fix

This patch keeps the Live Trades tab navigation lightweight on Android.

Changes:
- Account/network refresh is deferred until after the tab transition.
- Concurrent account-sync requests are coalesced.
- LIVE position cards are rebuilt only while the LIVE Trades tab is visible.
- Background/service state updates no longer rebuild hidden LIVE position widgets.
- The existing real-account synchronization and manual SELL logic are preserved.

The goal is to prevent the Kivy main thread from being flooded by API synchronization
and widget rebuilding when LIVE Trades is opened.
