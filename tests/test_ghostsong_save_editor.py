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


def build_save(*, knowledge=False, day=4, short_suit_list=False, progress=None, progress_sizes=None) -> bytes:
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

    extra_records = bytearray()
    if knowledge:
        def saved_list(key, ptype, values, size=None):
            object_id, array_id = next(ids), next(ids)
            entries.append((key, ref(object_id)))
            inner = "System.Boolean" if ptype == BOOLEAN else "System.Int32"
            extra_records.extend(b"\x04" + i32(object_id))
            extra_records.extend(lps(f"System.Collections.Generic.List`1[[{inner}, mscorlib]]"))
            extra_records.extend(i32(3) + lps("_items") + lps("_size") + lps("_version"))
            extra_records.extend(bytes([7, 0, 0, ptype, INT32, INT32]))
            extra_records.extend(ref(array_id) + i32(len(values) if size is None else size) + i32(0))
            extra_records.extend(b"\x0f" + i32(array_id) + i32(len(values)) + bytes([ptype]))
            extra_records.extend(bytes(values) if ptype == BOOLEAN else b"".join(i32(v) for v in values))

        # Include hidden blasters and a dummy equipped flag: never interpret those
        # as regular modules or change them when granting a collectible.
        saved_list("wmacquired1", BOOLEAN, [True, True, False, True] + [False] * 15)
        saved_list("wmequipped1", BOOLEAN, [True] + [False] * 17 + [True])
        saved_list("mmacquired1", BOOLEAN, [True] * 18)
        saved_list("mmequipped1", BOOLEAN, [False] * 18)
        saved_list("smacquired1", BOOLEAN, [True] * 6 + [False, True, True, True], size=6 if short_suit_list else 9)
        saved_list("smequipped1", BOOLEAN, [False] * 9)
        saved_list("wmacquired2", BOOLEAN, [False] * 19)
        saved_list("wmequipped2", BOOLEAN, [False] * 19)
        pasha_values = [0] * 15
        pasha_values[2] = pasha_values[3] = pasha_values[4] = 3
        saved_list("pashaprogress1", INT32, pasha_values)
        other = [0] * 72
        other[71] = 2
        saved_list("otherdata1", INT32, other)
        saved_list("miscworldstate1", INT32, [0] * 72)
        entries.extend([
            ("day1", prim(INT32, i32(day))),
            ("day2", prim(INT32, i32(3))),
            ("nanites2", prim(INT32, i32(99))),
        ])

    if progress:
        for key, value in progress.items():
            entries = [(k, v) for k, v in entries if k != key]
            if value is None:
                continue
            if isinstance(value, list):
                saved_list(key, BOOLEAN if value and type(value[0]) is bool else INT32, value, size=(progress_sizes or {}).get(key))
            elif isinstance(value, dict):
                object_id = next(ids)
                entries.append((key, ref(object_id)))
                names = list(value)
                extra_records.extend(b"\x04" + i32(object_id) + lps("SeedCounts") + i32(len(names)))
                extra_records.extend(b"".join(lps(name) for name in names))
                extra_records.extend(bytes([0] * len(names)) + bytes([INT32] * len(names)))
                extra_records.extend(b"".join(i32(value[name]) for name in names))
            elif isinstance(value, bool):
                entries.append((key, prim(BOOLEAN, bytes([value]))))
            else:
                entries.append((key, prim(INT32, i32(value))))

    out = bytearray()
    # SerializedStreamHeader: root object 1
    out += b"\x00" + i32(1) + i32(-1) + i32(1) + i32(0)
    # Hashtable (SystemClassWithMembersAndTypes)
    members = ["LoadFactor", "Version", "Comparer", "HashCodeProvider", "HashSize", "Keys", "Values"]
    out += b"\x04" + i32(1) + lps("System.Collections.Hashtable") + i32(len(members))
    out += b"".join(lps(m) for m in members)
    out += bytes([0, 0, 3, 3, 0, 5, 5])
    out += bytes([SINGLE, INT32]) + lps("System.Collections.IComparer") + lps("System.Collections.IHashCodeProvider") + bytes([INT32])
    out += f32(0.72) + i32(len(entries)) + b"\x0a\x0a" + i32(97 if knowledge else 23) + ref(2) + ref(3)
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
    out += extra_records
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


def load_save(page: Page, save_file, readonly=False):
    page.goto(URL)
    page.locator("#fileInput").set_input_files(str(save_file))
    expect(page.locator("#status-msg")).to_contain_text("Safety check passed")
    if not readonly:
        page.locator("#enable-editing").check()
        page.locator('#navigation button[data-view="all"]').click()


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_initial_state(page: Page, static_server):
    page.goto(URL)
    expect(page.locator("h1")).to_have_text("Ghost Song Progress Checker")
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


def load_knowledge_save(page, readonly=False, **kwargs):
    original = build_save(knowledge=True, **kwargs)
    page.goto(URL)
    page.locator("#fileInput").set_input_files(
        files=[{"name": "SaveData", "mimeType": "application/octet-stream", "buffer": original}]
    )
    expect(page.locator("#status-msg")).to_contain_text("Safety check passed")
    if not readonly:
        page.locator("#enable-editing").check()
        page.locator('#navigation button[data-view="all"]').click()
    return original


