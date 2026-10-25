#!/usr/bin/env python3
"""Setup script — siapkan environment untuk tg-agent.

Cek dependency (telethon), credential file, dan session. Exit code:
  0 = siap pakai
  1 = ada yang kurang (print apa yang harus diperbaiki)
"""
import os
import sys


def main():
    ok = True

    try:
        import telethon  # noqa
        print(f"[OK]    telethon {telethon.__version__}")
    except ImportError:
        print("[MISS]  telethon — install: pip install telethon")
        ok = False

    env_file = os.environ.get("TG_ENV_FILE", "/root/hero-secrets/userbot.env")
    if os.path.exists(env_file):
        has_id = False
        for line in open(env_file):
            if line.startswith("TG_API_ID=") and line.strip() != "TG_API_ID=":
                has_id = True
        print(f"[OK]    env file {env_file} (TG_API_ID {'present' if has_id else 'EMPTY'})")
        if not has_id:
            ok = False
    else:
        print(f"[MISS]  env file {env_file} — set TG_ENV_FILE atau buat file dengan TG_API_ID/TG_API_HASH")
        ok = False

    session = os.environ.get("TG_SESSION_PATH", "/root/hero-userbot/hermes_bridge")
    if os.path.exists(session + ".session"):
        print(f"[OK]    session {session}.session")
    else:
        print(f"[MISS]  session {session}.session — login dulu (telethon interactive)")
        ok = False

    print()
    if ok:
        print("Siap. Jalankan: python3 server.py serve")
    else:
        print("Ada yang kurang — lihat [MISS] di atas.")
        sys.exit(1)


if __name__ == "__main__":
    main()
