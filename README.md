# ScreenShare Pro

Web tabanlı ekran paylaşım platformu. Firewall arkasındaki kullanıcılarla bile sorunsuz ekran paylaşımı yapın.

## Özellikler

- WebRTC tabanlı gerçek zamanlı ekran paylaşımı
- Sesli iletişim desteği
- Anlık mesajlaşma
- JWT tabanlı güvenli kimlik doğrulama
- Firewall/NAT dostu (TURN sunucu desteği)
- Oda başına maksimum 5 izleyici

## Teknolojiler

### Backend

- Python 3.11+
- FastAPI
- PostgreSQL
- Redis
- SQLAlchemy 2.0 with AsyncConnectionPool

### Frontend

- HTML5/CSS3/JavaScript
- Tailwind CSS
- Alpine.js
- WebRTC API

## Kurulum

### Docker ile (Önerilen)

```bash
# Repo'yu klonla
git clone <repo-url>
cd screenshare-pro

# Environment dosyasını oluştur
cp .env.example .env
# .env dosyasını düzenle (özellikle JWT_SECRET!)

# Güvenli bir JWT_SECRET oluştur
python -c "import secrets; print(secrets.token_urlsafe(32))"

# .env dosyasına oluşturduğunuz secret'ı yapıştırın
# JWT_SECRET=<oluşturulan-secret>

# Docker ile başlat
docker-compose up -d
```

Uygulama http://localhost:8000 adresinde çalışacaktır.

### Manuel Kurulum

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# PostgreSQL ve Redis'in çalıştığından emin ol
# .env dosyasını oluştur

# Güvenli bir JWT_SECRET oluştur
python -c "import secrets; print(secrets.token_urlsafe(32))"

# .env dosyasına oluşturduğunuz secret'ı ekleyin:
# JWT_SECRET=<oluşturulan-secret>
# DEBUG=true

# Uygulamayı başlat
uvicorn app.main:app --reload
```

## API Endpoints

### Authentication

- `POST /api/auth/register` - Yeni kullanıcı kaydı
- `POST /api/auth/login` - Giriş (şifre değiştirme zorunluluğunu kontrol eder)
- `POST /api/auth/refresh` - Token yenileme
- `POST /api/auth/change-password` - Şifre değiştirme
- `GET /api/auth/me` - Kullanıcı bilgisi

### Rooms

- `POST /api/rooms` - Oda oluştur
- `GET /api/rooms` - Odalarımı listele
- `GET /api/rooms/{room_id}` - Oda detayı
- `GET /api/rooms/join/{invite_code}` - Odaya katıl
- `DELETE /api/rooms/{room_id}` - Odayı sonlandır

### WebSocket

- `/ws/room/{room_id}?token=<jwt>` - Oda iletişimi

## Lisans

MIT

## Güvenlik Notları

### JWT_SECRET Yönetimi (KRİTİK)

`JWT_SECRET` uygulamanın güvenliği için en kritik konfigürasyondur. Bu key olmadan JWT token'ları sahtelenebilir ve kullanıcı hesapları ele geçirilebilir.

**Production ortamında uygulama başlaması için JWT_SECRET zorunludur:**

- Production modunda (`DEBUG=false`) JWT_SECRET set edilmemişse uygulama başlamaz ve hata verir
- Development modunda (`DEBUG=true`) JWT_SECRET boş bırakılırsa otomatik olarak rastgele bir key oluşturulur (uyarı ile birlikte)

**Güvenli bir JWT_SECRET oluşturmak için:**

```bash
# Python ile
python -c "import secrets; print(secrets.token_urlsafe(32))"

# OpenSSL ile
openssl rand -base64 32