def test_module_catalog_matches_current_game_order(page: Page, static_server):
    load_knowledge_save(page)
    labels = page.locator(".module-group").first.locator("label").all_text_contents()
    assert [label.split("Owned")[0].split("Missing")[0].split("Equipped")[0] for label in labels[:4]] == [
        "Cloudburst Rifle", "The Heartbreaker", "Scatterburst", "Chill Crumbler"
    ]
    expect(page.locator(".module-row")).to_have_count(40)
    expect(page.locator("#module-wm-18")).to_have_count(0)
    expect(page.locator("#module-wm-6")).to_have_count(0)
    expect(page.locator("#module-wm-8")).to_have_count(0)
    expect(page.locator("#module-wm-7")).to_be_visible()
    expect(page.locator("#module-sm-6")).to_have_value("false")
    expect(page.locator("#q-basestats-Volatility").locator("..")).to_contain_text("Resolve")
    expect(page.locator("#q-basestats-Luck").locator("..")).to_contain_text("fixed 3%")


def test_grant_shell_exports_only_one_boolean(page: Page, static_server):
    original = load_knowledge_save(page)
    page.locator("#module-sm-6").select_option("true")
    expect(page.locator("#changes-list")).to_contain_text("smacquired1[6] · Frenzied Shell")
    expect(page.locator("#save-count")).to_have_text("1 pending change")
    with page.expect_download() as info:
        page.locator("#download-btn").click()
    edited = pathlib.Path(info.value.path()).read_bytes()
    changes = [(old, new) for old, new in zip(original, edited) if old != new]
    assert len(edited) == len(original)
    assert changes == [(0, 1)]
    # Read the downloaded bytes as a fresh file, not just the in-memory model.
    page.locator("#fileInput").set_input_files(files=[{
        "name": "SaveData", "mimeType": "application/octet-stream", "buffer": edited
    }])
    expect(page.locator("#module-sm-6")).to_have_value("true")
    expect(page.locator("#module-wm-2")).to_have_value("false")


def test_module_search_missing_filter_and_revert(page: Page, static_server):
    load_knowledge_save(page)
    page.locator("#module-filter").fill("Frenzied")
    page.locator("#missing-only").check()
    expect(page.locator(".module-row:visible")).to_have_count(1)
    expect(page.locator(".module-row:visible")).to_contain_text("unaffected by Luck")
    page.locator("#module-sm-6").select_option("true")
    expect(page.locator(".module-row:visible")).to_have_count(0)
    page.locator("#reset-all-btn").click()
    expect(page.locator(".module-row:visible")).to_have_count(1)
    expect(page.locator("#module-sm-6")).to_have_value("false")


def test_module_lists_use_logical_size(page: Page, static_server):
    load_knowledge_save(page, short_suit_list=True)
    # Backing capacity has shell flags, but the saved list has only six entries.
    expect(page.locator("#module-sm-5")).to_be_visible()
    expect(page.locator("#module-sm-6")).to_have_count(0)
    expect(page.locator(".module-row")).to_have_count(40)
    expect(page.locator("#module-count")).to_contain_text("3 unknown")


def test_module_ownership_does_not_remove_equipped_module(page: Page, static_server):
    load_knowledge_save(page)
    expect(page.locator('#module-wm-0 option[value="false"]')).to_be_disabled()
    expect(page.locator('#module-wm-2 option[value="false"]')).not_to_be_disabled()


def test_modules_follow_selected_slot_and_keep_changes_isolated(page: Page, static_server):
    load_knowledge_save(page)
    page.locator("#module-wm-2").select_option("true")
    for _ in range(3):
        page.locator("#slot-select").select_option("2")
        expect(page.locator("#module-wm-2")).to_have_value("false")
        expect(page.locator("#module-sm-6")).to_have_count(0)
        page.locator("#slot-select").select_option("1")
        expect(page.locator("#module-wm-2")).to_have_value("true")
    expect(page.locator("#save-count")).to_have_text("1 pending change")
    # Rebuilding panels must not retain detached inputs indefinitely.
    assert page.evaluate("[...inputsByLeaf.values()].every(bindings => [...bindings].every(b => b.el.isConnected))")


def test_pasha_uses_day_and_correct_travel_list(page: Page, static_server):
    load_knowledge_save(page, day=4)
    expect(page.locator("#run-summary")).to_have_text("Day 4 · 3 ship parts returned")
    cards = page.locator("#pasha-locations .quest-card")
    expect(cards.filter(has_text="hidden crashed pod")).to_have_class(re.compile("available"))
    # otherdata[71] is two, while miscworldstate[71] is zero. The former is
    # the travel flag used by the executable; they must not be confused.
    expect(cards.filter(has_text="Lupoto · by the Relic")).to_have_class(re.compile("available"))
    expect(cards.filter(has_text="right of the starting area")).not_to_have_class(re.compile("available"))
    expect(page.locator("#pasha-locations")).to_contain_text("Familiar completion flag is not set")


