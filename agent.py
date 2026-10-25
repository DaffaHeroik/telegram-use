#!/usr/bin/env python3
"""Agent intelligence layer — keunggulan tg-agent vs raw MTProto.

Raw Telethon kasih agent: object berantakan, gak ada token budget, search
cuma substring per-chat, gak ada context window awareness, gak ada sandbox.
Layer ini yang bikin tg-agent = "Telegram for AI agents", bukan sekadar wrapper.

Fitur:
  1. token_budget — potong output sebelum meledakin LLM context
  2. thread     — reply chain satu pembicaraan, utuh, tidak terputus
  3. smart_read — pagination aware-cache (halaman 2 gak re-fetch halaman 1)
  4. digest2   — classify + priority ranking (agent tau chat mana yang urgent)
  5. sandbox    — mutating action hanya ke whitelist peer
"""
import asyncio
import json
import os
import time

import reader

# ---------------------------------------------------------------------------
# 1. Token budget — jangan pernah ledakkan context window
# ---------------------------------------------------------------------------

def _estimate_tokens(text, ratio=4.0):
    """Estimasi token kasar: ~4 char/token buat teks campuran (EN+ID+code)."""
    return int(len(text) / ratio)


def _budget_slice(messages, max_tokens):
    """Ambil pesan sebanyak yang muat di budget. Return (slice, stats)."""
    kept, used, dropped = [], 0, []
    for m in messages:
        t = _estimate_tokens(m.get("text") or "")
        if used + t > max_tokens and kept:
            dropped.append(m)
            continue
        kept.append(m)
        used += t
    stats = {
        "tokens_est": used,
        "budget": max_tokens,
        "kept": len(kept),
        "dropped": len(dropped),
        "truncated": bool(dropped),
        "head_or_tail": "tail" if dropped else "full",
    }
    return kept, stats


# ---------------------------------------------------------------------------
# 2. Thread — reply chain utuh
# ---------------------------------------------------------------------------

async def thread(peer, msg_id, max_tokens=2000):
    """Ambil 1 pembicaraan: pesan target + semua reply di atasnya+bawahnya."""
    c = await reader.get_client()
    msgs = await c.get_messages(reader._parse_peer(peer), limit=200)
    by_id = {m.id: m for m in msgs}
    # Telusuri reply chain ke atas
    chain, cur, seen = [], msg_id, set()
    while cur in by_id and cur not in seen:
        seen.add(cur)
        m = by_id[cur]
        chain.append(m)
        rid = getattr(getattr(m, "reply_to", None), "reply_to_msg_id", None)
        cur = rid
    chain.reverse()
    # Kumpulkan reply langsung ke pesan target
    replies = [
        m for m in msgs
        if getattr(getattr(m, "reply_to", None), "reply_to_msg_id", None) == msg_id
        and m.id != msg_id
    ]
    out = [reader._msg_json(m) for m in chain] + \
          [reader._msg_json(m) for m in replies]
    out, stats = _budget_slice(out, max_tokens)
    return {
        "peer": peer,
        "root_msg_id": msg_id,
        "depth": len(chain),
        "replies": len(replies),
        **stats,
        "messages": out,
    }


# ---------------------------------------------------------------------------
# 3. smart_read — pagination yang gak re-fetch
# ---------------------------------------------------------------------------

async def smart_read(peer, max_tokens=3000, before_id=None):
    """Baca chatauto-size: ambil pesan sampai budget, otomatis next-page token.

    before_id = id pesan tertua dari halaman sebelumnya (dari output sebelumnya).
    Halaman 2 gak re-fetch halaman 1 — cache isinya persisten di CACHE_DIR.
    """
    c = await reader.get_client()
    kwargs = {"limit": 200}
    if before_id:
        kwargs["max_id"] = before_id
    msgs = await c.get_messages(reader._parse_peer(peer), **kwargs)
    msgs.reverse()  # kronologis
    out = [reader._msg_json(m) for m in msgs]
    out, stats = _budget_slice(out, max_tokens)
    oldest = out[0]["msg_id"] if out else None
    return {
        "peer": peer,
        **stats,
        "oldest_msg_id": oldest,
        "next_page_hint": f"pass before_id={oldest} untuk halaman berikutnya" if oldest else None,
        "messages": out,
    }


