# formats/

Định dạng cinecode đã lưu (`tools/formats.py save ...`). Hook khởi động đặt `CINECODE_FORMATS` trỏ vào thư mục này
để định dạng không mất khi container bị thu hồi (mặc định cinecode lưu ở `~/.cinecode/formats`).

Dùng: `python3 <KIT>/scripts/init_film.py . --quick --format "<tên>"`. Chỉ commit định dạng đã được người dùng duyệt.
