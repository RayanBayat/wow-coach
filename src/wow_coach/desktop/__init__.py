"""The WoW Coach desktop app (``wow-coach app``), built with Qt for Python (PySide6).

How the pieces fit together:

* ``app/core.py`` (``AppCore``) is the coach's brain. It is shared with the browser window
  and knows nothing about Qt.
* ``bridge.py`` (``CoreBridge``) is the only object the Qt windows talk to. It reads the state
  in a background thread, so a slow game hard disk never freezes the window, and turns the
  core's events into Qt signals.
* ``state.py`` turns the core's plain dict into small typed objects the pages can read.
* ``theme.py`` holds every color, size and style, in one place.
* ``main_window.py`` is the window: a sidebar on the left and one page at a time on the right.
* ``pages/`` holds one file per page (Coach chat, Notebook, Settings, ChatGPT, Setup, Privacy).
* ``run.py`` builds everything and starts the app.

Qt is an optional extra (``wow-coach[desktop]``), so nothing outside this package imports it.
"""