@pytest.mark.parametrize("day,location", [(2, "first room east of camp"), (3, "right of the starting area"), (5, "first room east of camp")])
def test_pasha_encounter_windows(page: Page, static_server, day, location):
    load_knowledge_save(page, day=day)
    cards = page.locator("#pasha-locations .quest-card")
    expect(cards.filter(has_text=location)).to_have_class(re.compile("available"))
    expect(cards.filter(has_text="hidden crashed pod")).not_to_have_class(re.compile("available"))


def test_raw_names_search_and_live_pasha_refresh(page: Page, static_server):
    load_knowledge_save(page)
    page.locator("#filter").fill("Scatterburst")
    expect(page.locator('#tree > details[data-key="wmacquired1"]')).to_be_visible()
    page.locator("#filter").fill("pashaprogress1")
    row = page.locator('#tree > details[data-key="pashaprogress1"]')
    row.locator("summary").click()
    field = row.locator('.tree-row').filter(has=page.locator('input[aria-label="[4]"]')).locator("input")
    field.fill("0")
    field.press("Tab")
    expect(page.locator("#changes-list")).to_contain_text("Camp after three parts")
    expect(page.locator(".quest-card").filter(has_text="hidden crashed pod")).not_to_have_class(re.compile("available"))


def test_missing_known_lists_do_not_prevent_generic_editing(page: Page, static_server, save_file):
    load_save(page, save_file)
    expect(page.locator("#module-count")).to_contain_text("40 unknown")
    expect(page.locator("#run-summary")).to_contain_text("unavailable")
    page.locator("#q-nanites-").fill("1000")
    page.locator("#q-nanites-").press("Tab")
    expect(page.locator("#save-count")).to_have_text("1 pending change")


def test_edits_after_download_restore_unsaved_state(page: Page, static_server):
    load_knowledge_save(page)
    page.locator("#module-wm-2").select_option("true")
    with page.expect_download():
        page.locator("#download-btn").click()
    assert page.evaluate("state.downloaded") is True
    page.locator("#module-sm-6").select_option("true")
    assert page.evaluate("state.downloaded") is False

# ─── Progress checker (read-only by default) ──────────────────────────────────

def progress_model(page):
    return page.evaluate("computeProgress(document.querySelector('#slot-select').value)")


def achievement(model, code):
    return next(x for x in model['achievements'] if x['id'] == code)


def completed_sources_except_beta():
    pickups = [0] * 105
    for i in [1, 6, 24, 67, 79]:
        pickups[i] = 1
    misc = [0] * 72
    misc[1] = 1
    stock = [1] * 21
    stock[9] = 0
    inventory = [0] * 69
    inventory[7] = 7
    for i in [1, 11, 12, 32, 33, 34, 35]:
        inventory[i] = 1
    return {'itempickupsvalue1': pickups, 'miscworldstate1': misc,
            'billstock1': stock, 'inventory1': inventory}


def test_checker_defaults_readonly_and_report_preserves_bytes(page: Page, static_server, save_file):
    load_save(page, save_file, readonly=True)
    expect(page.locator('#overview-panel')).to_be_visible()
    expect(page.locator('#quick-panel')).to_be_hidden()
    expect(page.locator('#enable-editing')).not_to_be_checked()
    page.locator('#navigation button[data-view="editor"]').click()
    expect(page.locator('#q-nanites-')).to_be_disabled()
    assert page.evaluate('changedLeaves().length') == 0
    assert page.evaluate('NRBF.bytesEqual(buildVerifiedFile().out, state.originalBytes)')
    page.locator('#navigation button[data-view="overview"]').click()
    with page.expect_download() as info:
        page.locator('#report-btn').click()
    import json
    report = json.loads(pathlib.Path(info.value.path()).read_text())
    assert report['slot'] == '1' and report['includesEdits'] is False
    assert len(report['achievements']) == 42
    assert len(report['npcs']) == 19
    assert len(report['godseeds']) == 5
    assert report['totals']['godseeds']['unknown'] == 19
    assert report['npcs'][0]['encounters'][0]['status'] == 'unknown'
    assert report['totals']['modules']['unknown'] == 40
    assert save_file.read_bytes() == build_save()


def test_core_source_identity_is_separate_from_inventory_target(page: Page, static_server):
    load_knowledge_save(page, readonly=True, progress=completed_sources_except_beta())
    model = progress_model(page)
    assert model['coreTotal'] == 7
    assert model['totals']['sources'] == {'owned': 7, 'missing': 1, 'unknown': 0, 'total': 8}
    assert [x['id'] for x in model['cores'] if x['owned'] is False] == ['beta-side']
    assert achievement(model, 'exp04')['status'] == 'met'
    page.locator('#navigation button[data-view="collectibles"]').click()
    page.locator('#core-missing').check()
    expect(page.locator('#core-list .collectible:visible')).to_have_count(1)
    expect(page.locator('#core-list .collectible:visible')).to_contain_text('branch to the left')
    expect(page.locator('#core-list .collectible:visible')).to_contain_text('rdb2b')
    expect(page.locator('#core-summary')).to_contain_text('inventory target met')


