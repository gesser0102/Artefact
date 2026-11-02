import builtins
import io
import os
import pathlib

import pytest


@pytest.fixture(autouse=True)
def forbid_disk_access(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError(f"application unit test touched the disk: {args}")

    monkeypatch.setattr(builtins, "open", fail)
    monkeypatch.setattr(io, "open", fail)
    monkeypatch.setattr(os, "open", fail)
    monkeypatch.setattr(pathlib.Path, "open", fail)
