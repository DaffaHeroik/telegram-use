#!/usr/bin/env python3
"""Telegram writer core — layer kirim pesan (mutating actions).

Aktif HANYA jika env TG_ALLOW_SEND=1. Default read-only supaya agent tidak
bisa kirim pesan tanpa consent eksplisit dari owner.
"""
import asyncio
import os

import reader
import agent

ALLOW_SEND = os.environ.get("TG_ALLOW_SEND", "0") == "1"


def _guard(peer=None):
    if not ALLOW_SEND:
        raise RuntimeError(
            "send dinonaktifkan — set TG_ALLOW_SEND=1 untuk mengaktifkan mutating actions"
        )
    if peer is not None:
        agent.check_sandbox(peer)


async def send_message(peer, text, reply_to=None, silent=False):
    """Kirim pesan teks. Return info pesan yang dikirim."""
    _guard(peer)
    c = await reader.get_client()
    kwargs = {}
    if reply_to:
        kwargs["reply_to"] = reply_to
    if silent:
        kwargs["silent"] = True
    m = await c.send_message(reader._parse_peer(peer), text, **kwargs)
    return {"ok": True, "msg_id": m.id, "peer": peer, "text": text[:200]}


async def edit_message(peer, msg_id, text):
    """Edit pesan sendiri."""
    _guard()
    c = await reader.get_client()
    m = await c.edit_message(reader._parse_peer(peer), int(msg_id), text)
    return {"ok": True, "msg_id": m.id, "edited": True}


async def delete_messages(peer, msg_ids, revoke=True):
    """Hapus pesan (revoke=True = hapus untuk semua orang). Ambil berapa ID sekaligus, jangan asal hapus."""
    _guard()
    c = await reader.get_client()
    await c.delete_messages(reader._parse_peer(peer), [int(i) for i in msg_ids], revoke=revoke)
    return {"ok": True, "deleted": len(msg_ids)}


async def forward_messages(from_peer, msg_ids, to_peer):
    """Forward pesan ke chat lain."""
    _guard()
    c = await reader.get_client()
    await c.forward_messages(
        reader._parse_peer(to_peer),
        [int(i) for i in msg_ids],
        reader._parse_peer(from_peer),
    )
    return {"ok": True, "forwarded": len(msg_ids), "to": to_peer}


async def send_file(peer, path, caption=None, reply_to=None):
    """Kirim file/media dari disk."""
    _guard()
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    c = await reader.get_client()
    kwargs = {}
    if caption:
        kwargs["caption"] = caption
    if reply_to:
        kwargs["reply_to"] = reply_to
    m = await c.send_file(reader._parse_peer(peer), path, **kwargs)
    return {"ok": True, "msg_id": m.id, "file": path}


async def mark_read(peer, max_id=None):
    """Tandai chat sudah dibaca."""
    _guard()
    c = await reader.get_client()
    await c.send_read_acknowledge(reader._parse_peer(peer), max_id=max_id)
    return {"ok": True, "peer": peer}


async def get_chat_info(peer):
    """Info lengkap 1 chat (bio, members, created date)."""
    c = await reader.get_client()
    e = await c.get_entity(reader._parse_peer(peer))
    out = {
        "id": e.id,
        "type": type(e).__name__,
        "username": getattr(e, "username", None),
        "first_name": getattr(e, "first_name", None),
        "last_name": getattr(e, "last_name", None),
        "title": getattr(e, "title", None),
        "bots_count": getattr(e, "bots_count", None),
    }
    full = getattr(e, "full", None) or await _safe_get_full(c, e)
    if full is not None:
        out["about"] = getattr(full, "about", None)
        out["participants_count"] = getattr(full, "participants_count", None)
    return out


async def _safe_get_full(c, e):
    from telethon.tl.functions.users import GetFullUserRequest
    from telethon.tl.functions.channels import GetFullChannelRequest

    try:
        name = type(e).__name__
        if name == "User":
            r = await c(GetFullUserRequest(e.id))
            return r.full_user
        if name == "Channel":
            r = await c(GetFullChannelRequest(e.id))
            return r.full_chat
    except Exception:
        pass
    return None