def test_current_build_targets_are_not_full_collection_counts(page: Page, static_server):
    data = completed_sources_except_beta()
    data.update({'wmacquired1': [True] * 19, 'mmacquired1': [True] * 18,
                 'smacquired1': [True] * 6 + [False, True, True]})
    data['inventory1'][26] = 1
    load_knowledge_save(page, readonly=True, progress=data)
    m = progress_model(page)
    assert m['totals']['modules']['owned'] == 39
    assert m['totals']['weapons']['owned'] == 8
    assert achievement(m, 'exp01')['status'] == 'met'
    assert achievement(m, 'exp02')['status'] == 'met'
    assert achievement(m, 'exp04')['status'] == 'met'
    assert [x['name'] for x in m['modules'] if x['owned'] is False] == ['Frenzied Shell']
    assert [x['name'] for x in m['weapons'] if x['owned'] is False] == ['Kinzy Axe']
    assert len(m['achievements']) == 42
    assert len({x['id'] for x in m['achievements']}) == 42
    assert all(x['guide'] for x in m['achievements'])
    assert all(len(x['where']) > 25 and x['route'][2] for x in m['modules'])


def test_shared_unlock_is_not_selected_slot_completion(page: Page, static_server):
    recorded = [1] * 42
    load_knowledge_save(page, readonly=True, progress={'achievementslist': recorded})
    page.locator('#slot-select').select_option('2')
    m = progress_model(page)
    assert all(x['recorded'] for x in m['achievements'])
    assert achievement(m, 'com01')['status'] == 'unknown'
    assert achievement(m, 'exp01')['status'] == 'unknown'
    assert achievement(m, 'npc01')['status'] == 'unknown'
    assert m['totals']['weapons']['unknown'] == 9
    assert m['totals']['sources']['unknown'] == 8
    assert m['totals']['modules']['owned'] == 0
    page.locator('#navigation button[data-view="achievements"]').click()
    row = page.locator('.achievement[data-id="com01"]')
    expect(row).to_contain_text('Unlock recorded · shared')
    expect(row).to_contain_text('Unknown')


def test_unavailable_counters_and_spare_list_capacity_are_unknown(page: Page, static_server):
    load_knowledge_save(page, readonly=True, short_suit_list=True)
    m = progress_model(page)
    assert m['totals']['modules']['unknown'] == 3
    assert all(x['owned'] is None for x in m['modules'] if x['group'] == 'sm' and x['index'] >= 6)
    assert achievement(m, 'com02')['count'] is None
    assert achievement(m, 'com02')['status'] == 'unknown'
    assert achievement(m, 'exp04')['count'] is None
    assert achievement(m, 'exp04')['status'] == 'unknown'


@pytest.mark.parametrize('stock,expected', [(-1, None), (0, True), (1, False), (2, None)])
def test_bill_core_stock_has_specific_semantics(page: Page, static_server, stock, expected):
    data = [1] * 21
    data[9] = stock
    load_knowledge_save(page, readonly=True, progress={'billstock1': data})
    assert next(x for x in progress_model(page)['cores'] if x['id'] == 'bill')['owned'] is expected


def test_native_achievement_thresholds_and_session_goals(page: Page, static_server):
    other = [0] * 72
    other[36] = 11
    # A set flag in unused bbicons[4] cannot substitute for a friendly bot.
    bots = [1, 1, 1, 1, 1, 1, 0]
    saymund = [0, 2, 2, 2, 2, 2, 2, 2, 0]
    load_knowledge_save(page, readonly=True, progress={'enemieskilled1': 999, 'timeshealed1': 99,
        'socketsmax1': 29, 'otherdata1': other, 'bbicons1': bots, 'saymundprogress1': saymund})
    m = progress_model(page)
    for code, count, target in [('com01',999,1000),('com02',99,100),('misc05',29,30),('misc03',11,12),('exp03',5,6),('npc03',7,8)]:
        a = achievement(m, code)
        assert a['status'] == 'progress' and a['count'] == count and a['target'] == target
    for code in ['com03','misc01','misc06','misc07']:
        a = achievement(m, code)
        assert a['status'] == 'unknown' and a['count'] is None
    page.locator('#navigation button[data-view="achievements"]').click()
    page.locator('#achievement-search').fill('Roslock')
    expect(page.locator('.achievement[data-id="com03"]')).to_be_visible()
    page.locator('#achievement-search').fill('')
    page.locator('#achievement-status').select_option('unknown')
    expect(page.locator('.achievement[data-id="com01"]')).to_be_hidden()
    expect(page.locator('.achievement[data-id="com03"]')).to_be_visible()


