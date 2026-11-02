# MediaMTX Dashboard – Backend (FastAPI)

Backend untuk memantau dan mengelola server MediaMTX. Frontend nanti cukup memanggil endpoint di sini.

## Struktur

```
mediamtx-dashboard-backend/
├── .env.example          contoh pengaturan (salin jadi .env)
├── requirements.txt
└── app/
    ├── main.py           titik masuk aplikasi, CORS, penanganan error
    ├── config.py         membaca .env
    ├── mediamtx_client.py  penghubung ke API MediaMTX + versi mock
    ├── mock_data.py      data tiruan (USE_MOCK=true)
    ├── schemas.py        bentuk data request/respons
    ├── responses.py      format { success, data, message }
    ├── deps.py
    └── routers/
        ├── server.py     health & konfigurasi global
        ├── streams.py    monitoring stream
        ├── paths.py      tambah/ubah/hapus path (kamera)
        └── sessions.py   daftar & putus koneksi klien
```

## Menjalankan (Windows)

```bat
cd D:\Project\mediamtx-dashboard-backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

Lalu buka **http://localhost:8000/docs**: semua endpoint bisa dicoba langsung dari situ (klik endpoint → *Try it out* → *Execute*).

Pastikan `mediamtx.exe` sedang berjalan dengan `api: yes`. Kalau ingin mencoba tanpa MediaMTX, ubah `USE_MOCK=true` di `.env`.

## Mode Docker Compose

File default `docker-compose.yml` memakai bridge network. Dashboard mengakses MediaMTX melalui `http://mediamtx:9997` dan tersedia pada port 8000:

```sh
docker compose up -d
```

Untuk membaca metrik sistem host, gunakan konfigurasi host network:

```sh
docker compose -f docker-compose.host.yml up -d
```

Mode host menjalankan dashboard dan Node Exporter di host network. Mode ini memakai `127.0.0.1:9997` untuk MediaMTX dan `127.0.0.1:9100` untuk Node Exporter. Untuk kembali ke bridge mode, jalankan `docker compose up -d --remove-orphans`.

## Endpoint

| Method | URL | Fungsi |
|---|---|---|
| GET | `/api/server/health` | Cek MediaMTX terhubung atau tidak |
| GET | `/api/server/config` | Konfigurasi global MediaMTX |
| PATCH | `/api/server/config` | Ubah konfigurasi global (tanpa restart) |
| GET | `/api/config/path-defaults` | Membaca konfigurasi default path dari MediaMTX v3 |
| PATCH | `/api/config/path-defaults` | Mengubah konfigurasi default path di runtime MediaMTX |
| GET | `/api/streams` | Daftar stream: online/offline, penonton, trafik, URL tonton |
| GET | `/api/streams/summary` | Angka ringkas untuk kartu statistik |
| GET | `/api/streams/{name}` | Detail satu stream |
| GET | `/api/paths` | Daftar konfigurasi path |
| POST | `/api/paths` | Tambah path/kamera |
| GET | `/api/paths/{name}` | Detail konfigurasi path |
| PATCH | `/api/paths/{name}` | Ubah path |
| DELETE | `/api/paths/{name}` | Hapus path |
| GET | `/api/sessions` | Semua koneksi aktif (RTSP, WebRTC, RTMP, SRT) |
| POST | `/api/sessions/{type}/{id}/kick` | Putus koneksi satu klien |

Contoh body untuk menambah kamera IP:

```json
{
  "name": "kamera-1",
  "source": "rtsp://admin:admin@192.168.1.20:554/stream1",
  "source_on_demand": true
}
```

Untuk stream yang dikirim dari OBS/FFmpeg, cukup `{"name": "kamera-1"}` (source default `publisher`).

## Format respons

Berhasil:
```json
{ "success": true, "data": [...], "message": "2 stream" }
```
Gagal:
```json
{ "success": false, "data": null, "message": "MediaMTX tidak bisa dihubungi ..." }
```

## Catatan

- Password di URL kamera disamarkan (`rtsp://admin:***@...`) saat ditampilkan, agar tidak bocor ke browser.
- Path yang ditambah lewat API hanya tersimpan di memori MediaMTX dan hilang saat MediaMTX di-restart. Untuk path permanen, tulis juga di `mediamtx.yml` atau simpan ke database lalu daftarkan ulang saat backend start (rencana tahap berikutnya).
- Belum ada login. Tahap berikutnya: autentikasi JWT.
