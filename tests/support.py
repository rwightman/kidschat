"""Test helpers for running backend unit tests without third-party installs."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace


class FakeArray:
    """Small stand-in for the numpy array behavior used by STT tests."""

    def __init__(self, data: bytes):
        self.data = data
        self.dtype = None
        self.divisor = None

    def astype(self, dtype):
        self.dtype = dtype
        return self

    def __itruediv__(self, divisor):
        self.divisor = divisor
        return self


def install_dependency_stubs() -> None:
    """Install lightweight module stubs for optional runtime dependencies."""
    if "ollama" not in sys.modules:
        try:
            import ollama  # noqa: F401
        except Exception:
            ollama = ModuleType("ollama")

            class AsyncClient:
                def __init__(self, host=None):
                    self.host = host

                async def list(self):
                    return SimpleNamespace(models=[])

                async def chat(self, **kwargs):
                    raise AssertionError("Unexpected call to stub ollama.AsyncClient.chat")

            ollama.AsyncClient = AsyncClient
            sys.modules["ollama"] = ollama

    if "httpx" not in sys.modules:
        try:
            import httpx  # noqa: F401
        except Exception:
            httpx = ModuleType("httpx")

            class AsyncClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    return False

                async def get(self, *args, **kwargs):
                    raise AssertionError("Unexpected call to stub httpx.AsyncClient.get")

            httpx.AsyncClient = AsyncClient
            sys.modules["httpx"] = httpx

    if "numpy" not in sys.modules:
        try:
            import numpy  # noqa: F401
        except Exception:
            numpy = ModuleType("numpy")
            numpy.int16 = "int16"
            numpy.float32 = "float32"

            def frombuffer(data, dtype=None):
                array = FakeArray(data)
                array.dtype = dtype
                return array

            numpy.frombuffer = frombuffer
            numpy.FakeArray = FakeArray
            sys.modules["numpy"] = numpy


install_dependency_stubs()
