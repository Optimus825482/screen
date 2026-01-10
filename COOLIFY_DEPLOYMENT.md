# 🚀 ScreenShare Pro - Coolify Deployment Guide

## Tek Container Deployment (All-in-One)

Bu yapılandırma PostgreSQL, Redis ve FastAPI uygulamasını **tek container** içinde çalıştırır.

---

## 📋 Coolify Ayarları

### 1. Yeni Uygulama Oluştur

1. Coolify Dashboard → **New Resource** → **Application**
2. **Git Repository** seç ve repo URL'ini gir
3. **Branch**: `main` (veya kullandığın branch)

### 2. Build Ayarları

| Ayar                    | Değer                |
| ----------------------- | -------------------- |
| **Build Pack**          | Dockerfile           |
| **Dockerfile Location** | `Dockerfile.coolify` |
| **Base Directory**      | `/` (root)           |

### 3. Environment Variables

Coolify'da **Environment Variables** bölümüne şunları ekle:

```env
# ZORUNLU - Güvenlik
JWT_SECRET=<32+ karakter güvenli string>

# Domain
PUBLIC_URL=https://screen.erkanerdem.net
CORS_ORIGINS=["https://screen.erkanerdem.net"]

# TURN Server (WebRTC için)
METERED_API_KEY=a2278584590ae2fd0bf60959fe0fecb7e3a7
METERED_API_URL=https://erkan.metered.live/api/v1/turn/credentials?apiKey=a2278584590ae2fd0bf60959fe0fecb7e3a7
TURN_USERNAME=f84d8ab3c68f3086725cd296
TURN_CREDENTIAL=4zGaofkudqEZZ6uf

# Admin
ADMIN_EMAIL=admin@erkanerdem.net

# Debug (production'da false)
DEBUG=false
```

### 4. Network Ayarları

| Ayar       | Değer                 |
| ---------- | --------------------- |
| **Port**   | 8005                  |
| **Domain** | screen.erkanerdem.net |
| **HTTPS**  | ✅ Enabled            |

### 5. Storage (Persistent Volumes)

Coolify'da **Persistent Storage** ekle:

| Mount Path                 | Açıklama            |
| -------------------------- | ------------------- |
| `/var/lib/postgresql/data` | PostgreSQL verileri |
| `/var/lib/redis`           | Redis verileri      |
| `/app/logs`                | Uygulama logları    |

---

## 🔐 JWT Secret Oluşturma

Terminal'de çalıştır:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Veya:

```bash
openssl rand -base64 32
```

---

## ✅ Deployment Sonrası Kontrol

### Health Check

```bash
curl https://screen.erkanerdem.net/health
```

Beklenen yanıt:

```json
{
  "status": "healthy",
  "service": "ScreenShare Pro",
  "redis": { "redis_connected": true }
}
```

### Admin Girişi

1. `https://screen.erkanerdem.net/login` adresine git
2. Kullanıcı adı: `admin`
3. Şifre: Container loglarında görünecek (ilk başlatmada)

**ÖNEMLİ**: İlk girişte şifre değiştirmeniz istenecek!

---

## 🔧 Troubleshooting

### Logları Görüntüle

Coolify Dashboard → Application → **Logs**

### Container'a Bağlan

```bash
docker exec -it <container_id> bash
```

### Servisleri Kontrol Et

```bash
supervisorctl status
```

### PostgreSQL'e Bağlan

```bash
docker exec -it <container_id> psql -U postgres -d screenshare
```

### Redis'e Bağlan

```bash
docker exec -it <container_id> redis-cli
```

---

## 📊 Resource Önerileri

| Resource | Minimum | Önerilen |
| -------- | ------- | -------- |
| CPU      | 1 core  | 2 cores  |
| RAM      | 512MB   | 1GB      |
| Disk     | 5GB     | 10GB     |

---

## 🔄 Güncelleme

1. Kodu push et
2. Coolify'da **Redeploy** tıkla
3. Persistent volume'lar korunur

---

## ⚠️ Önemli Notlar

1. **JWT_SECRET** production'da mutlaka değiştir!
2. **TURN credentials** WebRTC için gerekli - metered.ca'dan al
3. İlk deployment'ta admin şifresi loglarda görünür
4. Persistent volume'lar olmadan veriler kaybolur!
