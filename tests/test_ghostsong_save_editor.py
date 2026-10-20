from http.client import HTTPConnection
import pathlib
from playwright.sync_api import Page, expect
import pytest
import re
import struct
from subprocess import Popen, PIPE
import sys
import time

test_dir = pathlib.Path(__file__).parent.absolute()
root = test_dir.parent.absolute()
URL = "http://127.0.0.1:8123/ghostsong-save-editor.html"

NANOGEL = 602


# ─── Synthetic save file ──────────────────────────────────────────────────────
# Ghost Song saves are a .NET BinaryFormatter (MS-NRBF) System.Collections.Hashtable.
# This writes a small one with the same layout so the tests don't need a real save.

def lps(s: str) -> bytes:
    """Length-prefixed UTF-8 string (7-bit encoded length)."""
    body = s.encode("utf-8")
    n, head = len(body), bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        head.append(b | (0x80 if n else 0))
        if not n:
            return bytes(head) + body


def i32(v: int) -> bytes:
    return struct.pack("<i", v)


def f32(v: float) -> bytes:
    return struct.pack("<f", v)


def build_save() -> bytes:
    INT32, SINGLE, BOOLEAN = 8, 11, 1
    ids = iter(range(100, 10_000))

    def string(s):
        return b"\x06" + i32(next(ids)) + lps(s)

    def prim(ptype, raw):
        return b"\x08" + bytes([ptype]) + raw

    def ref(object_id):
        return b"\x09" + i32(object_id)

    shared_region_id = next(ids)
    stats_id, list_id, items_id = 10, 11, 12
    entries = [
        ("nanites1", prim(INT32, i32(NANOGEL))),
        ("healthmax1", prim(SINGLE, f32(208))),
        ("health1", prim(SINGLE, f32(208))),
        ("dashinvuln1", prim(BOOLEAN, b"\x01")),
        ("MostRecentSave", prim(INT32, i32(1))),
        ("classname1", string("Lost Soul")),
        ("region1", b"\x06" + i32(shared_region_id) + lps("Droid Lab")),
        ("regionaswritten1", ref(shared_region_id)),
        ("basestats1", ref(stats_id)),
        ("inventory1", ref(list_id)),
    ]

    out = bytearray()
    # SerializedStreamHeader: root object 1
    out += b"\x00" + i32(1) + i32(-1) + i32(1) + i32(0)
    # Hashtable (SystemClassWithMembersAndTypes)
    members = ["LoadFactor", "Version", "Comparer", "HashCodeProvider", "HashSize", "Keys", "Values"]
    out += b"\x04" + i32(1) + lps("System.Collections.Hashtable") + i32(len(members))
    out += b"".join(lps(m) for m in members)
    out += bytes([0, 0, 3, 3, 0, 5, 5])
    out += bytes([SINGLE, INT32]) + lps("System.Collections.IComparer") + lps("System.Collections.IHashCodeProvider") + bytes([INT32])
    out += f32(0.72) + i32(len(entries)) + b"\x0a\x0a" + i32(23) + ref(2) + ref(3)
    # Keys and Values (ArraySingleObject)
    out += b"\x10" + i32(2) + i32(len(entries)) + b"".join(string(k) for k, _ in entries)
    out += b"\x10" + i32(3) + i32(len(entries)) + b"".join(v for _, v in entries)
    # Stats class from the game assembly
    stats = ["Health", "Spirit", "Ammo", "GunPower", "Volatility", "Vigor", "Luck"]
    out += b"\x0c" + i32(20) + lps("Assembly-CSharp, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null")
    out += b"\x05" + i32(stats_id) + lps("Stats") + i32(len(stats)) + b"".join(lps(s) for s in stats)
    out += bytes([0] * len(stats)) + bytes([SINGLE] * len(stats)) + i32(20)
    out += b"".join(f32(v) for v in [60, 45, 150, 9, 15, 8, 6])
    # List<int>: _items (backing array), _size, _version
    out += b"\x04" + i32(list_id)
    out += lps("System.Collections.Generic.List`1[[System.Int32, mscorlib, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089]]")
    out += i32(3) + lps("_items") + lps("_size") + lps("_version")
    out += bytes([7, 0, 0, INT32, INT32, INT32])
    out += ref(items_id) + i32(3) + i32(0)
    out += b"\x0f" + i32(items_id) + i32(4) + bytes([INT32]) + b"".join(i32(v) for v in [1, 0, 5, 0])
    out += b"\x0b"  # MessageEnd
    return bytes(out)


@pytest.fixture(scope="module")
def save_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("ghostsong") / "SaveData"
    path.write_bytes(build_save())
    return path


