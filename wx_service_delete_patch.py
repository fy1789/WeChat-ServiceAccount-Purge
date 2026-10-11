#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeChat-ServiceAccount-Purge
One-Click Delete Patch for PC Weixin (4.1.15.51 x64) Service Account Holder ("brandservicesessionholder").

Usage:
  python wx_service_delete_patch.py status                    # Check live process & disk DLL status
  python wx_service_delete_patch.py apply                     # Apply hot-patch to running Weixin.exe memory
  python wx_service_delete_patch.py restore                   # Restore running Weixin.exe memory to original
  python wx_service_delete_patch.py file-apply [dll_path]     # Backup & patch Weixin.dll on disk (requires Admin)
  python wx_service_delete_patch.py file-restore [dll_path]   # Restore Weixin.dll on disk to original (requires Admin)
"""

import ctypes
import ctypes.wintypes as wt
import os
import shutil
import struct
import sys

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
PROCESS_ALL_ACCESS = 0x001F0FFF
PAGE_EXECUTE_READWRITE = 0x40

TARGET_VERSION = "4.1.15.51"
DEFAULT_DLL_PATH = rf"C:\Program Files\Tencent\Weixin\{TARGET_VERSION}\Weixin.dll"

# RVAs relative to Weixin.dll base (version 4.1.15.51)
FLAG_RVA  = 0x0BBD8FF0  # 1-byte mode flag in .data BSS tail (0 = MsgBox, 1 = BrandService)
SITE1_RVA = 0x05FF6A53  # UI confirm dialog subtitle check for brandservicesessionholder
SITE2_RVA = 0x01C5D555  # ChatSessionCellViewModel::Delete cascade check
SITE3_RVA = 0x0197C2F3  # DeleteAllMsgBoxSession sub-session filter call
STUB1_RVA = 0x076F9F50  # Code cave in .text alignment padding for Stub_CheckBox
STUB2_RVA = 0x076F9F80  # Code cave in .text alignment padding for Stub_FilterSession


def rel32(from_rva: int, insn_len: int, target_rva: int) -> bytes:
    return struct.pack("<i", target_rva - (from_rva + insn_len))


def rva_to_file_offset(rva: int) -> int:
    # All 5 code patch sites reside in .text (VirtualAddress=0x1000, PointerToRawData=0x400)
    return rva - 0x1000 + 0x400


def build_patches():
    # Stub 1: Stub_CheckBox at RVA 0x76F9F50 (46 bytes)
    b1 = STUB1_RVA
    stub1 = bytearray()
    stub1 += b"\x48\x83\xEC\x28"                                          # sub rsp, 0x28
    stub1 += b"\xE8" + rel32(b1 + len(stub1), 5, 0x00BC5610)              # call IsConversationBox
    stub1 += b"\x84\xC0"                                                  # test al, al
    stub1 += b"\x74\x09"                                                  # jz .check_brand_service (+9)
    stub1 += b"\xC6\x05" + rel32(b1 + len(stub1), 7, FLAG_RVA) + b"\x00"  # mov byte ptr [FLAG_RVA], 0
    stub1 += b"\xEB\x13"                                                  # jmp .done (+19)
    # .check_brand_service:
    stub1 += b"\x48\x89\xF1"                                              # mov rcx, rsi
    stub1 += b"\xE8" + rel32(b1 + len(stub1), 5, 0x00BC4F20)              # call IsBrandServiceSessionHolder
    stub1 += b"\x84\xC0"                                                  # test al, al
    stub1 += b"\x74\x07"                                                  # jz .done (+7)
    stub1 += b"\xC6\x05" + rel32(b1 + len(stub1), 7, FLAG_RVA) + b"\x01"  # mov byte ptr [FLAG_RVA], 1
    # .done:
    stub1 += b"\x48\x83\xC4\x28"                                          # add rsp, 0x28
    stub1 += b"\xC3"                                                      # ret

    # Stub 2: Stub_FilterSession at RVA 0x76F9F80 (40 bytes)
    b2 = STUB2_RVA
    stub2 = bytearray()
    stub2 += b"\x80\x3D" + rel32(b2 + len(stub2), 7, FLAG_RVA) + b"\x01"  # cmp byte ptr [FLAG_RVA], 1
    stub2 += b"\x74\x05"                                                  # je .filter_brand_service (+5)
    stub2 += b"\xE9" + rel32(b2 + len(stub2), 5, 0x02557C90)              # jmp IsMsgBoxSubSession
    # .filter_brand_service:
    stub2 += b"\x48\x83\xEC\x28"                                          # sub rsp, 0x28
    stub2 += b"\xE8" + rel32(b2 + len(stub2), 5, 0x02557D20)              # call IsBrandServiceSubSession
    stub2 += b"\x84\xC0"                                                  # test al, al
    stub2 += b"\x74\x08"                                                  # jz .ret (+8)
    stub2 += b"\x4C\x89\xF1"                                              # mov rcx, r14
    stub2 += b"\xE8" + rel32(b2 + len(stub2), 5, 0x00BC45C0)              # call IsBrandOrServiceContact
    # .ret:
    stub2 += b"\x48\x83\xC4\x28"                                          # add rsp, 0x28
    stub2 += b"\xC3"                                                      # ret

    return [
        ("STUB1 (Stub_CheckBox)",      STUB1_RVA, b"\xCC" * len(stub1), bytes(stub1)),
        ("STUB2 (Stub_FilterSession)", STUB2_RVA, b"\xCC" * len(stub2), bytes(stub2)),
        ("SITE1 (UI Dialog Subtitle)", SITE1_RVA, b"\x74\x16",          b"\xEB\x16"),
        ("SITE2 (Delete Cascade)",     SITE2_RVA, b"\xE8" + rel32(SITE2_RVA, 5, 0x02557CD0), b"\xE8" + rel32(SITE2_RVA, 5, STUB1_RVA)),
        ("SITE3 (SubSession Filter)",  SITE3_RVA, b"\xE8" + rel32(SITE3_RVA, 5, 0x02557C90), b"\xE8" + rel32(SITE3_RVA, 5, STUB2_RVA)),
    ]


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_ulonglong), ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", wt.LONG), ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_char * 260),
    ]


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.c_void_p), ("modBaseSize", wt.DWORD),
        ("hModule", wt.HMODULE), ("szModule", ctypes.c_char * 256), ("szExePath", ctypes.c_char * 260),
    ]


def find_weixin_process():
    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(pe)
    results = []
    if k32.Process32First(snap, ctypes.byref(pe)):
        while True:
            if pe.szExeFile.decode("gbk", "ignore").lower() == "weixin.exe":
                pid = pe.th32ProcessID
                msnap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
                me = MODULEENTRY32()
                me.dwSize = ctypes.sizeof(me)
                if k32.Module32First(msnap, ctypes.byref(me)):
                    while True:
                        if me.szModule.decode("gbk", "ignore").lower() == "weixin.dll":
                            exe_path = me.szExePath.decode("gbk", "ignore")
                            results.append((pid, me.modBaseAddr, me.modBaseSize, exe_path))
                            break
                        if not k32.Module32Next(msnap, ctypes.byref(me)):
                            break
                k32.CloseHandle(msnap)
            if not k32.Process32Next(snap, ctypes.byref(pe)):
                break
    k32.CloseHandle(snap)
    return results


def read_mem(hproc, addr: int, size: int) -> bytes:
    buf = ctypes.create_string_buffer(size)
    nread = ctypes.c_size_t(0)
    if not ctypes.windll.kernel32.ReadProcessMemory(hproc, ctypes.c_void_p(addr), buf, size, ctypes.byref(nread)):
        raise RuntimeError(f"ReadProcessMemory failed at 0x{addr:X}")
    return buf.raw


def write_mem(hproc, addr: int, data: bytes):
    k32 = ctypes.windll.kernel32
    old_prot = wt.DWORD(0)
    if not k32.VirtualProtectEx(hproc, ctypes.c_void_p(addr), len(data), PAGE_EXECUTE_READWRITE, ctypes.byref(old_prot)):
        raise RuntimeError(f"VirtualProtectEx failed at 0x{addr:X}")
    nwritten = ctypes.c_size_t(0)
    ok = k32.WriteProcessMemory(hproc, ctypes.c_void_p(addr), data, len(data), ctypes.byref(nwritten))
    k32.VirtualProtectEx(hproc, ctypes.c_void_p(addr), len(data), old_prot.value, ctypes.byref(old_prot))
    k32.FlushInstructionCache(hproc, ctypes.c_void_p(addr), len(data))
    if not ok or nwritten.value != len(data):
        raise RuntimeError(f"WriteProcessMemory failed at 0x{addr:X}")


def handle_live(action: str, patches):
    procs = find_weixin_process()
    if not procs:
        print("[-] No running Weixin.exe process with Weixin.dll found.")
        return None

    k32 = ctypes.windll.kernel32
    detected_dll = None
    for pid, base, _, dll_path in procs:
        detected_dll = dll_path
        print(f"[*] Live Process: Weixin.exe (PID={pid}), Weixin.dll Base=0x{base:X}")
        print(f"    Module Path : {dll_path}")
        hproc = k32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not hproc:
            print(f"[-] OpenProcess failed for PID {pid} (err={k32.GetLastError()})")
            continue
        try:
            # Verify all sites before applying/restoring to ensure version compatibility
            states = []
            for name, rva, orig_bytes, patch_bytes in patches:
                va = base + rva
                cur = read_mem(hproc, va, len(orig_bytes))
                if cur == orig_bytes:
                    state = "ORIGINAL"
                elif cur == patch_bytes:
                    state = "PATCHED"
                else:
                    state = f"MISMATCH ({cur.hex()})"
                states.append((name, rva, va, orig_bytes, patch_bytes, state))
                print(f"  - {name:28s} @ 0x{va:X} (RVA 0x{rva:07X}): {state}")

            if any(s[5].startswith("MISMATCH") for s in states):
                print(f"[!] Byte signature mismatch! Please check if Weixin version is {TARGET_VERSION}.")
                continue

            for name, rva, va, orig_bytes, patch_bytes, state in states:
                if action == "apply" and state == "ORIGINAL":
                    write_mem(hproc, va, patch_bytes)
                    verify = read_mem(hproc, va, len(patch_bytes))
                    print(f"    -> Applied {name}! Verified={verify == patch_bytes}")
                elif action == "restore" and state == "PATCHED":
                    write_mem(hproc, va, orig_bytes)
                    verify = read_mem(hproc, va, len(orig_bytes))
                    print(f"    -> Restored {name}! Verified={verify == orig_bytes}")
        finally:
            k32.CloseHandle(hproc)
    return detected_dll


def handle_file(action: str, patches, dll_path: str = DEFAULT_DLL_PATH):
    if not os.path.exists(dll_path):
        print(f"[-] Disk file not found: {dll_path}")
        return

    print(f"[*] Disk File: {dll_path}")
    states = []
    with open(dll_path, "rb") as f:
        for name, rva, orig_bytes, patch_bytes in patches:
            off = rva_to_file_offset(rva)
            f.seek(off)
            cur = f.read(len(orig_bytes))
            state = "ORIGINAL" if cur == orig_bytes else ("PATCHED" if cur == patch_bytes else f"MISMATCH ({cur.hex()})")
            states.append(state)
            print(f"  - {name:28s} @ FileOffset 0x{off:07X} (RVA 0x{rva:07X}): {state}")

    if any(s.startswith("MISMATCH") for s in states):
        print(f"[!] Byte signature mismatch on disk! Expected Weixin version {TARGET_VERSION}.")
        return

    if action in ("file-apply", "file-restore"):
        bak_path = dll_path + ".bak"
        if action == "file-apply" and not os.path.exists(bak_path):
            shutil.copy2(dll_path, bak_path)
            print(f"[+] Created backup: {bak_path}")
        with open(dll_path, "r+b") as f:
            for name, rva, orig_bytes, patch_bytes in patches:
                off = rva_to_file_offset(rva)
                target = patch_bytes if action == "file-apply" else orig_bytes
                f.seek(off)
                f.write(target)
        print(f"[+] Disk file {action} completed successfully.")


def main():
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "apply"
    custom_dll = sys.argv[2] if len(sys.argv) > 2 else None
    patches = build_patches()

    if action == "status":
        detected = handle_live("status", patches)
        handle_file("status", patches, custom_dll or detected or DEFAULT_DLL_PATH)
    elif action in ("apply", "restore"):
        handle_live(action, patches)
    elif action in ("file-apply", "file-restore"):
        handle_file(action, patches, custom_dll or DEFAULT_DLL_PATH)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
