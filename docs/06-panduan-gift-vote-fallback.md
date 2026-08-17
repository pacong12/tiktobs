# Panduan: Vote Gift via Komentar Terakhir (Gift Fallback)

Panduan praktis untuk operator/streamer. Untuk detail teknis lengkap lihat
`docs/05-gift-voting-fallback.md`.

---

## 1. Apa fitur ini?

Saat polling berjalan, penonton bisa vote dengan dua cara:

1. **Komentar** — ketik nomor kandidat (`01`, `02`, …), ID, atau nama.
2. **Gift** — nilai diamond gift dikonversi jadi vote: **1 diamond = 1 vote**.

Biasanya gift hanya dihitung jika **cocok dengan gift yang ditugaskan** ke
kandidat di Poll Admin. Masalahnya, banyak penonton mengirim gift populer
(Rocket, Universe, dll.) yang tidak ada di daftar gift kandidat — dan selama
ini gift itu hangus tanpa feedback.

Dengan fitur **fallback komentar**, gift seperti itu tidak lagi hangus:

> Jika pengirim gift **pernah komentar vote** di ronde polling yang sedang
> berjalan, gift-nya dihitung untuk kandidat yang dia pilih lewat **komentar
> terakhirnya**.

Fitur ini **selalu aktif** setiap polling berjalan (tidak ada toggle).

---

## 2. Cara kerjanya (3 langkah)

```
1. Penonton komentar "02"  ──►  vote +1 untuk kandidat 02
                                 sistem mencatat: "@sultan → kandidat 02"

2. @sultan kirim Rocket    ──►  Rocket bukan gift kandidat mana pun
   (5000 diamond)               sistem cek catatan @sultan → ada: "02"
                            ──►  Rocket dihitung untuk kandidat 02
                                 +5000 vote (1 diamond = 1 vote)

3. Tanpa komentar vote     ──►  gift TIDAK dihitung untuk siapa pun
                                 penonton diberi tahu di layar
```

Aturan penting:

- Hanya komentar **selama ronde polling aktif** yang berlaku (komentar sebelum
  polling di sesi yang sama tetap dihitung lewat replay riwayat).
- Komentar vote **terakhir** yang menang. Komentar iseng ("wkwkwk", "halo")
  tidak menghapus pilihan sebelumnya.
- Gift yang **langsung cocok** dengan gift kandidat tetap dihitung normal —
  fallback hanya dipakai kalau gift tidak cocok ke kandidat mana pun.
- Aman setelah restart aplikasi — catatan pilihan penonton tersimpan.

---

## 3. Tabel skenario

| Penonton | Komentar di ronde ini | Gift yang dikirim | Hasil |
|:---|:---|:---|:---|
| @sultan | `02` | Rocket (5000 💎) | **+5000 vote** untuk kandidat 02 ✅ |
| @sultan | `02`, lalu `01` | Galaxy | Dihitung langsung: Galaxy milik kandidat 01 (match langsung, tanpa fallback) ✅ |
| @sultan | `02`, lalu `wkwkwk` | Rose | Dihitung langsung (Rose milik kandidat pemiliknya) ✅ |
| @budi | `01` | Universe (2000 💎) | **+2000 vote** untuk kandidat 01 ✅ (via komentar `01`) |
| @rara | (tidak ada) | Rocket | **Tidak dihitung** ⚠️ — layar menampilkan peringatan |
| @sultan | (ronde sebelumnya `01`) | Rocket | **Tidak dihitung** ⚠️ — komentar ronde lama tidak berlaku; harus komentar lagi di ronde baru |
| @sultan | `02` | Polling sudah selesai | Gift tercatat biasa, bukan vote |

---

## 4. Apa yang harus dilakukan operator

### a. Siapkan polling seperti biasa

Di Poll Admin (`/poll-admin.html`): isi kandidat + **gift boost** bila ada.
Tidak ada pengaturan tambahan — fallback otomatis aktif saat polling mulai.

### b. Bacakan cara vote ke penonton (template)

> "Cara vote: komentar nomor kandidat, contoh **01** atau **02**. Mau dukung
> pakai gift? Bebas! Kirim gift apa saja **setelah komentar nomornya** — nilai
> diamond-nya dihitung penuh untuk kandidat pilihanmu. Kalau langsung kirim
> gift tanpa komentar, gift-nya tidak dihitung ya!"

### c. Perhatikan layar

Saat polling berjalan, tiga lapisan feedback muncul otomatis:

