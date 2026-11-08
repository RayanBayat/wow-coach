"""Read small text files without following links or touching special files.

The game folder is not ours alone, so a path in it could be a link to something big or
secret, or a special file (a pipe, a device) that blocks. We only read plain files.
"""

import os
import stat
from pathlib import Path


def read_plain_text(path: Path, max_bytes: int) -> str | None:
    """Return the text of a plain file of at most ``max_bytes`` bytes, else None.

    None means: missing, a link, not a regular file, too big, not UTF-8 or unreadable.
    At most ``max_bytes + 1`` bytes are ever read, even if the file grows while we read.
    """
    try:
        if not stat.S_ISREG(path.lstat().st_mode):  # lstat: a link is not a regular file
            return None
        # O_NOFOLLOW / O_NONBLOCK close the small gap between the check above and the open.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return None
            data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            return None
        return data.decode("utf-8")
    except OSError, ValueError:  # ValueError covers UnicodeDecodeError
        return None
