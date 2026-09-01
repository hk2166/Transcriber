"""One-click system-audio routing — no manual Audio MIDI Setup.

BlackHole only hears what macOS routes through it, and macOS silently flips
the default output to Bluetooth headphones whenever they connect — so
"BlackHole installed" ≠ "BlackHole receiving audio", and every headphone user
records silent system audio without noticing.

This module automates the fix natively (same CoreAudio ctypes approach as
meeting_detect): create a *stacked* aggregate device — a Multi-Output — that
plays to the user's real output (their buds/speakers, as the clock master)
AND to BlackHole (drift-corrected), then make it the system default output.
No shell-outs, no extra tools, no permission prompts: aggregate management is
plain user-space CoreAudio.

``enable()`` pairs BlackHole with *whatever* the current output is, so any
device sets up automatically; ``disable()`` restores the real device and
removes the aggregate. Known trade-off of every Multi-Output device: the
volume keys stop working while routed (adjust volume in the meeting app).
"""

from __future__ import annotations

import ctypes
import logging

logger = logging.getLogger(__name__)

__all__ = ["RoutingError", "disable", "enable", "status"]

_CORE_AUDIO = "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
_CORE_FOUNDATION = (
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
)
_SYSTEM_OBJECT = 1  # kAudioObjectSystemObject
_UTF8 = 0x08000100  # kCFStringEncodingUTF8
_SINT32 = 3  # kCFNumberSInt32Type

#: Our aggregate's stable identity — recreated/destroyed by UID.
AGGREGATE_UID = "com.hemant.confab.systemaudio"


class RoutingError(RuntimeError):
    """A routing step failed in a way the user must hear about."""


class _PropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


def _fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


def _addr(selector: str) -> _PropertyAddress:
    return _PropertyAddress(_fourcc(selector), _fourcc("glob"), 0)


def _load():
    ca = ctypes.CDLL(_CORE_AUDIO)
    cf = ctypes.CDLL(_CORE_FOUNDATION)
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32,
    ]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32,
    ]
    cf.CFDictionaryCreateMutable.restype = ctypes.c_void_p
    cf.CFDictionaryCreateMutable.argtypes = [
        ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p,
    ]
    cf.CFDictionarySetValue.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    cf.CFArrayCreateMutable.restype = ctypes.c_void_p
    cf.CFArrayCreateMutable.argtypes = [
        ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p,
    ]
    cf.CFArrayAppendValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    cf.CFNumberCreate.restype = ctypes.c_void_p
    cf.CFNumberCreate.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p]
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    ca.AudioObjectGetPropertyData.restype = ctypes.c_int32
    ca.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
    ca.AudioObjectSetPropertyData.restype = ctypes.c_int32
    ca.AudioHardwareCreateAggregateDevice.restype = ctypes.c_int32
    ca.AudioHardwareCreateAggregateDevice.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
    ]
    ca.AudioHardwareDestroyAggregateDevice.restype = ctypes.c_int32
    ca.AudioHardwareDestroyAggregateDevice.argtypes = [ctypes.c_uint32]
    return ca, cf


def _cfstr(cf, text: str):
    return cf.CFStringCreateWithCString(None, text.encode(), _UTF8)


def _read_cfstr(cf, ref) -> str | None:
    if not ref:
        return None
    buf = ctypes.create_string_buffer(512)
    if cf.CFStringGetCString(ref, buf, len(buf), _UTF8):
        return buf.value.decode(errors="replace")
    return None


def _device_string(ca, cf, device_id: int, selector: str) -> str | None:
    ref = ctypes.c_void_p(0)
    size = ctypes.c_uint32(ctypes.sizeof(ref))
    address = _addr(selector)
    status = ca.AudioObjectGetPropertyData(
        device_id, ctypes.byref(address), 0, None,
        ctypes.byref(size), ctypes.byref(ref),
    )
    if status != 0:
        return None
    value = _read_cfstr(cf, ref)
    if ref:
        cf.CFRelease(ref)
    return value


def _all_devices(ca, cf) -> list[dict]:
    size = ctypes.c_uint32(0)
    address = _addr("dev#")  # kAudioHardwarePropertyDevices
    if ca.AudioObjectGetPropertyDataSize(
        _SYSTEM_OBJECT, ctypes.byref(address), 0, None, ctypes.byref(size)
    ) != 0:
        return []
    count = size.value // 4
    ids = (ctypes.c_uint32 * count)()
    if ca.AudioObjectGetPropertyData(
        _SYSTEM_OBJECT, ctypes.byref(address), 0, None,
        ctypes.byref(size), ids,
    ) != 0:
        return []
    return [
        {
            "id": device_id,
            "uid": _device_string(ca, cf, device_id, "uid "),
            "name": _device_string(ca, cf, device_id, "lnam"),
        }
        for device_id in ids
    ]


