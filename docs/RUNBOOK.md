# Runbook – sự cố đã gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| `HTTP 404 ModelNotOpen ... has not activated the model X` | Model chưa kích hoạt trên tài khoản Ark | Kích hoạt trong Ark Console nếu có trong danh sách; không thì đổi model theo `docs/MODELS.md` |
| `HTTP 404 InvalidEndpointOrModel.NotFound` | Sai ID model | Tra `docs/MODELS.md` hoặc `tools/ark.py ping --all` |
| `HTTP 502 upstream request failed` sau đúng ~30 s | Proxy chèn khóa của Claude cloud cắt request đồng bộ > 30 s (ảnh pro, ảnh 4K) | Không thử lại (có thể đã bị tính phí). Giảm `--size`, dùng `--fast`, hoặc chạy qua Lambda (`lambda/README.md`). Báo Anthropic để nâng giới hạn – mẫu báo cáo bên dưới |
| Video ra vuông dù `--resolution 720p` | Ảnh đầu vào vuông, `ratio=adaptive` | Truyền `--ratio 16:9` (model sẽ crop) hoặc dùng ảnh 16:9 |
| `ModuleNotFoundError: rembg` / thiếu font CJK | Hook khởi động chưa chạy hoặc lỗi | `CLAUDE_CODE_REMOTE=true .claude/hooks/session-start.sh` |
| Connector (AWS, Drive…) báo cần đăng nhập lại, sau khi đăng nhập vẫn không có tool | Phiên đã gỡ server khi lỗi xác thực, không nạp lại giữa chừng | Commit/push công việc, mở **phiên mới** |
| Plugin GitHub lỗi `Authorization header is badly formatted` | Lỗi kết nối plugin | Không ảnh hưởng clone/push (đi qua git proxy); kết nối lại plugin trong cài đặt nếu cần GitHub API |

## Mẫu báo cáo giới hạn 30 s cho Anthropic
> Claude Code on the web: requests to a host using proxy-injected credentials (`ark.ap-southeast.bytepluses.com`)
> are cut at ~30 s with `HTTP 502 upstream request failed`. Requests under ~26 s succeed; every request over 30 s
> fails at 30.1 s (reproduced with 3 different payloads). `/__agentproxy/status` shows no `recentRelayFailures`.
> The upstream API (synchronous image generation) legitimately takes 30–60 s. Please raise or make configurable
> the upstream timeout for injected-credential hosts.
