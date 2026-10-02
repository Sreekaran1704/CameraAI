"""Every test denies outbound Python socket connections by default."""

import socket

import pytest

from photocull.config import Config
from photocull.fixtures import generate_fixtures


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Network access is forbidden in tests")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def photos(tmp_path):
    folder = tmp_path / "photos"
    generate_fixtures(folder)
    return folder


@pytest.fixture
def config(tmp_path):
    return Config(cache_dir=tmp_path / "cache")