@pytest.mark.parametrize('finished,expected', [(False,'progress'),(True,'met')])
def test_ending_required_for_run_achievements(page: Page, static_server, finished, expected):
    inventory = [0] * 69
    inventory[7] = 9
    load_knowledge_save(page, readonly=True, progress={'finishedgame1':finished, 'difficulty1':1,
        'timesdied1':0, 'timeplayed1':10800, 'newgameplus1':1, 'inventory1':inventory,
        'itempickupsvalue1':[0] * 105, 'billstock1':[1] * 21})
    m = progress_model(page)
    for code in ['misc02','misc04','misc08']:
        assert achievement(m, code)['status'] == expected
    # NG+ core totals must never fabricate collection of this world's sources.
    assert m['totals']['sources']['owned'] == 0
    assert m['totals']['sources']['missing'] == 8
    assert achievement(m, 'exp04')['status'] == 'met'


def test_run_failures_are_explicit_not_achievement_history(page: Page, static_server):
    load_knowledge_save(page, readonly=True, progress={'finishedgame1':False, 'difficulty1':0,
        'timesdied1':1, 'timeplayed1':10801, 'achievementslist':[1] * 42})
    m = progress_model(page)
    for code in ['misc02','misc04','misc08']:
        a = achievement(m, code)
        assert a['status'] == 'blocked' and a['recorded'] is True


def test_readonly_toggle_preserves_pending_edits_and_relocks_controls(page: Page, static_server):
    original = load_knowledge_save(page)
    page.locator('#module-sm-6').select_option('true')
    expect(page.locator('#working-note')).to_be_visible()
    page.locator('#enable-editing').uncheck()
    expect(page.locator('#q-nanites-')).to_be_disabled()
    expect(page.locator('#module-sm-6')).to_be_disabled()
    assert progress_model(page)['modules'][-3]['owned'] is True
    assert page.evaluate('changedLeaves().length') == 1
    with page.expect_download() as info:
        page.locator('#backup-btn').click()
    assert pathlib.Path(info.value.path()).read_bytes() == original
    page.locator('#reset-all-btn').click()
    expect(page.locator('#working-note')).to_be_hidden()
    assert page.evaluate('NRBF.bytesEqual(buildVerifiedFile().out, state.originalBytes)')

@pytest.mark.parametrize('molly_progress,expected', [(2,'progress'),(3,'met')])
def test_good_friends_uses_native_crew_requirements(page: Page, static_server, molly_progress, expected):
    bill, pasha, raven, molly = ([0] * 12 for _ in range(4))
    bill[5], pasha[9], raven[4], molly[5] = 2, 2, 2, molly_progress
    inventory = [0] * 69
    inventory[46] = 1
    load_knowledge_save(page, readonly=True, progress={'billprogress1':bill,'pashaprogress1':pasha,
        'ravenprogress1':raven,'mollyprogress1':molly,'inventory1':inventory})
    goal = achievement(progress_model(page), 'npc05')
    assert goal['status'] == expected
    assert goal['count'] == (5 if molly_progress == 3 else 4)
    assert any('Molly’s horse' in line for line in goal['evidence'])


def test_counter_thresholds_and_boss_indices_at_completion(page: Page, static_server):
    other = [0] * 72
    other[36] = 12
    miniboss = [0] * 20
    miniboss[16] = 1  # Fome cannot substitute for Vek at 17.
    miniboss[3] = 1
    load_knowledge_save(page, readonly=True, progress={'enemieskilled1':1000,'timeshealed1':100,
        'socketsmax1':30,'otherdata1':other,'bbicons1':[1,1,1,1,0,1,1],
        'saymundprogress1':[0]+[2]*8,'minibossvalue1':miniboss})
    m = progress_model(page)
    for code in ['com01','com02','misc05','misc03','exp03','npc03','en07']:
        assert achievement(m, code)['status'] == 'met'
    assert achievement(m, 'en08')['status'] == 'progress'
    axe = next(x for x in m['weapons'] if x['index'] == 68)
    assert axe['region'] == 'Toler-Under-Foot'
    assert 'Huttle Drop' in axe['where'] and 'ed3 → ed6 → ed7 → ed8' in axe['evidence']

# ─── NPC conversation checker ────────────────────────────────────────────────

def npc_model(page, npc_id):
    return next(npc for npc in progress_model(page)['npcs'] if npc['id'] == npc_id)


def npc_entry(page, npc_id, index):
    return next(e for e in npc_model(page, npc_id)['encounters'] if e['index'] == index)


def test_npc_tab_replaces_pasha_and_keeps_nested_guidance(page: Page, static_server):
    load_knowledge_save(page, readonly=True)
    expect(page.locator('#navigation button[data-view="pasha"]')).to_have_count(0)
    page.locator('#navigation button[data-view="npcs"]').click()
    expect(page.locator('#npcs-panel')).to_be_visible()
    expect(page.locator('.npc-card')).to_have_count(19)
    expect(page.locator('#npc-count')).to_contain_text('19 characters')
    pasha = page.locator('.npc-card[data-npc="pasha"]')
    pasha.locator('> summary').click()
    expect(pasha.locator('#pasha-panel')).to_be_visible()
    expect(pasha.locator('#pasha-locations')).to_contain_text('hidden crashed pod')
    expect(page.locator('#npc-run-summary')).to_contain_text('3 ship parts returned')
    assert page.evaluate('changedLeaves().length') == 0
    assert page.evaluate('NRBF.bytesEqual(buildVerifiedFile().out,state.originalBytes)')