# Linux/Mac
cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 43 | head -n 1
```

**Kurallar:**
- Minimum 32 karakter uzunluğunda olmalı
- Rastgele ve tahmin edilemez olmalı
- Her ortam (dev, staging, prod) için farklı olmalı
- Asla kod içine commit edilmemeli
- Version control'de saklanmamalı (.env gitignore'da olmalı)

### API Key Yönetimi

Bu projede Metered TURN server için API key kullanılmaktadır. API key asla frontend kodunda saklanmamalıdır.

- API key sadece backend `.env` dosyasında saklanır
- Frontend, ICE konfigürasyonunu backend `/api/rooms/ice-config` endpoint'inden alır
- API key client-side JavaScript'ten tamamen kaldırılmıştır

### Production İçin Kontrol Listesi

Deploy öncesi aşağıdaki kontrolleri yapın:

- [ ] `.env` dosyasını production'a yüklemeyin (Environment variable olarak set edin)
- [ ] `JWT_SECRET` değerini güçlü ve rastgele bir key ile değiştirin
- [ ] `ADMIN_PASSWORD` değerini güçlü bir şifre ile ayarlayın (boş bırakılırsa rastgele oluşturulur ve log'a yazılır)
- [ ] `DEBUG=false` olarak ayarlayın
- [ ] `METERED_API_KEY` değerinizi https://www.metered.ca/ adresinden alın
- [ ] CORS ayarlarını production domain'lerinize göre güncelleyin (`CORS_ORIGINS`)
- [ ] `PUBLIC_URL`'i production domain'inize göre ayarlayın
- [ ] PostgreSQL ve Redis şifrelerini güçlendirin
- [ ] HTTPS/SSL sertifikası kullanın
- [ ] Rate limiting kurallarını configure edin

## Rate Limiting

Uygulama, API endpoint'leri ve WebSocket bağlantıları için rate limiting özelliği ile birlikte gelir. Bu özellik,滥用 saldırılarını önlemek ve kaynakları korumak için tasarlanmıştır.

### Rate Limit Özellikleri

- **Redis Backend Desteği**: Redis kullanılabilir olduğunda dağıtık rate limiting
- **In-Memory Fallback**: Redis kullanılamadığında otomatik olarak bellek içi rate limiting'e geçiş
- **Sliding Window Algorithm**: Hassas ve doğru rate limiting
- **Kullanıcı Bazlı Limitlendirme**: Kimlik doğrulanmış kullanıcılar ve IP bazlı limitlendirme

### API Endpoint Limitleri

| Endpoint | Limit | Pencere |
|----------|-------|---------|
| POST /api/auth/login | 5 | 1 dakika |
| POST /api/rooms (create) | 10 | 1 dakika |
| POST /api/auth/refresh | 20 | 1 dakika |
| GET /api/auth/me | 60 | 1 dakika |
| GET /api/rooms (list) | 60 | 1 dakika |
| GET /api/rooms/{id} | 60 | 1 dakika |
| PUT /api/diagrams/{id} | 100 | 1 dakika |
| POST /api/files/upload | 10 | 1 dakika |
| Diğer API endpoint'leri | 100 | 1 dakika |

### WebSocket Mesaj Limitleri

| Mesaj Tipi | Limit | Pencere | Burst |
|------------|-------|---------|-------|
| Chat mesajları | 60/dakika | 60s | 10/saniye |
| WebRTC signaling (offer/answer/ice) | 300/dakika | 60s | 30/saniye |
| Content update (diagram) | 100/dakika | 60s | 20/saniye |
| Cursor update | 300/dakika | 60s | 30/saniye |
| Diğer mesajlar | 120/dakika | 60s | 20/saniye |

### Rate Limit Yapılandırması

`.env` dosyasında rate limiting ayarlarını yapılandırabilirsiniz:

```bash
# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_USE_REDIS=false  # Redis kullanılabilir olduğunda true yapın
RATE_LIMIT_LOGIN_PER_MINUTE=5
RATE_LIMIT_CREATE_ROOM_PER_MINUTE=10
RATE_LIMIT_DEFAULT_PER_MINUTE=100
RATE_LIMIT_WS_CHAT_PER_MINUTE=60
RATE_LIMIT_WS_SIGNALLING_PER_MINUTE=300
```

### Rate Limit Hata Cevapları

Rate limit aşıldığında API şu hata cevabını döndürür:

```json
{
  "detail": "Rate limit exceeded. Please try again later."
}
```

HTTP Headers:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1704067200
Retry-After: 60
```

