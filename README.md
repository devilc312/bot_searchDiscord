<div align="center">

# Discord AI Search Bot

**Bot hỏi – đáp bằng AI, tự tìm kiếm thông tin trên web và trả lời trong thread Discord.**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

</div>

---

## Tổng quan

Ai @mention bot trong server, bot tạo một thread, tìm kiếm trên web, đọc các trang liên quan rồi trả lời kèm link nguồn. Trong thread đó, hỏi tiếp không cần @mention lại.

Toàn bộ code tự viết bằng Python và discord.py, không dùng framework agent có sẵn. Bot chỉ có đúng hai công cụ là **tìm web** và **đọc một trang**, không có terminal hay truy cập file, nên bề mặt rủi ro nhỏ.

---

## 1. Tính năng

- **Hỏi – đáp theo ngữ cảnh**: mỗi thread là một phiên riêng, giữ vài lượt gần nhất làm ngữ cảnh
- **Tìm kiếm web**: DuckDuckGo, **không cần API key**
- **Đọc trang**: tải trang và trích phần chữ chính, kèm giới hạn kích thước
- **Trả lời trong thread**: @mention thì bot tạo thread; thread được nhớ qua lần restart
- **Chọn LLM**: Google Gemini hoặc API kiểu Anthropic (kể cả gateway tương thích), đổi bằng một biến môi trường
- **Slash command**: `/reset` (xóa ngữ cảnh thread), `/help`
- **Cắt tin nhắn dài thông minh**: không làm vỡ code block khi vượt giới hạn 2000 ký tự của Discord
- **Giới hạn tốc độ** theo từng người dùng, **chặn SSRF** khi đọc trang
- **Biết ai là chủ bot** qua Discord User ID (không giả được bằng tên hiển thị)

---

## 2. Cách hoạt động

```text
Thành viên Discord
      │  @mention (hoặc tin nhắn trong thread của bot)
      ▼
  Discord Gateway ──websocket──>  Bot (discord.py)
                                    │
                                    ├─> Kiểm tra quyền, giới hạn tốc độ
                                    ├─> Tạo / dùng lại thread, nạp lịch sử thread
                                    │
                                    └─> LLM (Gemini hoặc Anthropic-compatible)
                                           │  gọi tool khi cần (tối đa N vòng)
                                           ├─> web_search  (DuckDuckGo)
                                           └─> read_page   (chặn SSRF)
                                           │
      ◄────────── phản hồi trong thread ───┘
```

Mỗi câu hỏi có thể làm LLM gọi tool vài vòng (mặc định tối đa 4). Hết số vòng mà chưa có đáp án, bot ép LLM trả lời bằng thông tin đã thu được.

Lịch sử hội thoại chỉ giữ **trong RAM** (câu hỏi và câu trả lời cuối, không giữ kết quả tool), nên restart là mất ngữ cảnh. Chỉ **danh sách ID thread** được lưu ra file.

---

## 3. Công nghệ

| Thành phần | Công nghệ |
|---|---|
| Ngôn ngữ | Python 3.12+ |
| Discord | discord.py 2.x |
| LLM | Google Gemini (REST) hoặc API kiểu Anthropic Messages |
| Tìm kiếm | DuckDuckGo qua `ddgs` |
| Đọc trang | `httpx` + `trafilatura` |
| Lưu trữ | RAM cho hội thoại, file JSON cho danh sách thread |
| Triển khai | Docker Compose |

---

## 4. Cài đặt

### Yêu cầu

