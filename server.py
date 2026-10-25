#!/usr/bin/env python3
"""tg-agent — MCP server: Telegram for AI agents.

stdio JSON-RPC 2.0. Tools: list_chats, read_chat, batch_read, search, digest, me.

Setup (OpenCode / Hermes / Claude / Cursor):
  command: ["/root/tg-agent/server.py", "serve"]

CLI debug:
  python3 server.py call list_chats '{}'
  python3 server.py call read_chat '{"peer": 7821918442, "limit": 10}'
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reader
import writer

TOOLS = [
    {
        "name": "me",
        "description": "Identitas akun Telegram yang sedang login (read-only sanity check).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_chats",
        "description": "Daftar chat/Channel/User yang terbaca (id, nama, tipe, username). Cepat: ~0.1s.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 100}},
        },
    },
    {
        "name": "read_chat",
        "description": "Baca N pesan terakhir dari satu chat (peer = id atau username). 500 pesan ~1s.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "peer": {"type": ["integer", "string"]},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["peer"],
        },
    },
    {
        "name": "batch_read",
        "description": "Baca banyak chat sekaligus secara paralel. 20 chat x 20 pesan = 0.06s.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
                "top": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "search_messages",
        "description": "Cari substring di pesan. Tanpa peer = cari di top N chat. Return match saja.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "peer": {"type": ["integer", "string"], "default": None},
                "limit": {"type": "integer", "default": 100},
                "top": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "digest",
        "description": "Ringkasan per-chat dengan preview pesan terakhir. Token-efficient untuk triase ribuan chat.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "top": {"type": "integer", "default": 10},
                "limit": {"type": "integer", "default": 5},
            },
        },
    },
    {
        "name": "chat_info",
        "description": "Info lengkap satu chat: bio, jumlah member, tanggal dibuat, dll.",
        "inputSchema": {
            "type": "object",
            "properties": {"peer": {"type": ["integer", "string"]}},
            "required": ["peer"],
        },
    },
    {
        "name": "send_message",
        "description": "Kirim pesan teks ke chat. MUTATING — butuh TG_ALLOW_SEND=1.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "peer": {"type": ["integer", "string"]},
                "text": {"type": "string"},
                "reply_to": {"type": "integer", "default": None},
                "silent": {"type": "boolean", "default": False},
            },
            "required": ["peer", "text"],
        },
    },
    {
        "name": "edit_message",
        "description": "Edit pesan sendiri. MUTATING — butuh TG_ALLOW_SEND=1.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "peer": {"type": ["integer", "string"]},
                "msg_id": {"type": "integer"},
                "text": {"type": "string"},
            },
            "required": ["peer", "msg_id", "text"],
        },
    },
    {
        "name": "delete_messages",
        "description": "Hapus pesan (revoke=True hapus buat semua orang). Ambil berapa ID sekaligus, jangan asal hapus. Amankan pesan sebelum menghapus. MUTATING — butuh TG_ALLOW_SEND=1.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "peer": {"type": ["integer", "string"]},
                "msg_ids": {"type": "array", "items": {"type": "integer"}},
                "revoke": {"type": "boolean", "default": True},
            },
            "required": ["peer", "msg_ids"],
        },
    },
    {
        "name": "forward_messages",
        "description": "Forward pesan ke chat lain. MUTATING — butuh TG_ALLOW_SEND=1.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_peer": {"type": ["integer", "string"]},
                "msg_ids": {"type": "array", "items": {"type": "integer"}},
                "to_peer": {"type": ["integer", "string"]},
            },
            "required": ["from_peer", "msg_ids", "to_peer"],
        },
    },
    {
        "name": "send_file",
        "description": "Kirim file/media dari disk. MUTATING — butuh TG_ALLOW_SEND=1.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "peer": {"type": ["integer", "string"]},
                "path": {"type": "string"},
                "caption": {"type": "string", "default": None},
                "reply_to": {"type": "integer", "default": None},
            },
            "required": ["peer", "path"],
        },
    },
    {
        "name": "mark_read",
        "description": "Tandai chat sudah dibaca. MUTATING — butuh TG_ALLOW_SEND=1.",
        "inputSchema": {
            "type": "object",
            "properties": {"peer": {"type": ["integer", "string"]}},
            "required": ["peer"],
        },
    },
]


_LOOP = None


def _get_loop():
    """Satu event loop persistent — Telethon menolak ganti loop setelah connect."""
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP


async def dispatch(name, args):
    args = args or {}
    if name == "me":
        return await reader.me()
    if name == "list_chats":
        return await reader.list_chats(limit=args.get("limit", 100))
    if name == "read_chat":
        return await reader.read_chat(peer=args["peer"], limit=args.get("limit", 50))
    if name == "batch_read":
        return await reader.batch_read(limit=args.get("limit", 20), top=args.get("top", 20))
    if name == "search_messages":
        return await reader.search_messages(
            query=args["query"], peer=args.get("peer"), limit=args.get("limit", 100), top=args.get("top", 20)
        )
    if name == "digest":
        return await reader.digest(top=args.get("top", 10), limit=args.get("limit", 5))
    if name == "chat_info":
        return await writer.get_chat_info(peer=args["peer"])
    if name == "send_message":
        return await writer.send_message(
            peer=args["peer"], text=args["text"],
            reply_to=args.get("reply_to"), silent=args.get("silent", False),
        )
    if name == "edit_message":
        return await writer.edit_message(peer=args["peer"], msg_id=args["msg_id"], text=args["text"])
    if name == "delete_messages":
        return await writer.delete_messages(
            peer=args["peer"], msg_ids=args["msg_ids"], revoke=args.get("revoke", True),
        )
    if name == "forward_messages":
        return await writer.forward_messages(
            from_peer=args["from_peer"], msg_ids=args["msg_ids"], to_peer=args["to_peer"],
        )
    if name == "send_file":
        return await writer.send_file(
            peer=args["peer"], path=args["path"],
            caption=args.get("caption"), reply_to=args.get("reply_to"),
        )
    if name == "mark_read":
        return await writer.mark_read(peer=args["peer"])
    raise ValueError(f"unknown tool: {name}")


def _result(content):
    return {"content": [{"type": "text", "text": json.dumps(content, ensure_ascii=False, default=str)}]}


def serve_stdio():
    mid = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if req.get("method") == "initialize":
            mid = req.get("id")
            resp = {
                "jsonrpc": "2.0", "id": mid, "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "tg-agent", "version": "1.0.0"},
                },
            }
        elif req.get("method") == "notifications/initialized":
            continue
        elif req.get("method") == "tools/list":
            resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": {"tools": TOOLS}}
        elif req.get("method") == "tools/call":
            Name = req["params"]["name"]
            args = req["params"].get("arguments", {})
            try:
                out = _get_loop().run_until_complete(dispatch(Name, args))
                resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": _result(out)}
            except Exception as e:
                resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": {
                    "content": [{"type": "text", "text": f"error: {e}"}], "isError": True,
                }}
        else:
            resp = {"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32601, "message": "method not found"}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


def cli():
    """Debug CLI: server.py call <tool> '<json args>'"""
    if len(sys.argv) >= 4 and sys.argv[1] == "call":
        name = sys.argv[2]
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        try:
            out = _get_loop().run_until_complete(dispatch(name, args))
            print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        except Exception as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
            sys.exit(1)
    else:
        print(__doc__)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve_stdio()
    else:
        cli()
