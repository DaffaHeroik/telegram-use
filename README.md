# telegram-use — Telegram for AI agents

**Browser Use for Telegram.** MCP server yang mengubah Telegram menjadi tools
yang bisa dipanggil AI agent — baca ribuan chat dalam hitungan detik, kirim
pesan, dan otomatis tau chat mana yang harus ditangani dulu.

Agent tidak perlu menginstall Telethon, pegang session, atau pusing dengan
MTProto. Panggil `read_chat`, dapat JSON. Itu saja.

## Kenapa ini ada

Telegram Web butuh scroll+render per chat — 1000 pesan = 5–10 menit. Bot API
tidak bisa membaca chat pribadi. telegram-use menarik langsung dari **MTProto**
(protokol resmi Telegram), sekaligus menambah **layer kecerdasan** yang
dimiliki oleh keduanya: token budget, thread utuh, triage otomatis, dan sandbox.

## Install

```bash
git clone https://github.com/DaffaHeroik/telegram-use.git
cd telegram-use
pip install telethon
python3 setup_check.py
```

Anda butuh:

1. **API credentials** — dapatkan di my.telegram.org (gratis, 2 menit).
   Simpan ke dalam file, contoh `~/.tg/telegram.env`:
   ```
   TG_API_ID=123456
   TG_API_HASH=abcdef0123456789abcdef0123456789
   ```
2. **Session** — login sekali dengan Telethon:
   ```bash
   python3 -c "
   from telethon.sync import TelegramClient
   c = TelegramClient('~/.tg/session', 123456, 'your_api_hash')
   c.start()  # akan minta nomor HP + kode login
   "
   ```

Setelah itu, jalankan MCP server:

```bash
python3 server.py serve
```

## Config

Wajib:

| Env | Isi |
|---|---|---|
| `TG_ENV_FILE` | path ke file berisi `TG_API_ID` / `TG_API_HASH` |
| `TG_SESSION_PATH` | path session Telethon (tanpa ekstensi `.session`) |

Opsional:

| Env | Default | Kegunaan |
|---|---|---|
| `TG_CACHE_DIR` | `./cache` | lokasi cache |
| `TG_CACHE_TTL` | `300` | umur cache (detik) — repeat query gratis |
| `TG_ALLOW_SEND` | `0` | set `1` untuk mengaktifkan mutating actions |
| `TG_SANDBOX` | `0` | set `1` — mutating action hanya ke whitelist |
| `TG_SAFE_PEERS` | (kosong) | peer whitelist, contoh `me,123456789` |

## Tools (16)

**Baca** (jalan tanpa env tambahan):

| Tool | Kegunaan |
|---|---|
| `me` | identitas akun yang login |
| `list_chats` | daftar chat (id, nama, tipe, username) |
| `read_chat` | N pesan terakhir dari 1 peer |
| `batch_read` | banyak chat sekaligus (paralel) |
| `search_messages` | pencarian substring lintas chat |
| `digest` | ringkasan per-chat (token-efficient) |
| `chat_info` | info lengkap 1 chat (bio, member count) |

**Tulis** (butuh `TG_ALLOW_SEND=1`):

| Tool | Kegunaan |
|---|---|---|
| `send_message` | kirim teks (`reply_to`, `silent`) |
| `edit_message` | edit pesan sendiri |
| `delete_messages` | hapus pesan (revoke) — ambil beberapa ID sekaligus |
| `forward_messages` | teruskan ke chat lain |
| `send_file` | kirim file/media dari disk |
| `mark_read` | tandai chat sudah dibaca |

**Cerdas** (layer agent — lihat "Kenapa bukan Telethon saja"):

| Tool | Kegunaan |
|---|---|
| `smart_read` | baca sampai token budget + `next_page_hint` |
| `thread` | satu pembicaraan utuh: reply chain ke atas + semua reply |
| `digest2` | triase inbox: klassifikasi (urgent/question/task/support/mention) + prioritas |

## Performance

MTProto persistent connection, batching paralel, dan cache:

| Operasi | Cold | Cached (5 menit) |
|---|---|---|
| list_chats (44 chat) | 0.10s | — |
| 500 pesan dari 1 chat | 0.97s | — |
| 2000 pesan dari 1 chat | ~1s | — |
| full history 3546 pesan (6 bulan) | 53.5s | — |
| 20 chat paralel × 20 pesan | 0.06s | — |
| batch_read top 20 | 0.47s | **0.0005s (1000x)** |
| digest top 10 | 0.13s | **0.0002s** |
| kirim 1 pesan | **0.027s** | — |

Batasannya adalah rate limit Telegram, bukan kode. Yang membuatnya cepat:
baca paralel `asyncio.gather`, koneksi TCP persistent, dan cache 5 menit.

## Kenapa bukan Telethon saja?

MTProto hanya memberikan pipa, bukan otak. Telethon memberi Anda object
berantakan, tidak ada token budget, thread harus dirakit manual, tidak ada
safety rail. telegram-use menambahkan:

1. **Token budget** — setiap response dipotong sesuai `max_tokens`. Lihat
   `next_page_hint` untuk halaman berikutnya tanpa re-fetch.
2. **Thread utuh** — `thread` menelusuri reply chain ke atas + mengumpulkan
   semua reply. Satu pembicaraan, tidak berantakan.
3. **Triage otomatis** — `digest2` menandai setiap chat (urgent / question /
   task / support / mention) lalu diurutkan. Agent langsung tahu chat mana
   yang urgent.
4. **Sandbox** — `TG_SANDBOX=1` + `TG_SAFE_PEERS=me,123` membatasi mutating
   action hanya ke whitelist. Bawaan, tidak perlu kode tambahan.

## Config MCP

OpenCode / Hermes / Claude Desktop / Cursor — sama saja:

```json
{
  "mcp": {
    "telegram-use": {
      "type": "local",
      "command": ["/path/to/telegram-use/server.py", "serve"],
      "env": {
        "TG_ENV_FILE": "/home/you/.tg/telegram.env",
        "TG_SESSION_PATH": "/home/you/.tg/session",
        "TG_ALLOW_SEND": "1",
        "TG_SANDBOX": "1",
        "TG_SAFE_PEERS": "me"
      },
      "enabled": true
    }
  }
}
```

## Gotcha

Telethon mem-pin event loop setelah terhubung — MCP server harus menjalankan
semua pemanggilan tool melalui *persistent* `asyncio` loop
(`run_until_complete`), tidak pernah `asyncio.run()` per panggilan. Melanggarnya
memberikan "event loop must not change after connection" pada panggilan kedua.

## Bahaya / tanggung jawab

Ini userbot: mutating action berjalan sebagai **akun Telegram Anda**.
`TG_ALLOW_SEND=1` membuka kemampuan kirim. Aktifkan sandbox saat Agent bisa
memutuskan sendiri tujuannya. Segala tanggung jawab ada pada pengguna.

## Tech

Python 3.11+, Telethon (MTProto), zero dependency lain. Read-only secara
default; write hanya jika diaktifkan secara eksplisit.

## License

MIT