# ---------------------------------------------------------------------------
# 4. Digest v2 — classify + priority ranking
# ---------------------------------------------------------------------------

_PATTERNS = [
    ("mention",   ["@", "daffaheroikzre", "papamamamw", "hero"]),
    ("question",  ["?", "gimana", "gmn", "gabisa", "error", "bug", "kenapa", "mengapa"]),
    ("urgent",    ["urgent", "asap", "sekarang", "butuh", "panik", "down", "mati"]),
    ("task",      ["tugas", "task", "todo", "deadline", "jangan lupa", "please", "tolong"]),
    ("support",   ["support", "bantuan", "minta", "beli", "order", "harga", "sales"]),
]

_PRIORITY = {"urgent": 0, "mention": 1, "question": 2, "task": 3, "support": 4}


def _classify(text):
    t = (text or "").lower()
    tags = [name for name, kws in _PATTERNS if any(k in t for k in kws)]
    return tags


def _priority(tags, unread, verified, sender_is_bot):
    p = min([_PRIORITY[t] for t in tags], default=9)
    if unread:
        p = min(p, 4)
    if sender_is_bot:
        p = max(p, 8)  # bot outbound jarang urgent bagi owner
    return p


async def digest2(top=20, max_tokens=3000, max_per_chat=3):
    """Triage seluruh chat: classify tiap chat, rank berdasarkan prioritas.

    Output urut dari paling urgent. Agent langsung tau chat mana harus dia
    tangani dulu — ini yang MTProto gak kasih.
    """
    c = await reader.get_client()
    dialogs = await c.get_dialogs(limit=None)
    sample = [d for d in dialogs if d.entity is not None][:top]
    tasks = [c.get_messages(d.entity, limit=max_per_chat) for d in sample]
    results = await asyncio.gather(*tasks)
    rows = []
    for d, msgs in zip(sample, results):
        texts = [m.text for m in msgs if m.text]
        blob = " ".join(texts).lower()
        tags = _classify(blob)
        e = d.entity
        sender_is_bot = bool(getattr(e, "bot", False))
        rows.append({
            "chat_id": e.id,
            "name": d.name,
            "type": reader._entity_kind(e),
            "username": getattr(e, "username", None),
            "verified": bool(getattr(e, "verified", False)),
            "unread": int(d.unread_count or 0),
            "tags": tags,
            "priority": _priority(tags, d.unread_count, getattr(e, "verified", False), sender_is_bot),
            "preview": texts[:max_per_chat],
        })
    rows.sort(key=lambda r: (r["priority"], -r["unread"], r["name"].lower()))
    out, stats = _budget_slice(rows, max_tokens * 4)  # rows ringan, budget longgar
    return {
        "chats": len(rows),
        "top_priority": rows[0]["name"] if rows else None,
        **stats,
        "triage": out,
    }


# ---------------------------------------------------------------------------
# 5. Sandbox — mutating action cuma ke whitelist peer
# ---------------------------------------------------------------------------

def _sandbox_peers():
    """Whitelist peer dari env TG_SAFE_PEERS (comma-separated)."""
    raw = os.environ.get("TG_SAFE_PEERS", "")
    return {p.strip().lstrip("@").lower() for p in raw.split(",") if p.strip()}


def check_sandbox(peer):
    """Raise kalau peer gak ada di whitelist (dan sandbox aktif)."""
    if os.environ.get("TG_SANDBOX", "0") != "1":
        return
    allowed = _sandbox_peers()
    if not allowed:
        return
    key = str(peer).lstrip("@").lower()
    if key not in allowed:
        raise RuntimeError(
            f"sandbox: peer '{peer}' tidak ada di TG_SAFE_PEERS — mutating action diblokir"
        )
