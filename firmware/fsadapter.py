"""
Filesystem adapter for datalog.RotatingCsv on MicroPython. Kept separate so the
pure datalog logic stays host-testable (tests inject a fake with the same methods).
"""

import os


class FsAdapter:
    def __init__(self, directory):
        self.dir = directory
        try:
            os.mkdir(directory)
        except OSError:
            pass  # already exists

    def open(self, path, mode):
        return open(path, mode)

    def size(self, path):
        """Return byte size, or None if the file doesn't exist."""
        try:
            return os.stat(path)[6]
        except OSError:
            return None

    def remove(self, path):
        try:
            os.remove(path)
        except OSError:
            pass

    def rename(self, src, dst):
        os.rename(src, dst)
