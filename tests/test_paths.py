import os
import sys

import pytest

from mojo.world.paths import PathError, check_relative_path, resolve_inside


@pytest.mark.parametrize("p", [
    "audio/narration.wav", "a.png", "img/sub/dir/x_1-2.png",
])
def test_ok(p):
    assert check_relative_path(p) == p


@pytest.mark.parametrize("p", [
    "../x", "a/../../x", "..", ".", "a//b", "/etc/passwd", "~/x", "~root/x", "C:/x", "C:\\x", "\\\\srv\\share\\x",
    "a\\b", "a/./b", "x:stream", "con", "dir/NUL.txt", "com1", "lpt3.wav", "a/b ", "a/b.", "", "a\x00b", "a\nb",
    "é/x".encode("utf-8").decode("latin-1"), "a/" + "b" * 0 + "/c", "x" * 201, "/".join(["d"] * 13),
    "ａ/ｂ", "a b/../c", "%2e%2e/x",
])
def test_rejected(p):
    with pytest.raises(PathError):
        check_relative_path(p)


def test_non_string():
    with pytest.raises(PathError):
        check_relative_path(None)  # type: ignore[arg-type]


@pytest.mark.skipif(sys.platform.startswith("win"), reason="symlink exige privilégio no Windows")
def test_symlink_escape_blocked(tmp_path):
    root = tmp_path / "world"
    root.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "k.txt").write_text("x")
    os.symlink(outside, root / "lnk")
    with pytest.raises(PathError):
        resolve_inside(root, "lnk/k.txt")
    (root / "ok.txt").write_text("y")
    assert resolve_inside(root, "ok.txt") == (root / "ok.txt").resolve()