def test_npc_main_dialogue_excludes_approach_and_ambient(page: Page, static_server):
    load_knowledge_save(page, readonly=True, progress={'billprogress1':[0,2,1,0,2,2,1]})
    bill = npc_model(page, 'bill')
    assert bill['totals']['covered'] == 2
    assert bill['totals']['total'] == 6
    first = npc_entry(page, 'bill', 1)
    assert first['status'] == 'covered' and first['covered'] == first['main'] == 1
    second = npc_entry(page, 'bill', 2)
    assert second['status'] == 'progress' and second['covered'] == 0 and second['main'] == 2
    # Final camp entry has no approach; its one main conversation is covered at 1.
    assert npc_entry(page, 'bill', 6)['status'] == 'covered'
    assert npc_entry(page, 'bill', 3)['status'] == 'unrecorded'
    assert npc_entry(page, 'bill', 4)['covered'] == 1
    page.locator('#navigation button[data-view="npcs"]').click()
    page.locator('#npc-search').fill('Bill')
    expect(page.locator('.npc-card:visible')).to_have_count(1)
    page.locator('.npc-card[data-npc="bill"] > summary').click()
    page.locator('#npc-needs-dialogue').check()
    expect(page.locator('.npc-card[data-npc="bill"] .npc-encounter:visible')).to_have_count(4)
    expect(page.locator('.npc-card[data-npc="bill"] .npc-encounter[data-index="1"]')).to_be_hidden()


def test_shared_rime_array_is_split_by_character(page: Page, static_server):
    load_knowledge_save(page, readonly=True, progress={'rimeprogress1':[0,5,1,2,0,4,4,3]})
    expected = {'rime':[1], 'hector':[2], 'outlier':[3,4], 'scientist':[5], 'slovenmuck':[6], 'relic':[7]}
    for name, indices in expected.items():
        assert [e['index'] for e in npc_model(page, name)['encounters']] == indices
    assert npc_entry(page, 'rime', 1)['status'] == 'covered'
    assert npc_entry(page, 'slovenmuck', 6)['status'] == 'covered'
    assert npc_entry(page, 'relic', 7)['status'] == 'progress'
    assert npc_entry(page, 'relic', 7)['covered'] == 2
    assert npc_entry(page, 'hector', 2)['covered'] == 0
    page.locator('#navigation button[data-view="editor"]').click()
    page.locator('#filter').fill('Slovenmuck')
    expect(page.locator('#tree > details[data-key="rimeprogress1"]')).to_be_visible()


def test_pasha_pod_and_starting_area_indices_match_assets(page: Page, static_server):
    values = [0] * 15
    values[9], values[10] = 5, 1
    load_knowledge_save(page, readonly=True, progress={'pashaprogress1':values})
    pod, surface = npc_entry(page, 'pasha', 9), npc_entry(page, 'pasha', 10)
    assert pod['label'] == 'Hidden crashed pod' and pod['status'] == 'covered'
    assert surface['label'] == 'Near the starting area' and surface['status'] == 'progress'
    assert surface['covered'] == 0
    assert npc_entry(page, 'pasha', 13)['location'] == 'Crash Site'
    assert npc_entry(page, 'pasha', 14)['location'].startswith('Stoffbloom')


@pytest.mark.parametrize('value,expected', [(1,'variant'),(2,'variant'),(4,'covered')])
def test_shared_branch_counter_does_not_invent_a_dialogue_percentage(page: Page, static_server, value, expected):
    load_knowledge_save(page, readonly=True, progress={'luaprogress1':[0,0,0,value,0,0,0]})
    entry = npc_entry(page, 'lua', 3)
    assert entry['status'] == expected
    assert entry['main'] is None and entry['covered'] is None
    page.locator('#navigation button[data-view="npcs"]').click()
    page.locator('.npc-card[data-npc="lua"] > summary').click()
    expect(page.locator('.npc-card[data-npc="lua"] .npc-encounter[data-index="3"] progress')).to_have_count(0)


def test_npc_missing_fields_and_slots_remain_unknown(page: Page, static_server):
    load_knowledge_save(page, readonly=True, progress={'billprogress1':[0,2,3,3,4,3,1], 'achievementslist':[1]*42})
    assert npc_model(page, 'bill')['totals']['covered'] == 6
    assert npc_model(page, 'charley')['encounters'] == []
    assert npc_model(page, 'charley')['hasData'] is False
    page.locator('#slot-select').select_option('2')
    for npc in progress_model(page)['npcs']:
        assert npc['totals']['covered'] == 0
        assert all(e['status'] == 'unknown' and e['value'] is None for e in npc['encounters'])
    assert len(progress_model(page)['npcs']) == 19


def test_unknown_positive_encounter_is_preserved_without_a_completion_guess(page: Page, static_server):
    values = [0] * 11
    values[10] = 23
    load_knowledge_save(page, readonly=True, progress={'billprogress1':values})
    extra = npc_entry(page, 'bill', 10)
    assert extra['status'] == 'unknown' and extra['value'] == 23
    assert extra['target'] is None and extra['covered'] is None
    assert extra['label'] == 'Other saved encounter 10'


