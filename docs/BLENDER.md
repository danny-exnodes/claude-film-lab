# Blender + GPU cục bộ cho sinh vật cận cảnh

Hướng mới (2026-11): cận cảnh sinh vật dựng và render bằng **Blender Cycles trên GPU NVIDIA của người dùng**, không dùng
model ảnh/video trả phí. Cảnh rộng/môi trường vẫn có thể dùng `film3d` (three.js) chạy trên trình duyệt có GPU.

Lý do: độ thật của sinh vật nằm ở asset (hình khối điêu khắc/quét, texture, lông chải, shader tóc/lông, SSS), không ở máy
render. 3D thủ tục bằng three.js chạm trần ở da/lông/đá cận cảnh (xem báo cáo q01t03). Cycles có Principled Hair BSDF,
tán xạ dưới da thật, path tracing; Geometry Nodes cho lông vũ có sợi tơ thật.

Máy tham chiếu của người dùng: **RTX 5080 16 GB** (Windows). Đo trên xưởng web (`film3d/studio.html`, s13):
57 ms/khung 1920×1080 spp 8; 229 ms/khung 3840×2160 spp 16.

## 1. Phiên Claude trên PC (bắt buộc cho MCP)
Phiên Claude Code cloud **không** với tới máy người dùng; MCP for Blender nói chuyện qua socket `localhost`, nên phải chạy
trong phiên Claude trên chính PC đó:
- App **Claude Desktop** (có Claude Code), hoặc Claude Code CLI trong terminal ở thư mục làm việc.
- Thư mục làm việc: bản clone repo này (nhánh đang dùng) + `projects/<project>/` kéo từ Drive như mọi phiên.

## 2. Blender + MCP for Blender
1. Cài **Blender 5.2 LTS** (blender.org). Script mẫu của lab viết cho 5.2 (bpy 5.2.4).
2. Cài `uv`: `winget install --id=astral-sh.uv -e`, mở terminal mới.
3. Cài addon: `uvx mcp-for-blender setup` (tự chép và bật addon). Cách tay: Edit → Preferences → Add-ons → Install… file
   `addon.py` của repo `ahujasid/blender-mcp`, bật "Interface: MCP for Blender".
4. Trong Blender: phím N ở viewport → tab "MCP for Blender" → **Start MCP Server**.
5. Nối Claude:
   - Claude Code: `claude mcp add blender uvx mcp-for-blender`
   - Claude Desktop (`claude_desktop_config.json`): `{"mcpServers": {"blender": {"command": "uvx", "args": ["mcp-for-blender"]}}}`
     (nếu app không tìm thấy `uvx`: `"command": "cmd", "args": ["/c", "uvx", "mcp-for-blender"]`).
6. Cycles: Edit → Preferences → System → Cycles Render Devices → **OptiX**, tích RTX 5080.

An toàn: socket của addon **không có xác thực** – ai với tới cổng đều chạy được Python trong Blender. Chỉ để `localhost`,
không mở ra mạng. Lưu file `.blend` trước khi cho Claude thao tác. Tích hợp Hunyuan3D có sẵn trong addon là **API đám mây
Tencent (có phí)** – lab không dùng; dùng Hunyuan3D chạy local (mục 3).

## 3. Hunyuan3D chạy local (tạo model + texture từ ảnh, miễn phí)
| Bản | VRAM | Ghi chú |
|---|---|---|
| **Hunyuan3D-2 (2.0)** | 6 GB hình khối; **16 GB** hình khối + texture | Vừa 16 GB (sát giới hạn; dùng `--low_vram_mode`). Có `api_server.py` và `blender_addon.py`. Texture RGB (chưa PBR). |
| Hunyuan3D-2.1 | 10 GB hình khối; 21 GB texture PBR; 29 GB cả hai | Texture PBR đẹp hơn nhưng **không vừa 16 GB** nếu chạy cùng lúc; tách hai bước + `--low_vram_mode`, có thể vẫn thiếu. |

Bắt đầu bằng **2.0**. Cài (Python 3.10, venv riêng):
```
git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2 && cd Hunyuan3D-2
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128   # RTX 50 (Blackwell) cần bản CUDA 12.8 trở lên
pip install -r requirements.txt && pip install -e .
cd hy3dgen/texgen/custom_rasterizer && python setup.py install && cd ../../..
cd hy3dgen/texgen/differentiable_renderer && python setup.py install && cd ../../..
python api_server.py --host 127.0.0.1 --port 8080        # chỉ localhost
```
- README của Tencent chỉ thử với cu124; RTX 50 cần PyTorch build cu128 (suy luận của lab, kiểm khi cài). Hai phần mở rộng
  CUDA cần Visual Studio Build Tools (C++) + CUDA Toolkit 12.8 trên Windows. Nếu build lỗi: dùng bản gói sẵn cho Windows
  mà README liệt kê, hoặc WSL2 Ubuntu.
- Trong Blender: cài `blender_addon.py` của repo Hunyuan3D-2, trỏ tới `http://127.0.0.1:8080`, hoặc tạo bằng `gradio_app.py`
  rồi import `.glb`.
- Đọc file LICENSE của repo trước khi dùng thương mại (giấy phép cộng đồng của Tencent, có điều khoản theo lãnh thổ).
- Ảnh đầu vào: ảnh con vật thật có giấy phép dùng được hoặc tranh cổ thuộc phạm vi công cộng; ghi nguồn vào `research.md`.
  Hunyuan3D hợp với **thân/đầu**; lông vũ thì để Geometry Nodes của script lab chải.

## 4. Quy trình đề xuất cho một sinh vật
1. Thân/đầu: Hunyuan3D (ảnh tham chiếu) → làm sạch, retopo/remesh trong Blender → armature.
2. Lông/lông vũ: script lab (Geometry Nodes, curves) mọc trên thân theo vùng lông (vertex group).
3. Shader: Principled BSDF/Hair BSDF, SSS cho da mặt, coat cho mỏ, giác mạc khúc xạ.
4. Render Cycles OptiX, khử nhiễu OptiX/OIDN; xuất chuỗi EXR/PNG hoặc MP4 → ghép như các tập 3D code.
5. Mọi file `.blend`, `.glb`, texture, script riêng của tập là **dữ liệu dự án** (Drive + `projects/`), không commit.

## 5. Kiểm script trên cloud
Phiên cloud có thể chạy `bpy` 5.2.4 (pip, Python 3.13) để kiểm script bằng CPU ở độ phân giải/số mẫu thấp trước khi gửi
người dùng; render thật chỉ trên GPU của người dùng.
