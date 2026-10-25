# tg-agent — Telegram for AI agents

MCP server yang bikin AI agent bisa baca Telegram dengan kecepatan API, bukan
klik UI. "Browser Use untuk Telegram."

## Kenapa

Telegram Web butuh scroll+render per chat — 1000 pesan = 5–10 menit. tg-agent
narik pesan yang sama **langsung dari MTProto dalam <1 detik**. Read-only by
default, output langsung structured JSON siap masuk LLM context.

## Setup

```bash
pip install telethon
python3 setup_check.py          # cek dependency + credential + session
python3 server.py serve         # MCP server (stdio JSON-RPC 2.0)
python3 server.py call me '{}'  # CLI debug
python3 server.py call read_chat '{"peer": 7821918442, "limit": 10}'
```

Credential via env var (atau fallback ke path default di VPS):
- `TG_ENV_FILE` — file berisi `TG_API_ID` / `TG_API_HASH`
- `TG_SESSION_PATH` — path session Telethon tanpa ekstensi
- `TG_CACHE_DIR`, `TG_CACHE_TTL` — cache repeat query (default `./cache`, 300s)

Config snippet untuk agent (OpenCode / Hermes / Cursor / Claude):

```json
{
  "mcp": {
    "tg-agent": {
      "type": "local",
      "command": ["/path/to/tg-agent/server.py", "serve"],
      "enabled": true
    }
  }
}
```

## Tools (MCP)

**Baca** (default, tanpa env):
- `me` — identitas akun yang login
- `list_chats [limit]` — daftar chat (id, nama, tipe, username)
- `read_chat <peer> [limit]` — N pesan terakhir dari 1 peer
- `batch_read [limit] [top]` — banyak chat sekaligus (paralel)
- `search_messages <query> [peer] [limit] [top]` — substring search lintas chat
- `digest [top] [limit]` — ringkasan per-chat (token-efficient buat triase ribuan chat)
- `chat_info <peer>` — info lengkap 1 chat (bio, member count, dll)

**Tulis** (butuh `TG_ALLOW_SEND=1`, default OFF):
- `send_message <peer> <text> [reply_to] [silent]`
- `edit_message <peer> <msg_id> <text>`
- `delete_messages <peer> <msg_ids[]> [revoke]`
- `forward_messages <from_peer> <msg_ids[]> <to_peer>`
- `send_file <peer> <path> [caption]`
- `mark_read <peer>`

Semua mutating action di-guard env `TG_ALLOW_SEND=1` — agent tidak bisa
kirim apapun tanpa consent eksplisit dari owner.

## Performance (44-chat account, Tencent Beijing VPS)

| Operasi | Cold | Cached (5 menit) |
|---|---|---|
| list_chats (semua 44) | 0.10s | — |
| 500 pesan dari 1 channel | 0.97s | — |
| 2000 pesan dari 1 channel | ~1s | — |
| full history 3546 pesan (6 bulan) | 53.5s | — |
| 20 chat paralel × 20 pesan | 0.06s | — |
| batch_read top 20 | 0.47s | **0.0005s (1000x)** |
| digest 10 chat teratas | 0.13s | **0.0002s** |
| search 20 chat | 0.37s | — |

Batasannya adalah rate limit Telegram, bukan kode. Repeat query dalam window
cache 300s gratis — pattern agent-nya: digest sekali, lalu drill ke chat yang
relevan,semua tanpa re-hit MTProto.

## Kenapa gak Telethon langsung?

Karena MTProto cuma kasih pipa, bukan otak. Yang MTProto gak punya (dan
tg-agent kasih):

1. **Token budget** — setiap response dipotong sesuai `max_tokens`, tidak
   pernah ledakkan context window. `smart_read` ambil pesan sampai budget
   lalu kasih `next_page_hint` — pagination tanpa re-fetch.
2. **Thread utuh** — `thread` telusuri reply chain ke atas + kumpulkan semua
   reply. Satu pembicaraan, gak terpatial oleh pesan lain.
3. **Triage otomatis** — `digest2` classify tiap chat (urgent/question/task/
   support/mention) lalu rank. Agent tau chat mana harus ditangani dulu.
4. **Sandbox** — set `TG_SANDBOX=1` + `TG_SAFE_PEERS=me,12345` maka mutating
   action cuma bisa ke peer yang di-whitelist. Safety rail bawaan.

## Gotcha

Telethon pins its event loop after connect — the MCP server MUST run every
`tools/call` through ONE persistent `asyncio.new_event_loop()`
(`run_until_complete`), never `asyncio.run()` per call. Violating this gives
"event loop must not change after connection" on the second call.

## Tech

Telethon 1.45 (MTProto client), Python 3.11, zero dependency selain Telethon.
Read-only by design — mengirim pesan butuh layer terpisah yang explicit.

## License

MIT
