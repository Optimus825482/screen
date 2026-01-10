# 🚀 ScreenShare Pro - Coolify Docker Compose Deployment

## Buildpack: Docker Compose

3 servis çalışır: **PostgreSQL + Redis + FastAPI App**

---

## 📋 Coolify Ayarları

### 1. Yeni Uygulama Oluştur

1. Coolify Dashboard → **New Resource** → **Application**
2. **Git Repository** seç ve repo URL'ini gir
3. **Branch**: `main`

### 2. Build Ayarları

| Ayar                        | Değer                 |
| --------------------------- | --------------------- |
| **Build Pack**              | Docker Compose        |
| **Docker Compose Location** | `docker-compose.yaml` |

### 3. Environment Variables (Coolify'da ekle)

```env
# ZORUNLU
JWT_SECRET=<32+ karakter güvenli string>
POSTGRES_PASSWORD=screenshare2025

# Domain
PUBLIC_URL=https://screen.erkanerdem.net
CORS_ORIGINS=["https://screen.erkanerdem.net"]

# TURN Server (WebRTC)
METERED_API_KEY=a2278584590ae2fd0bf60959fe0fecb7e3a7
METERED_API_URL=https://erkan.metered.live/api/v1/turn/credentials
TURN_USERNAME=f84d8ab3c68f3086725cd296
TURN_CREDENTIAL=4zGaofkudqEZZ6uf

# Admin
ADMIN_EMAIL=admin@erkanerdem.net

# Debug
DEBUG=false
```

### 4. Network / Port

| Ayar             | Değer                 |
| ---------------- | --------------------- |
| **Exposed Port** | 8005 (api servisi)    |
| **Domain**       | screen.erkanerdem.net |

---

## 🔐 JWT Secret Oluştur

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## ✅ Health Check

```bash
curl https://screen.erkanerdem.net/health
```

---

## 📊 Servisler

| Servis | Port | Açıklama           |
| ------ | ---- | ------------------ |
| api    | 8005 | FastAPI uygulaması |
| db     | 5432 | PostgreSQL 15      |
| redis  | 6379 | Redis 7            |

---

## ⚠️ Önemli

1. **JWT_SECRET** production'da mutlaka değiştir
2. Coolify volume'ları otomatik yönetir
3. İlk deployment'ta admin şifresi loglarda görünür