- Docker và Docker Compose (hoặc Python 3.12+ nếu chạy trực tiếp)
- Một **Discord Bot Token**, tạo tại [Discord Developer Portal](https://discord.com/developers/applications)
- Khóa API của một LLM: Gemini, hoặc Anthropic-compatible

### Các bước

```bash
git clone https://github.com/devilc312/bot_searchDiscord.git
cd bot_searchDiscord

cp .env.example .env
# Mở .env, điền token và khóa API (xem phần 5)

docker compose up -d --build
docker logs -f searchbot
```

Thấy dòng `Đã đăng nhập: <tên bot>` là bot đã online.

<details>
<summary><b>Chạy trực tiếp bằng Python</b></summary>

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app
```

</details>

<details>
<summary><b>Chạy test</b></summary>

```bash
pip install -r requirements-dev.txt
pytest
```

</details>

---

## 5. Biến môi trường

| Biến | Bắt buộc | Mặc định | Ý nghĩa |
|---|:---:|---|---|
| `DISCORD_TOKEN` | ✅ | | Token bot (cũng nhận tên `DISCORD_BOT_TOKEN`) |
| `LLM_PROVIDER` | | `gemini` | `gemini` hoặc `anthropic` |
| `GEMINI_API_KEY` | khi dùng Gemini | | Khóa Google AI Studio |
| `GEMINI_MODEL` | | `gemini-3.8-flash` | Tên model Gemini |
| `ANTHROPIC_BASE_URL` | khi dùng Anthropic | | Địa chỉ API hoặc gateway |
| `ANTHROPIC_AUTH_TOKEN` | khi dùng Anthropic | | Gửi dạng `Authorization: Bearer` |
| `ANTHROPIC_MODEL` | khi dùng Anthropic | | Tên model gateway chấp nhận |
| `OWNER_ID` | | | Discord User ID của chủ bot |
| `ALLOWED_USER_IDS` | | trống = mọi người | Danh sách User ID được dùng, ngăn cách bằng dấu phẩy |
| `ALLOWED_CHANNEL_IDS` | | trống = mọi kênh | Chỉ trả lời ở các kênh này (kể cả thread của chúng) |
| `HISTORY_TURNS` | | `6` | Số cặp hỏi – đáp giữ làm ngữ cảnh mỗi thread |
| `MAX_TOOL_ROUNDS` | | `4` | Số vòng gọi tool tối đa mỗi câu hỏi |
| `RATE_LIMIT_PER_MIN` | | `5` | Số câu hỏi mỗi người mỗi phút |
| `DATA_DIR` | | `data` | Nơi lưu danh sách thread (trong Docker là volume `/data`) |

> **Không bao giờ commit file `.env`.** `.gitignore` đã chặn sẵn.

---

## 6. Mời bot vào server

1. Mở [Discord Developer Portal](https://discord.com/developers/applications) → chọn application
2. Vào **Bot** → bật **Message Content Intent** (thiếu cái này bot không đọc được tin nhắn)
3. Bấm **Reset Token** và copy token (chỉ hiện một lần)
4. Vào **OAuth2 → URL Generator**, chọn scope `bot` và `applications.commands`
5. Chọn quyền: `Send Messages`, `Read Message History`, `Create Public Threads`, `Send Messages in Threads`
6. Mở URL vừa sinh ra và chọn server để mời bot vào

Lấy User ID của bạn: Discord → Settings → Advanced → bật Developer Mode, rồi chuột phải vào tên mình → Copy User ID.

---

## 7. Bảo mật

- **Chỉ có hai tool**: tìm web và đọc trang. Không có terminal, file hay lệnh hệ thống, nên dù model bị dụ cũng không làm hại được máy chủ.
- **Chặn SSRF**: `read_page` từ chối `localhost`, mạng nội bộ, link-local, CGNAT, endpoint metadata cloud, URL có `user:pass@`, và host phân giải ra IP nội bộ. Mỗi lần redirect được kiểm tra lại. *Giới hạn đã biết*: vẫn còn khe hở DNS rebinding.
- **Prompt injection**: system prompt dặn model coi nội dung web là dữ liệu. Đây chỉ là chỉ dẫn cho model, không phải khóa cứng. Vì bot không có tool nguy hiểm nên hậu quả bị giới hạn ở câu trả lời sai.
- **Nhãn chủ bot** dựa trên User ID do Discord gắn, không phải tên hiển thị. Nhãn này chỉ là thông tin cho model, không mở thêm quyền nào.
- Lỗi trả cho người dùng là câu thân thiện; chi tiết (kể cả phản hồi từ nhà cung cấp) chỉ nằm trong log và không chứa khóa.
- Container chạy bằng user thường, hệ thống file chỉ đọc, bỏ hết capability.
- Mọi câu hỏi đi qua nhà cung cấp LLM bạn chọn. Nếu dùng gateway bên thứ ba, họ thấy nội dung câu hỏi.
- **Chi phí**: nếu để mọi người dùng bot thì bạn trả tiền API cho mọi câu hỏi. Dùng `ALLOWED_USER_IDS`, `RATE_LIMIT_PER_MIN` và đặt hạn mức chi tiêu ở nhà cung cấp.

---

## 8. Lỗi thường gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| Bot online nhưng không trả lời | Chưa bật Message Content Intent, hoặc không có quyền tạo thread | Bật intent / cấp quyền, restart |
| "Hết quota hoặc bị giới hạn tốc độ" | HTTP 429 từ nhà cung cấp. Gemini free tier chỉ cho vài chục request mỗi ngày mỗi model | Bật billing hoặc đổi nhà cung cấp |
| "Model không tồn tại hoặc đã bị ngừng" | HTTP 404 | Đổi `GEMINI_MODEL` / `ANTHROPIC_MODEL` |
| "Khóa API bị từ chối" | HTTP 401/403 | Kiểm tra khóa |
| "Dịch vụ AI trả về dữ liệu không hợp lệ" | Gateway trả định dạng lạ | Xem log |
| Search trả lỗi hoặc trống | DuckDuckGo chặn khi bị gọi nhiều từ một IP | Giảm tần suất hoặc thay backend search |

Mỗi câu hỏi tốn **2 đến 5 request** LLM (suy nghĩ, tìm, đọc, tổng hợp), nên free tier hết nhanh.

---

## 9. Cấu trúc dự án

```text
.
├── app/
│   ├── __main__.py      # Entry point
│   ├── bot.py           # Client Discord: @mention, thread, slash command
│   ├── llm.py           # Gemini + Anthropic-compatible, vòng lặp tool, ghép SSE
│   ├── tools.py         # web_search, read_page
│   ├── urlsafety.py     # Chặn SSRF
│   ├── splitter.py      # Cắt tin dài, giữ nguyên code block
│   ├── store.py         # Lưu danh sách thread (ghi nguyên tử)
│   ├── history.py       # Lịch sử hội thoại theo thread (RAM)
│   ├── ratelimit.py     # Giới hạn tốc độ theo người dùng
│   ├── config.py        # Đọc biến môi trường
│   └── prompt.py        # System prompt
├── tests/               # pytest
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── requirements-dev.txt
```

---

## Giấy phép

MIT. Xem [LICENSE](LICENSE).

<div align="center">
<sub>Xây dựng bởi <a href="https://github.com/devilc312">@devilc312</a></sub>
</div>
