# ScreenShare Pro

Web tabanlı ekran paylaşım platformu. Firewall arkasındaki kullanıcılarla bile sorunsuz ekran paylaşımı yapın.

## Özellikler

- 🖥️ WebRTC tabanlı gerçek zamanlı ekran paylaşımı
- 🎤 Sesli iletişim desteği
- 💬 Anlık mesajlaşma
- 🔐 JWT tabanlı güvenli kimlik doğrulama
- 🌐 Firewall/NAT dostu (TURN sunucu desteği)
- 👥 Oda başına maksimum 3 izleyici

## Teknolojiler

### Backend

- Python 3.11+
- FastAPI
- PostgreSQL
- Redis
- SQLAlchemy 2.0

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
# .env dosyasını düzenle (JWT_SECRET'ı değiştir!)

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

# Uygulamayı başlat
uvicorn app.main:app --reload
```

## API Endpoints

### Authentication

- `POST /api/auth/register` - Yeni kullanıcı kaydı
- `POST /api/auth/login` - Giriş
- `POST /api/auth/refresh` - Token yenileme
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
