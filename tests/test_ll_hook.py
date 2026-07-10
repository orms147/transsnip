"""HookState — pure decision logic of the WH_KEYBOARD_LL callback.

The Win32 plumbing (SetWindowsHookEx, message loop, watchdog) can't run
under pytest without swallowing real keystrokes, so the callback's decision
table lives in `HookState` and is exercised here: RegisterHotKey-equivalent
semantics (exact modifier match, fire-once-per-hold) plus the swallow rules
that keep games from seeing the combo.
"""
from transsnip.hotkeys.ll_hook import MOD_ALT, MOD_CONTROL, HookState
from transsnip.hotkeys.manager import HotkeyManager

VK_T = 0x54
VK_S = 0x53
VK_A = 0x41

T0 = 100.0        # arbitrary monotonic base for tests
TICK = 0.03       # OS auto-repeat period is a few dozen ms


def make_state() -> HookState:
    s = HookState()
    s.set_combos({
        (MOD_ALT, VK_T): "region_translate",
        (MOD_CONTROL | MOD_ALT, VK_S): "open_settings",
    })
    return s


def _mods(value: int):
    return lambda: value


def _never():
    raise AssertionError("modifier snapshot taken for a non-trigger key")


def test_match_fires_and_swallows():
    s = make_state()
    assert s.on_key(VK_T, True, _mods(MOD_ALT), T0) == ("region_translate", True)


def test_exact_modifier_match_required():
    # Ctrl+Alt+T must NOT fire the Alt+T binding (RegisterHotKey semantics).
    s = make_state()
    assert s.on_key(VK_T, True, _mods(MOD_CONTROL | MOD_ALT), T0) == (None, False)
    # Bare T (no modifiers) passes through to the focused app.
    assert s.on_key(VK_T, True, _mods(0), T0) == (None, False)


def test_multi_modifier_combo():
    s = make_state()
    assert s.on_key(VK_S, True, _mods(MOD_CONTROL | MOD_ALT), T0) == ("open_settings", True)


def test_autorepeat_swallowed_but_fires_once():
    s = make_state()
    assert s.on_key(VK_T, True, _mods(MOD_ALT), T0) == ("region_translate", True)
    # OS auto-repeat while held: swallowed (game must not see a stream of
    # T's) but the action does not re-fire.
    assert s.on_key(VK_T, True, _mods(MOD_ALT), T0 + TICK) == (None, True)
    assert s.on_key(VK_T, True, _mods(MOD_ALT), T0 + 2 * TICK) == (None, True)


def test_keyup_rearms():
    s = make_state()
    s.on_key(VK_T, True, _mods(MOD_ALT), T0)
    assert s.on_key(VK_T, False, _mods(MOD_ALT), T0 + TICK) == (None, False)  # keyup passes
    assert s.on_key(VK_T, True, _mods(MOD_ALT), T0 + 2 * TICK) == ("region_translate", True)


def test_modifier_released_mid_hold_passes_through_and_rearms():
    s = make_state()
    s.on_key(VK_T, True, _mods(MOD_ALT), T0)
    # User lets go of Alt while still holding T: repeats no longer match, so
    # they reach the app, and the combo is re-armed.
    assert s.on_key(VK_T, True, _mods(0), T0 + TICK) == (None, False)
    assert s.on_key(VK_T, True, _mods(MOD_ALT), T0 + 2 * TICK) == ("region_translate", True)


def test_stale_held_entry_fires_as_fresh_press():
    # Windows silently removed the hook while the key was held, so the keyup
    # was never seen — _held goes stale. The next press (long after any
    # auto-repeat train) must FIRE, not vanish into a swallowed no-op.
    s = make_state()
    s.on_key(VK_T, True, _mods(MOD_ALT), T0)
    late = T0 + HookState.HELD_STALE_S + 1.0
    assert s.on_key(VK_T, True, _mods(MOD_ALT), late) == ("region_translate", True)
    # And the repeat train after it is guarded again.
    assert s.on_key(VK_T, True, _mods(MOD_ALT), late + TICK) == (None, True)


def test_non_trigger_key_skips_modifier_snapshot():
    # The fast path must bail on the vk check alone — `_never` raising proves
    # the (more expensive) GetAsyncKeyState snapshot isn't taken per keystroke.
    s = make_state()
    assert s.on_key(VK_A, True, _never, T0) == (None, False)
    assert s.on_key(VK_A, False, _never, T0) == (None, False)


def test_set_combos_keeps_held_for_still_bound_combos():
    # A settings re-apply while the user holds a combo must NOT re-arm it —
    # the next OS auto-repeat would fire a second action from one press.
    s = make_state()
    s.on_key(VK_T, True, _mods(MOD_ALT), T0)
    s.set_combos({(MOD_ALT, VK_T): "region_translate"})
    assert s.on_key(VK_T, True, _mods(MOD_ALT), T0 + TICK) == (None, True)


def test_set_combos_drops_held_for_removed_combos():
    s = make_state()
    s.on_key(VK_T, True, _mods(MOD_ALT), T0)
    s.set_combos({(MOD_CONTROL | MOD_ALT, VK_S): "open_settings"})  # T unbound
    # Rebind T: it starts re-armed (no stale held entry survives).
    s.set_combos({(MOD_ALT, VK_T): "region_translate"})
    assert s.on_key(VK_T, True, _mods(MOD_ALT), T0 + TICK) == ("region_translate", True)


def test_empty_combos_ignores_everything():
    s = HookState()
    s.set_combos({})
    assert s.on_key(VK_T, True, _never, T0) == (None, False)


def test_sync_physical_seeds_held_keys():
    # Hook resurrected mid-hold of a combo the WM_HOTKEY fallback already
    # fired: the next auto-repeat must NOT fire again (Alt+F would toggle
    # the overlay straight back off).
    s = make_state()
    s.sync_physical(lambda vk: vk == VK_T, T0)
    assert s.on_key(VK_T, True, _mods(MOD_ALT), T0 + TICK) == (None, True)
    # Keyup re-arms as usual.
    s.on_key(VK_T, False, _mods(MOD_ALT), T0 + 2 * TICK)
    assert s.on_key(VK_T, True, _mods(MOD_ALT), T0 + 3 * TICK) == ("region_translate", True)


def test_sync_physical_rearms_released_keys():
    # The hook died between a fired keydown and its keyup: the stale held
    # entry would swallow the user's next press into nothing — sync against
    # the physical keyboard (key is UP) must re-arm it.
    s = make_state()
    s.on_key(VK_T, True, _mods(MOD_ALT), T0)
    s.sync_physical(lambda _vk: False, T0 + 1.0)
    assert s.on_key(VK_T, True, _mods(MOD_ALT), T0 + 1.1) == ("region_translate", True)


def test_manager_hook_combos_first_wins():
    # RegisterHotKey gives a duplicated combo to the FIRST action that bound
    # it; the hook table must agree or the same keystroke would fire
    # different actions depending on which backend handles it.
    m = HotkeyManager()
    m._wanted = {
        "region_translate": (MOD_ALT, VK_T),
        "fullscreen_translate": (MOD_ALT, VK_T),  # duplicate loser
        "open_settings": (MOD_CONTROL | MOD_ALT, VK_S),
    }
    assert m._hook_combos() == {
        (MOD_ALT, VK_T): "region_translate",
        (MOD_CONTROL | MOD_ALT, VK_S): "open_settings",
    }
