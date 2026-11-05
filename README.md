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
| GET | `/api/streams/{name}/viewers` | Jumlah pembaca lintas protokol dan 60 sampel riwayat; polling halaman detail setiap 5 detik |
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
  "sourceOnDemand": true
}
```

Field opsional lainnya memakai nama MediaMTX: `sourceOnDemandStartTimeout`, `sourceOnDemandCloseAfter`, `maxReaders`, dan `sourceRedirect`.

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

# MediaMTX Dashboard – Backend (FastAPI)

Backend untuk memantau dan mengelola server MediaMTX. Frontend nanti cukup memanggil endpoint di sini.

## Struktur

```
mediamtx-dashboard-backend/
├── .env.example          contoh pengaturan (salin jadi .env)
├── .env                  konfigurasi pengembangan (salin dari .env.example)
├── LOGIN_SETUP.md        panduan lengkap autentikasi JWT
├── README.md (Anda sedang melihatnya)  dokumentasi autentikasi
├── requirements.txt
└── app/
    ├── main.py           titik masuk aplikasi, CORS, penanganan error
    ├── config.py         membaca .env
    ├── deps.py
    ├── mediamtx_client.py  penghubung ke API MediaMTX + versi mock
    ├── mock_data.py      data tiruan (USE_MOCK=true)
    ├── responses.py      format { success, data, message }
    ├── schemas.py        bentuk data request/respons
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
| POST | `/api/login` | Autentikasi pengguna dan dapatkan JWT cookie |
| POST | `/api/logout` | Hapus JWT cookie dan logout |

Contoh body untuk menambah kamera IP:

```json
{
  "name": "kamera-1",
  "source": "rtsp://admin:admin@192.168.1.20:554/stream1",
  "sourceOnDemand": true
}
```

Field opsional lainnya memakai nama MediaMTX: `sourceOnDemandStartTimeout`, `sourceOnDemandCloseAfter`, `maxReaders`, dan `sourceRedirect`.

Untuk stream yang dikirim dari OBS/FFmpeg, cukup `{"name": "kamera-1"}` (source default `publisher`).

## Autentikasi JWT

### 1. Gambaran Umum

MediaMTX Dashboard menggunakan JWT (JSON Web Token) untuk autentikasi. Semua endpoint API (kecuali `/api/login` dan `/api/logout`) memerlukan autentikasi yang valid.

### 2. Konfigurasi

Autentikasi diatur melalui variabel lingkungan di `.env`:

```env
AUTH_USERNAME=admin
AUTH_PASSWORD=admin
JWT_SECRET=YOUR_STRONG_RANDOM_SECRET_HERE
JWT_EXPIRE_MINUTES=480
JWT_SECURE_COOKIE=false
```

- **`AUTH_USERNAME`**: Username admin (default: "admin")
- **`AUTH_PASSWORD`**: Password admin (default: "admin")
- **`JWT_SECRET`**: Secret untuk menandatangani JWT (wajib diisi, minimal 32 karakter)
- **`JWT_EXPIRE_MINUTES`**: Waktu kadaluarsa token dalam menit (default: 480 menit = 8 jam)
- **`JWT_SECURE_COOKIE`**: Set `Secure` flag pada cookie (hanya untuk HTTPS, default: false)

### 3. Mulai Aplikasi

```bash
# Pertama, salin .env.example ke .env dan sesuaikan isinya
mv .env.example .env
# Edit .env dan isi JWT_SECRET dengan secret acak yang kuat

# Generate JWT secret (recommended):
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Install dependencies dan jalankan
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 4. Mengakses Frontend

1. Buka browser dan navigasi ke `http://localhost:8000`
2. Anda akan diarahkan ke halaman login
3. Masuk dengan kredensial admin (sesuaikan dengan `.env` Anda)
4. Dashboard akan dimuat setelah login berhasil

### 5. API Autentikasi

#### Login (`POST /api/login`)

```bash
curl -X POST http://localhost:8000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' \
  -c cookies.txt
```

Response:
```json
{
  "success": true,
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "expires_in": 28800
  },
  "message": "Login successful"
}
```

Token JWT disimpan sebagai cookie `access_token` dengan atribut:
- `HttpOnly`: Benar (tidak bisa diakses JavaScript)
- `SameSite`: Lax
- `max-age`: Waktu kadaluarsa (dalam detik)

#### Logout (`POST /api/logout`)

```bash
curl -X POST http://localhost:8000/api/logout \
  -b cookies.txt
```

Response:
```json
{
  "success": true,
  "data": null,
  "message": "Logged out successfully"
}
```

#### Memverifikasi Token (Semua Endpoint Lain)

Semua endpoint API (kecuali `/api/login` dan `/api/logout`) memerlukan cookie `access_token` yang valid. Contoh:

```bash
curl -X GET http://localhost:8000/api/server/health \
  -b cookies.txt
```

Jika token tidak valid/kadaluarsa/hilang, Anda akan mendapatkan respons:
```json
{
  "success": false,
  "data": null,
  "message": "Not authenticated" atau "Token expired" atau "Invalid authentication credentials"
}
```

### 6. Frontend Autentikasi

Frontend secara otomatis menangani autentikasi:

1. **Routing**: Semua halaman dashboard dilindungi dan akan mengarahkan ke halaman login jika tidak terautentikasi
2. **Auto-refresh**: Token yang valid disimpan di browser dan dikirim secara otomatis dengan setiap permintaan API
3. **Timeout**: Pengguna diarahkan ke halaman login ketika token kadaluarsa
4. **Manual Logout**: Klik tombol "Logout" (bila tersedia) atau gunakan tombol keluar di sidebar

### 7. Keamanan

- **Cookie HttpOnly**: Token disimpan di cookie HttpOnly, melindungi dari XSS
- **SameSite=Lax**: Mencegah CSRF pada subdomain yang sama
- **Masa Kadaluarsa**: Token memiliki waktu kadaluarsa yang dapat dikonfigurasi
- **HTTPS**: Gunakan `JWT_SECURE_COOKIE=true` untuk produksi HTTPS
- **Secret**: JWT_SECRET harus dijaga kerahasiaannya dan tidak boleh disimpan di Git

### 8. Dokumentasi Tambahan

Lihat `LOGIN_SETUP.md` untuk panduan lengkap tentang konfigurasi, penggunaan, dan pemecahan masalah autentikasi JWT.

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
- Autentikasi JWT sudah diaktifkan. Lihat `LOGIN_SETUP.md` untuk panduan.