def test_npc_progress_refreshes_with_edits_and_reverts(page: Page, static_server):
    original = load_knowledge_save(page, progress={'billprogress1':[0,2,1,0,2,2,1]})
    bill_card = page.locator('.npc-card[data-npc="bill"]')
    bill_card.locator('> summary').click()
    page.locator('#filter').fill('billprogress1')
    tree = page.locator('#tree > details[data-key="billprogress1"]')
    tree.locator('> summary').click()
    field = tree.locator('input[aria-label="[2]"]')
    field.fill('3'); field.press('Tab')
    assert npc_entry(page, 'bill', 2)['status'] == 'covered'
    assert bill_card.get_attribute('open') is not None
    expect(page.locator('#changes-list')).to_contain_text('Bill · Camp conversation 2')
    with page.expect_download() as info:
        page.locator('#download-btn').click()
    edited = pathlib.Path(info.value.path()).read_bytes()
    assert len(edited) == len(original)
    assert [(a,b) for a,b in zip(original,edited) if a != b] == [(1,3)]
    page.locator('#reset-all-btn').click()
    assert npc_entry(page, 'bill', 2)['status'] == 'progress'
    assert page.evaluate('NRBF.bytesEqual(buildVerifiedFile().out,state.originalBytes)')


def test_npc_counters_use_list_size_not_backing_capacity(page: Page, static_server):
    values = [0,2] + [0]*7 + [99]
    load_knowledge_save(page, readonly=True, progress={'billprogress1':values}, progress_sizes={'billprogress1':2})
    bill = npc_model(page, 'bill')
    assert bill['totals']['covered'] == 1 and bill['totals']['unknown'] == 5
    assert npc_entry(page, 'bill', 1)['status'] == 'covered'
    assert npc_entry(page, 'bill', 2)['value'] is None
    assert all(e['index'] != 9 for e in bill['encounters'])

# ─── Godseed source checklist ────────────────────────────────────────────────

def seed_type(page, type_id):
    return next(t for t in progress_model(page)['godseeds'] if t['id'] == type_id)


def all_seed_sources():
    values = [0] * 105
    for i in [8,20,19,29,54,14,17,25,52,62,3,11,16,21,33,77,89]:
        values[i] = 1
    stock = [1] * 21
    stock[1] = 0
    misc = [0] * 72
    misc[43] = 2
    return {'itempickupsvalue1':values,'billstock1':stock,'miscworldstate1':misc}


def test_all_godseed_types_and_current_scene_sources(page: Page, static_server):
    load_knowledge_save(page, readonly=True)
    m = progress_model(page)
    assert [(t['id'],t['index'],t['totals']['total']) for t in m['godseeds']] == [
        ('red',14,5),('orange',15,5),('violet',16,6),('green',31,2),('malformed',53,1)]
    assert len(m['godseedSources']) == 19
    assert len({s['id'] for s in m['godseedSources']}) == 19
    pickup_ids = {s['index'] for s in m['godseedSources'] if s['key']=='itempickupsvalue'}
    assert pickup_ids == {8,20,19,29,54,14,17,25,52,62,3,11,16,21,33,77,89}
    # The old worlddata annotation at index 12 has no current scene pickup.
    assert 12 not in pickup_ids
    assert all(s['where'] and s['scene'] for s in m['godseedSources'])
    assert 'Vigor' in seed_type(page,'red')['effect']
    assert 'GunPower' in seed_type(page,'orange')['effect']
    assert 'Resolve' in seed_type(page,'violet')['effect']
    assert 'Luck' in seed_type(page,'green')['effect']
    page.locator('#navigation button[data-view="collectibles"]').click()
    expect(page.locator('#godseeds-panel')).to_be_visible()
    expect(page.locator('#godseed-list .collectible')).to_have_count(19)
    assert page.evaluate('changedLeaves().length') == 0


def test_absorbed_godseeds_stay_collected_with_empty_inventory(page: Page, static_server):
    data = all_seed_sources()
    data['inventory1'] = [0] * 69
    load_knowledge_save(page, readonly=True, progress=data)
    m = progress_model(page)
    assert m['totals']['godseeds'] == {'owned':19,'missing':0,'unknown':0,'total':19}
    assert all(t['inventoryCount']==0 for t in m['godseeds'])
    assert all(s['owned'] is True for s in m['godseedSources'])
    page.locator('#navigation button[data-view="collectibles"]').click()
    page.locator('#godseed-missing').check()
    expect(page.locator('#godseed-list .collectible:visible')).to_have_count(0)
    expect(page.locator('#godseed-empty')).to_be_visible()
    expect(page.locator('#progress-summary')).to_contain_text('Godseed sources collected')
    assert page.evaluate('NRBF.bytesEqual(buildVerifiedFile().out,state.originalBytes)')