WebSocket için:
```json
{
  "type": "rate_limit_exceeded",
  "message": "Rate limit exceeded: max 60 messages per 60 seconds"
}
```

### Güvenlik Uyarıları

Uygulama production modunda başlatılırken şu güvenlik kontrolleri yapılır:

1. **JWT_SECRET Kontrolü**: Production modunda (`DEBUG=false`) JWT_SECRET set edilmemişse veya varsayılan değer kullanılıyorsa uygulama başlatılmaz
2. **Minimum Uzunluk Kontrolü**: JWT_SECRET 32 karakterden kısaysa uyarı verilir
3. **Placeholder Kontrolü**: Varsayılan placeholder değerler production'da reddedilir

### Admin Kullanıcı Güvenliği

İlk kurulumda admin kullanıcısı otomatik olarak oluşturulur:

- **Kullanıcı adı**: `.env` dosyasındaki `ADMIN_USERNAME` ile ayarlanır (varsayılan: `admin`)
- **Şifre**: `.env` dosyasındaki `ADMIN_PASSWORD` ile ayarlanabilir
- **Rastgele şifre**: `ADMIN_PASSWORD` boş bırakılırsa 24 karakterlik güçlü bir şifre otomatik oluşturulur
- **Şifre görüntüleme**: Rastgele oluşturulan şifre sadece ilk kurulumda log'larda görüntülenir
- **İlk girişte şifre değiştirme**: `ADMIN_FORCE_PASSWORD_CHANGE=true` ile ilk girişte şifre değiştirme zorunlu

```bash
# .env dosyasında admin şifresini ayarlamak için:
ADMIN_USERNAME=myadmin
ADMIN_EMAIL=admin@mydomain.com
ADMIN_PASSWORD=MyVeryStrongP@ssw0rd!123
ADMIN_FORCE_PASSWORD_CHANGE=true
```

**Önemli**:
- İlk kurulumda oluşturulan şifre loglarda görüntülenir
- Logları güvenli bir yerde saklayın ve ilk girişte şifrenizi değiştirin
- Şifre değiştirmek için `POST /api/auth/change-password` endpoint'ini kullanın
- Request body: `{"old_password": "...", "new_password": "..."}`

## Redis State Management

Uygulama, ölçeklenebilir state yönetimi için Redis kullanır. Redis kullanılamadığında otomatik olarak bellek içi (in-memory) fallback'e geçer.

### Redis ile Yönetilen State'ler

- **Guest Sessions**: Misafir oturum bilgileri (token, room_id, guest_name)
- **Active Users**: Heartbeat ile takip edilen aktif kullanıcılar
- **WebSocket Room State**: Oda katılımcıları, presenter'lar, paylaşılan dosyalar
- **Cross-Instance Communication**: Redis pub/sub ile çoklu instance senkronizasyonu

### Redis Yapılandırması

`.env` dosyasında Redis URL yapılandırması:

```bash
# Redis Connection
REDIS_URL=redis://localhost:6379/0

# Production için Redis AUTH önerilir:
# REDIS_URL=redis://:password@localhost:6379/0
# veya
# REDIS_URL=redis://username:password@redis-server:6379/0
```

### Docker Compose ile Redis

Docker Compose kullanıyorsanız, `docker-compose.yml` dosyasına Redis ekleyin:

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data

volumes:
  redis_data:
```

### Redis Kullanım Özellikleri

1. **Otomatik Fallback**: Redis kullanılamadığında uygulama çalışmaya devam eder (in-memory storage)
2. **TTL Desteği**: Otomatik expire ile temizlik (guest sessions: 24 saat, active users: 90 saniye)
3. **Pub/Sub**: Çoklu instance deployment için cross-instance mesajlaşma
4. **Health Check**: `/health` endpoint'i Redis durumunu raporlar

### Health Check

```bash
curl http://localhost:8000/health
```

Cevap:
```json
{
  "status": "healthy",
  "service": "ScreenShare Pro",
  "redis": {
    "redis_available": true,
    "redis_connected": true,
    "using_fallback": false,
    "fallback_entries": 0
  }
}
```