@pytest.fixture(scope="module")
def static_server():
    """Start a local HTTP server for testing"""
    process = Popen(
        [sys.executable, "-m", "http.server", "8123", "--directory", root],
        stdout=PIPE
    )
    retries = 5
    while retries > 0:
        conn = HTTPConnection("127.0.0.1:8123")
        try:
            conn.request("HEAD", "/")
            response = conn.getresponse()
            if response is not None:
                yield process
                break
        except ConnectionRefusedError:
            time.sleep(1)
            retries -= 1

    if not retries:
        raise RuntimeError("Failed to start http server")
    else:
        process.terminate()
        process.wait()


def load_save(page: Page, save_file):
    page.goto(URL)
    page.locator("#fileInput").set_input_files(str(save_file))
    expect(page.locator("#status-msg")).to_contain_text("Safety check passed")


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_initial_state(page: Page, static_server):
    page.goto(URL)
    expect(page.locator("h1")).to_have_text("Ghost Song Save Editor")
    expect(page.locator("#dropzone")).to_be_visible()
    expect(page.locator("#quick-panel")).to_be_hidden()


def test_load_shows_quick_fields(page: Page, static_server, save_file):
    load_save(page, save_file)
    expect(page.locator("#slot-select")).to_have_value("1")
    expect(page.locator("#q-nanites-")).to_have_value(str(NANOGEL))
    expect(page.locator("#q-healthmax-")).to_have_value("208")
    expect(page.locator("#q-basestats-Health")).to_have_value("60")
    expect(page.locator("#all-count")).to_have_text("10 keys")
    expect(page.locator("#download-btn")).to_be_disabled()


def test_edit_nanogel_changes_only_that_value(page: Page, static_server, save_file):
    load_save(page, save_file)
    page.locator("#q-nanites-").fill("99999")
    page.locator("#q-nanites-").press("Tab")
    expect(page.locator("#changes-list")).to_contain_text("nanites1")
    expect(page.locator("#save-count")).to_have_text("1 pending change")

    with page.expect_download() as download_info:
        page.locator("#download-btn").click()
    download = download_info.value
    assert download.suggested_filename == "SaveData"
    expect(page.locator("#status-msg")).to_contain_text("exactly 1 changed value")

    # Independent of the page's own checks: the only difference should be the
    # four bytes holding the Int32 nanogel count.
    original = save_file.read_bytes()
    edited = pathlib.Path(download.path()).read_bytes()
    offset = original.index(b"\x08\x08" + i32(NANOGEL)) + 2
    assert edited == original[:offset] + i32(99999) + original[offset + 4:]


def test_shared_string_is_flagged_and_edits_all_users(page: Page, static_server, save_file):
    load_save(page, save_file)
    page.locator("#filter").fill("region")
    row = page.locator("#tree > .tree-row[data-key=region1]")
    expect(row.locator(".badge")).to_have_text("shared ×2")
    row.locator("input").fill("Somewhere Else")
    row.locator("input").press("Tab")
    expect(page.locator("#tree > .tree-row[data-key=regionaswritten1] input")).to_have_value("Somewhere Else")
    expect(page.locator("#save-count")).to_have_text("1 pending change")


def test_invalid_value_is_rejected(page: Page, static_server, save_file):
    load_save(page, save_file)
    field = page.locator("#q-nanites-")
    field.fill("3000000000")
    field.press("Tab")
    expect(field).to_have_class(re.compile(r"\binvalid\b"))
    expect(page.locator("#quick-body")).to_contain_text("out of range")
    expect(page.locator("#save-count")).to_have_text("No changes yet")


def test_revert_all(page: Page, static_server, save_file):
    load_save(page, save_file)
    page.locator("#q-basestats-Vigor").fill("20")
    page.locator("#q-basestats-Vigor").press("Tab")
    expect(page.locator("#save-count")).to_have_text("1 pending change")
    page.locator("#reset-all-btn").click()
    expect(page.locator("#q-basestats-Vigor")).to_have_value("8")
    expect(page.locator("#download-btn")).to_be_disabled()


def test_rejects_non_save_file(page: Page, static_server):
    page.goto(URL)
    page.locator("#fileInput").set_input_files(
        files=[{"name": "notes.txt", "mimeType": "text/plain", "buffer": b"hello world"}]
    )
    expect(page.locator("#error-msg")).to_contain_text("doesn't look like a Ghost Song save")
    expect(page.locator("#quick-panel")).to_be_hidden()


def test_rejects_truncated_save(page: Page, static_server):
    page.goto(URL)
    page.locator("#fileInput").set_input_files(
        files=[{"name": "SaveData", "mimeType": "application/octet-stream", "buffer": build_save()[:200]}]
    )
    expect(page.locator("#error-msg")).to_contain_text("Unexpected end of file")
    expect(page.locator("#quick-panel")).to_be_hidden()