def _default_output(ca) -> int:
    device = ctypes.c_uint32(0)
    size = ctypes.c_uint32(ctypes.sizeof(device))
    address = _addr("dOut")  # kAudioHardwarePropertyDefaultOutputDevice
    ca.AudioObjectGetPropertyData(
        _SYSTEM_OBJECT, ctypes.byref(address), 0, None,
        ctypes.byref(size), ctypes.byref(device),
    )
    return device.value


def _set_default_output(ca, device_id: int) -> None:
    device = ctypes.c_uint32(device_id)
    address = _addr("dOut")
    status = ca.AudioObjectSetPropertyData(
        _SYSTEM_OBJECT, ctypes.byref(address), 0, None,
        ctypes.sizeof(device), ctypes.byref(device),
    )
    if status != 0:
        raise RoutingError(f"Couldn't switch the output device (OSStatus {status}).")


def _sub_device_uids(ca, cf, device_id: int) -> list[str]:
    """An aggregate's sub-device UIDs; [] for a plain device."""
    ref = ctypes.c_void_p(0)
    size = ctypes.c_uint32(ctypes.sizeof(ref))
    address = _addr("grup")  # kAudioAggregateDevicePropertyFullSubDeviceList
    if ca.AudioObjectGetPropertyData(
        device_id, ctypes.byref(address), 0, None,
        ctypes.byref(size), ctypes.byref(ref),
    ) != 0 or not ref:
        return []
    uids = []
    for index in range(cf.CFArrayGetCount(ref)):
        uid = _read_cfstr(cf, cf.CFArrayGetValueAtIndex(ref, index))
        if uid:
            uids.append(uid)
    cf.CFRelease(ref)
    return uids


def pick_real_device(
    default_uid: str | None, devices: list[dict]
) -> dict | None:
    """The physical output to pair with BlackHole (pure — unit-tested).

    Usually just the current default; but when the default is BlackHole
    itself or our own aggregate, there's no real device to inherit — the
    caller must ask the user to pick their speakers first.
    """
    for device in devices:
        if device.get("uid") == default_uid:
            name = (device.get("name") or "").lower()
            if device.get("uid") == AGGREGATE_UID or "blackhole" in name:
                return None
            return device
    return None


def _find(devices: list[dict], *, uid: str | None = None,
          name_contains: str | None = None) -> dict | None:
    for device in devices:
        if uid is not None and device.get("uid") == uid:
            return device
        if name_contains is not None and name_contains in (
            device.get("name") or ""
        ).lower():
            return device
    return None


def status() -> dict:
    """What the record screen needs: is system audio actually reaching
    BlackHole-land, and what is sound playing through right now?"""
    ca, cf = _load()
    devices = _all_devices(ca, cf)
    default_id = _default_output(ca)
    default = next((d for d in devices if d["id"] == default_id), None)
    blackhole = _find(devices, name_contains="blackhole")
    subs = _sub_device_uids(ca, cf, default_id) if default else []
    routed = bool(
        blackhole
        and default
        and (
            default["uid"] == blackhole["uid"]  # BH itself (odd but routed)
            or (blackhole["uid"] in subs)
        )
    )
    return {
        "blackhole_present": blackhole is not None,
        "routed": routed,
        "output_name": (default or {}).get("name"),
        "confab_aggregate_active": bool(default and default["uid"] == AGGREGATE_UID),
    }


