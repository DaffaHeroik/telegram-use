#!/usr/bin/env python3
"""Setup script — siapkan environment untuk telegram-use.

Cek dependency (telethon), credential file, dan session. Exit code:
  0 = siap pakai
  1 = ada yang kurang (print apa yang harus diperbaiki)

Env vars wajib:
  TG_ENV_FILE      file berisi TG_API_ID / TG_API_HASH
  TG_SESSION_PATH  path session Telethon (tanpa ekstensi .session)

Env vars opsional:
  TG_CACHE_DIR, TG_CACHE_TTL, TG_ALLOW_SEND, TG_SANDBOX, TG_SAFE_PEERS
"""
import os
import sys


def _get(name, default=None):
    return os.environ.get(name, default)


def main():
    ok = True

    try:
        import telethon  # noqa
        print(f"[OK]    telethon {telethon.__version__}")
    except ImportError:
        print("[MISS]  telethon — install: pip install telethon")
        ok = False

    env_file = _get("TG_ENV_FILE")
    if not env_file:
        print("[MISS]  TG_ENV_FILE belum diset — file berisi TG_API_ID/TG_API_HASH")
        ok = False
    elif os.path.exists(env_file):
        has_id = False
        for line in open(env_file):
            if line.startswith("TG_API_ID=") and line.strip() != "TG_API_ID=":
                has_id = True
        print(f"[OK]    env file {env_file} (TG_API_ID {'present' if has_id else 'EMPTY'})")
        if not has_id:
            ok = False
    else:
        print(f"[MISS]  env file {env_file} tidak ada — set TG_ENV_FILE atau buat file dengan TG_API_ID/TG_API_HASH")
        ok = False

    session = _get("TG_SESSION_PATH")
    if not session:
        print("[MISS]  TG_SESSION_PATH belum diset — path session Telethon (tanpa .session)")
        ok = False
    elif os.path.exists(session + ".session"):
        print(f"[OK]    session {session}.session")
    else:
        print(f"[MISS]  session {session}.session tidak ada — login dulu (telethon interactive)")
        ok = False

    if _get("TG_ALLOW_SEND") == "1":
        print("[WARN]  TG_ALLOW_SEND=1 — mutating actions aktif")
        if _get("TG_SANDBOX") == "1":
            print(f"[OK]    sandbox aktif, safe peers: {_get('TG_SAFE_PEERS', '(unset)')}")
        else:
            print("[WARN]  TG_SANDBOX tidak aktif — send bisa ke peer mana saja")

    print()
    if ok:
        print("Siap. Jalankan: python3 server.py serve")
    else:
        print("Ada yang kurang — lihat [MISS] di atas.")
        sys.exit(1)


if __name__ == "__main__":
    main()
