#!/usr/bin/env python3
"""Telegram reader core — Telethon-backed, agent-oriented.

Dipakai oleh server.py (MCP) dan CLI. Read-only by default.
Semua output sudah structured (dict/list) supaya langsung masuk LLM context.
"""
import asyncio
import hashlib
import json
import os
import time

# Config: env vars wajib. Gak ada hardcoded path/credential di repo ini.
# Jalankan `python3 setup_check.py` untuk cek segalanya.
SESSION = os.environ["TG_SESSION_PATH"]          # contoh: /home/you/.tg/session
ENV_FILE = os.environ["TG_ENV_FILE"]             # contoh: /home/you/.tg/telegram.env
CACHE_DIR = os.environ.get("TG_CACHE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache"))
CACHE_TTL = int(os.environ.get("TG_CACHE_TTL", 300))  # detik

_client = None


def _cache_key(*parts):
    raw = json.dumps(parts, default=str, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _cache_get(key):
    os.makedirs(CACHE_DIR, exist_ok=True)
    p = os.path.join(CACHE_DIR, key + ".json")
    if not os.path.exists(p):
        return None
    age = time.time() - os.path.getmtime(p)
    if age > CACHE_TTL:
        return None
    return json.load(open(p))


def _cache_put(key, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    p = os.path.join(CACHE_DIR, key + ".json")
    json.dump(data, open(p, "w"), ensure_ascii=False, default=str)


def _load_env():
    env = {}
    for line in open(ENV_FILE):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v.strip()
    return env


async def get_client():
    global _client
    if _client is None or not _client.is_connected():
        from telethon import TelegramClient
        env = _load_env()
        _client = TelegramClient(SESSION, int(env["TG_API_ID"]), env["TG_API_HASH"])
        await _client.connect()
        me = await _client.get_me()
        if me is None:
            raise RuntimeError("Telegram session expired — user must re-login")
    return _client


def _entity_kind(e):
    return type(e).__name__


async def list_chats(limit=100):
    """Daftar chat: id, nama, tipe, username. 0.1s untuk 44 dialog."""
    c = await get_client()
    dialogs = await c.get_dialogs(limit=limit)
    out = []
    for d in dialogs:
        if d.entity is None:
            continue
        e = d.entity
        out.append({
            "chat_id": e.id,
            "name": d.name,
            "type": _entity_kind(e),
            "username": getattr(e, "username", None),
        })
    return {"count": len(out), "chats": out}


def _parse_peer(peer):
    s = str(peer).strip()
    if s.lstrip("-").isdigit():
        return int(s)
    return s


def _msg_json(m, chat_name=None):
    return {
        "msg_id": m.id,
        "date": m.date.isoformat() if m.date else None,
        "sender_id": m.sender_id,
        "text": m.text,
        **({"chat_name": chat_name} if chat_name else {}),
    }


async def read_chat(peer, limit=50):
    """Baca N pesan terakhir dari 1 chat. 500 pesan ~1s."""
    c = await get_client()
    msgs = await c.get_messages(_parse_peer(peer), limit=limit)
    entity = msgs[0].peer_id if msgs else None
    name = None
    try:
        d = await c.get_entity(_parse_peer(peer))
        name = getattr(d, "title", None) or getattr(d, "first_name", None) or str(d.id)
    except Exception:
        pass
    return {
        "chat": peer,
        "chat_name": name,
        "count": len(msgs),
        "messages": [_msg_json(m, name) for m in reversed(msgs)],
    }


async def batch_read(limit=20, top=20):
    """Baca banyak chat sekaligus (parallel gather). 20x20 = 0.06s. Cached."""
    key = _cache_key("batch_read", limit, top)
    hit = _cache_get(key)
    if hit is not None:
        hit["cached"] = True
        return hit
    c = await get_client()
    dialogs = await c.get_dialogs(limit=None)
    sample = [d for d in dialogs if d.entity is not None][:top]
    t0 = time.time()
    tasks = [c.get_messages(d.entity, limit=limit) for d in sample]
    results = await asyncio.gather(*tasks)
    out = []
    for d, msgs in zip(sample, results):
        for m in reversed(msgs):
            out.append({
                "chat_id": d.entity.id,
                "chat_name": d.name,
                **_msg_json(m),
            })
    result = {
        "chats_read": len(sample),
        "total_messages": len(out),
        "elapsed_sec": round(time.time() - t0, 3),
        "messages": out,
    }
    _cache_put(key, result)
    return result


async def search_messages(query, peer=None, limit=100, top=20):
    """Cari substring di banyak chat. Return match saja."""
    q = query.lower()
    matches = []
    c = await get_client()
    if peer:
        msgs = await c.get_messages(_parse_peer(peer), limit=limit)
        for m in msgs:
            if m.text and q in m.text.lower():
                matches.append(_msg_json(m))
    else:
        dialogs = await c.get_dialogs(limit=None)
        sample = [d for d in dialogs if d.entity is not None][:top]
        tasks = [c.get_messages(d.entity, limit=limit) for d in sample]
        results = await asyncio.gather(*tasks)
        for d, msgs in zip(sample, results):
            for m in msgs:
                if m.text and q in m.text.lower():
                    matches.append({"chat_id": d.entity.id, "chat_name": d.name, **_msg_json(m)})
    return {"query": query, "matches": len(matches), "results": matches}


async def digest(top=10, limit=5):
    """Ringkasan per-chat: preview pesan terakhir. Token-efficient. Cached."""
    key = _cache_key("digest", top, limit)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    c = await get_client()
    dialogs = await c.get_dialogs(limit=None)
    sample = [d for d in dialogs if d.entity is not None][:top]
    tasks = [c.get_messages(d.entity, limit=limit) for d in sample]
    results = await asyncio.gather(*tasks)
    out = []
    for d, msgs in zip(sample, results):
        out.append({
            "chat_id": d.entity.id,
            "chat_name": d.name,
            "type": _entity_kind(d.entity),
            "last_date": msgs[0].date.isoformat() if msgs and msgs[0].date else None,
            "n_messages_pulled": len(msgs),
            "preview": [m.text[:120] for m in reversed(msgs) if m.text][:limit],
        })
    result = {"chats": len(out), "digest": out}
    _cache_put(key, result)
    return result


async def me():
    c = await get_client()
    u = await c.get_me()
    return {"id": u.id, "first_name": u.first_name, "username": u.username}