| Tempat | Vote biasa (gift cocok) | Vote fallback (via komentar) | Gift tak dihitung |
|:---|:---|:---|:---|
| **Overlay voting** (`/vote-overlay.html`) | Toast combo `🌹 Rose ×N → Kandidat` | Toast emas: `Rocket +5000 → Bob · via komentar "02"` | Banner merah 5 detik: "⚠️ Rocket dari @rara **tidak dihitung** — komentar nomor/nama kandidat dulu, baru gift!" |
| **Alert gift** (`/vote-gift-alert.html`) | Alert emas + suara 🎉 | Alert emas + suara + badge `via last comment: "02"` | Kartu merah `+0 VOTES` tanpa suara, dengan panduan |
| **Gift Bubbles** (`/gift-bubbles.html`) | Bubble emas di kartu kandidat | Bubble emas di kartu kandidat yang dikredit | Bubble merah berisi **foto profil pengirim** + badge ❌ (gift tetap terlihat, tapi jelas tidak dihitung) |
| **Poll Admin** (`/poll-admin.html`) | Toast vote masuk | Toast: `🎁 Rocket dari @sultan → Bob (+5000 via komentar terakhir: "02")` | Toast peringatan kuning: gift diabaikan |

Jadi kalau ada penonton protes "gift-ku tidak masuk", operator bisa langsung
lihat alasannya di Poll Admin/overlay: hampir selalu karena dia belum
komentar nomor kandidat di ronde itu.

### d. Setelah polling baru dimulai

Ingatkan lagi: pilihan dari ronde sebelumnya tidak dibawa. Penonton harus
komentar lagi di ronde baru sebelum gift-nya bisa dihitung via fallback.

---

## 5. Setup OBS (scene browser source)

Tambahkan Browser Source untuk tiap overlay (URL dari server lokal, port
8000):

1. `http://127.0.0.1:8000/vote-overlay.html` — kartu polling utama (progress
   bar, peringkat) + toast fallback & banner gift tak dihitung. **Wajib ada.**
2. `http://127.0.0.1:8000/vote-gift-alert.html` — alert besar setiap gift
   vote (emas) / gift tak dihitung (merah). Opsional tapi sangat membantu.
3. `http://127.0.0.1:8000/gift-bubbles.html` — bubble ikon gift menempel di
   kartu kandidat. Opsional.
4. `http://127.0.0.1:8000/poll-admin.html` — buka di browser biasa (bukan
   OBS) untuk kontrol + monitoring toast.

Semua halaman otomatis reconnect kalau server restart.

---

## 6. FAQ

**Apakah bisa dimatikan?**
Tidak saat ini — fallback selalu aktif selama polling berjalan.

**Komentar sebelum polling dimulai ikut dihitung?**
Ya, selama masih di sesi live yang sama: saat polling mulai, riwayat event
sesi itu diputar ulang secara kronologis sehingga vote komentar (dan intent
untuk fallback) tetap terbentuk.

**Kalau kandidat punya gift yang sama?**
Tidak diizinkan — server menolak memulai polling dengan gift ganda, supaya
tidak ada gift yang diam-diam hanya menguntungkan satu kandidat.

**1 diamond = 1 vote untuk semua gift?**
Ya, baik match langsung maupun fallback. Minimum 1 vote.

**Gift combo/streak (Rose x99)?**
Dihitung sekali di akhir combo dengan total penuh (99 × harga satuan), lalu
aturan fallback yang sama berlaku.

**Kalau aplikasinya restart di tengah ronde?**
Aman. Status polling, vote, dan catatan pilihan penonton dipulihkan otomatis
dari database.

**Aman dari kecurangan (orang spam komentar lalu kirim gift murah)?**
Fallback justru membuat gift murah tetap berharga bagi pengirimnya sendiri —
nilainya masuk ke kandidat pilihannya. Tidak ada cara mendapat vote tanpa
mengirim gift atau komentar (komentar = 1 vote/komentar seperti biasa).

---

## 7. Troubleshooting

| Gejala | Penyebab umum | Solusi |
|:---|:---|:---|
| Gift penonton tidak masuk vote | Dia belum komentar vote di ronde ini | Tunjukkan banner/alert merah di layar; minta komentar nomor dulu |
| Gift masuk ke kandidat "salah" menurut penonton | Sistem mengikuti **komentar terakhirnya**, bukan tebak-tebakan | Jelaskan aturan "komentar terakhir yang menang" |
| Tidak ada toast/banner apa pun | Overlay belum ditambah di OBS, atau halaman belum dibuka | Cek Browser Source OBS; buka `/poll-admin.html` |
| Polling tidak jalan / overlay "Waiting for poll" | Polling belum dimulai atau koneksi live putus | Cek tombol Start di Poll Admin; cek status koneksi TikTokLive |
| Angka vote terasa tidak berubah | Gift dikirim saat polling tidak aktif | Vote hanya dihitung saat polling berjalan |

Log server (berguna untuk audit):

```bash
tail -f /tmp/tiktobs-server.log | grep -E "fallback|not counted|Gift vote"
```

Contoh baris:

```
Gift vote via comment fallback: 5000 votes added to Bob via gift 'Rocket' (sender @sultan last commented '02').
Gift 'Ice Cream' from @rara not counted: no matching candidate and no vote comment this round (poll 'Ronde 1' active).
```