def enable() -> dict:
    """Route system audio through BlackHole while keeping the user's device.

    Builds "Confab + <device>" fresh each time (so it always reflects the
    *current* output — AirPods today, speakers tomorrow) and makes it the
    default output. Idempotent when already routed.
    """
    ca, cf = _load()
    devices = _all_devices(ca, cf)
    blackhole = _find(devices, name_contains="blackhole")
    if blackhole is None or not blackhole.get("uid"):
        raise RoutingError("BlackHole isn't installed.")

    default_id = _default_output(ca)
    default = next((d for d in devices if d["id"] == default_id), None)
    if default and blackhole["uid"] in _sub_device_uids(ca, cf, default_id):
        logger.info("System audio already routed via %r.", default["name"])
        return {"routed": True, "output_name": default["name"], "changed": False}

    real = pick_real_device((default or {}).get("uid"), devices)
    if real is None or not real.get("uid"):
        raise RoutingError(
            "Select your real speakers or headphones as the output first — "
            "the current output has no physical device to pair with."
        )

    # Rebuild our aggregate from scratch so it always contains today's device.
    stale = _find(devices, uid=AGGREGATE_UID)
    if stale is not None:
        ca.AudioHardwareDestroyAggregateDevice(ctypes.c_uint32(stale["id"]))

    name = f"Confab + {real['name']}"
    aggregate_id = _create_stacked_aggregate(
        ca, cf, name=name, master_uid=real["uid"], blackhole_uid=blackhole["uid"]
    )
    _set_default_output(ca, aggregate_id)
    logger.info("System audio routed: %r (master %r + BlackHole).",
                name, real["name"])
    return {"routed": True, "output_name": name, "changed": True}


def disable() -> dict:
    """Back to the plain device: restore the master output, drop the aggregate."""
    ca, cf = _load()
    devices = _all_devices(ca, cf)
    aggregate = _find(devices, uid=AGGREGATE_UID)
    if aggregate is None:
        return {"routed": status()["routed"], "changed": False}

    if _default_output(ca) == aggregate["id"]:
        subs = _sub_device_uids(ca, cf, aggregate["id"])
        real_uid = next(
            (uid for uid in subs
             if "blackhole" not in ((_find(devices, uid=uid) or {}).get("name") or "").lower()),
            None,
        )
        real = _find(devices, uid=real_uid) if real_uid else None
        if real is not None:
            _set_default_output(ca, real["id"])
    ca.AudioHardwareDestroyAggregateDevice(ctypes.c_uint32(aggregate["id"]))
    logger.info("System-audio routing disabled; aggregate removed.")
    return {"routed": False, "changed": True}


def _create_stacked_aggregate(
    ca, cf, *, name: str, master_uid: str, blackhole_uid: str
) -> int:
    """CoreAudio aggregate with the stacked flag = a Multi-Output Device.

    The real device is the clock master (glitch-free listening); BlackHole
    drift-corrects against it.
    """
    keys_cb = ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")
    vals_cb = ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryValueCallBacks")
    arr_cb = ctypes.c_void_p.in_dll(cf, "kCFTypeArrayCallBacks")

    retained: list = []

    def s(text: str):
        ref = _cfstr(cf, text)
        retained.append(ref)
        return ref

    def n(value: int):
        raw = ctypes.c_int32(value)
        ref = cf.CFNumberCreate(None, _SINT32, ctypes.byref(raw))
        retained.append(ref)
        return ref

    def sub(uid: str, drift: bool):
        d = cf.CFDictionaryCreateMutable(
            None, 0, ctypes.byref(keys_cb), ctypes.byref(vals_cb)
        )
        retained.append(d)
        cf.CFDictionarySetValue(d, s("uid"), s(uid))  # kAudioSubDeviceUIDKey
        if drift:
            cf.CFDictionarySetValue(d, s("drift"), n(1))
        return d

    subdevices = cf.CFArrayCreateMutable(None, 0, ctypes.byref(arr_cb))
    retained.append(subdevices)
    cf.CFArrayAppendValue(subdevices, sub(master_uid, drift=False))
    cf.CFArrayAppendValue(subdevices, sub(blackhole_uid, drift=True))

    description = cf.CFDictionaryCreateMutable(
        None, 0, ctypes.byref(keys_cb), ctypes.byref(vals_cb)
    )
    retained.append(description)
    cf.CFDictionarySetValue(description, s("uid"), s(AGGREGATE_UID))
    cf.CFDictionarySetValue(description, s("name"), s(name))
    cf.CFDictionarySetValue(description, s("subdevices"), subdevices)
    cf.CFDictionarySetValue(description, s("master"), s(master_uid))
    cf.CFDictionarySetValue(description, s("stacked"), n(1))

    aggregate_id = ctypes.c_uint32(0)
    osstatus = ca.AudioHardwareCreateAggregateDevice(
        description, ctypes.byref(aggregate_id)
    )
    for ref in reversed(retained):
        if ref:
            cf.CFRelease(ref)
    if osstatus != 0 or aggregate_id.value == 0:
        raise RoutingError(
            f"Couldn't create the Multi-Output device (OSStatus {osstatus})."
        )
    return aggregate_id.value