def test_godseed_inventory_does_not_fabricate_world_collection(page: Page, static_server):
    inventory = [0] * 69
    for i in [14,15,16,31,53]:inventory[i]=3
    load_knowledge_save(page, readonly=True, progress={'inventory1':inventory,'itempickupsvalue1':[0]*105,
        'billstock1':[1]*21,'miscworldstate1':[0]*72,'newgameplus1':1})
    m = progress_model(page)
    assert m['totals']['godseeds']['owned'] == 0
    assert m['totals']['godseeds']['missing'] == 19
    assert all(t['inventoryCount']==3 for t in m['godseeds'])


@pytest.mark.parametrize('gift,expected,ready', [(0,False,False),(1,False,True),(2,True,False),(3,None,False)])
def test_malformed_gift_ready_is_not_received(page: Page, static_server, gift, expected, ready):
    misc = [0] * 72;misc[43]=gift
    load_knowledge_save(page, readonly=True, progress={'miscworldstate1':misc})
    source = seed_type(page,'malformed')['sources'][0]
    assert source['owned'] is expected and source['giftReady'] is ready
    assert source['index'] == 43 and source['key'] == 'miscworldstate'
    if ready:
        page.locator('#navigation button[data-view="collectibles"]').click()
        expect(page.locator('#godseed-list [data-id="malformed-gambler"]')).to_contain_text('Gift ready')


@pytest.mark.parametrize('stock,expected', [(-1,None),(0,True),(1,False),(2,None)])
def test_green_godseed_shop_stock_semantics(page: Page, static_server, stock, expected):
    values = [1]*21;values[1]=stock
    load_knowledge_save(page, readonly=True, progress={'billstock1':values})
    source=next(s for s in seed_type(page,'green')['sources'] if s['id']=='green-bill')
    assert source['owned'] is expected
    assert '8,000' in source['where'] and 'three ship parts' in source['where']


def test_godseed_location_filters_and_separate_loose_seed_counts(page: Page, static_server):
    data=all_seed_sources();data['itempickupsvalue1'][11]=0
    data['seedsinbotroom1']={'GunPower':2,'Vigor':3,'Volatility':4}
    load_knowledge_save(page, readonly=True, progress=data)
    assert seed_type(page,'orange')['pendingCount']==2
    assert seed_type(page,'red')['pendingCount']==3
    assert seed_type(page,'violet')['pendingCount']==4
    assert seed_type(page,'green')['pendingCount'] is None
    assert progress_model(page)['totals']['godseeds']['owned']==18
    page.locator('#navigation button[data-view="collectibles"]').click()
    page.locator('#godseed-type').select_option('violet')
    page.locator('#godseed-missing').check()
    expect(page.locator('#godseed-list .collectible:visible')).to_have_count(1)
    expect(page.locator('#godseed-list .collectible:visible')).to_contain_text('Huttle Drop')
    page.locator('#godseed-search').fill('purple')
    expect(page.locator('#godseed-list .collectible:visible')).to_have_count(1)
    page.locator('#godseed-search').fill('Sap-Stone')
    expect(page.locator('#godseed-empty')).to_be_visible()


def test_godseed_missing_fields_list_size_and_other_slots_are_unknown(page: Page, static_server):
    pickups = [0] * 105;pickups[3]=pickups[89]=1
    load_knowledge_save(page, readonly=True, progress={'itempickupsvalue1':pickups,'miscworldstate1':None}, progress_sizes={'itempickupsvalue1':4})
    m=progress_model(page)
    assert m['totals']['godseeds']['owned']==1
    assert m['totals']['godseeds']['unknown']==18  # positive capacity at 89 must be ignored
    assert all(t['inventoryCount'] is None and t['pendingCount'] is None for t in m['godseeds'])
    page.locator('#slot-select').select_option('2')
    m=progress_model(page)
    assert m['totals']['godseeds']=={'owned':0,'missing':0,'unknown':19,'total':19}
    assert all(t['inventoryCount'] is None for t in m['godseeds'])


def test_godseed_pickup_edits_refresh_counts_and_revert_without_other_changes(page: Page, static_server):
    original=load_knowledge_save(page, progress={'itempickupsvalue1':[0]*105})
    page.locator('#filter').fill('itempickupsvalue1')
    tree=page.locator('#tree > details[data-key="itempickupsvalue1"]');tree.locator('> summary').click()
    field=tree.locator('input[aria-label="[54]"]');field.fill('1');field.press('Tab')
    assert next(s for s in seed_type(page,'red')['sources'] if s['index']==54)['owned'] is True
    expect(page.locator('#changes-list')).to_contain_text('Red Godseed')
    with page.expect_download() as info:page.locator('#download-btn').click()
    edited=pathlib.Path(info.value.path()).read_bytes()
    assert len(edited)==len(original)
    assert [(a,b) for a,b in zip(original,edited) if a!=b]==[(0,1)]
    page.locator('#reset-all-btn').click()
    assert next(s for s in seed_type(page,'red')['sources'] if s['index']==54)['owned'] is False
    assert page.evaluate('NRBF.bytesEqual(buildVerifiedFile().out,state.originalBytes)')
