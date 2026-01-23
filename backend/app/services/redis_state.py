"""
Redis State Management Service

Bu modul, in-memory state (guest_sessions, active_users, WebSocket manager)
yerine Redis kullanarak state yönetimi sağlar.

Özellikler:
- Guest session yönetimi
- Aktif kullanıcı takibi
- WebSocket connection state (pub/sub ile senkronizasyon)
- Otomatik expire (TTL) desteği
"""

import json
import time
from typing import Optional, Dict, Any, List
from datetime import datetime

from app.config import settings
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

# Redis import - yoksa graceful fallback
try:
    from redis.asyncio import Redis, ConnectionPool
    from redis.exceptions import RedisError
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    Redis = None  # type: ignore
    ConnectionPool = None  # type: ignore
    RedisError = Exception  # type: ignore


# Redis key prefix'leri
GUEST_SESSION_PREFIX = "guest_session:"
ACTIVE_USER_PREFIX = "active_user:"
WS_ROOM_PREFIX = "ws_room:"
WS_USER_PREFIX = "ws_user:"
WS_PRESENTER_PREFIX = "ws_presenter:"
WS_SHARED_FILE_PREFIX = "ws_file:"
WS_USERNAME_PREFIX = "ws_username:"
WS_PRESENTATION_PREFIX = "ws_presentation:"
WS_VOICE_CHAT_PREFIX = "ws_voice_chat:"
WS_AUDIO_USERS_PREFIX = "ws_audio_users:"
ROOM_PUBSUB_PREFIX = "room_broadcast:"

# TTL değerleri (saniye)
GUEST_SESSION_TTL = 86400  # 24 saat
ACTIVE_USER_TTL = 90  # 90 saniye (heartbeat timeout'dan uzun)
WS_STATE_TTL = 3600  # 1 saat


class RedisStateService:
    """
    Redis tabanlı state yönetimi.

    Redis kullanılamadığında in-memory fallback kullanır.
    """

    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis: Optional["Redis"] = None
        self._pool: Optional["ConnectionPool"] = None
        self._use_fallback = not REDIS_AVAILABLE
        self._fallback_store: Dict[str, Any] = {}

        # Pub/sub subscriptions
        self._pubsub = None
        self._subscribed_channels = set()

    async def get_redis(self) -> Optional["Redis"]:
        """Get or create Redis connection."""
        if self._use_fallback:
            return None

        if self._redis is None:
            try:
                self._pool = ConnectionPool.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True
                )
                self._redis = Redis(connection_pool=self._pool)

                # Test connection
                await self._redis.ping()
                logger.info("Redis state service connected successfully")

            except (RedisError, OSError) as e:
                logger.warning(
                    f"Redis connection failed, using in-memory fallback: {e}"
                )
                self._use_fallback = True
                self._redis = None
                self._pool = None

        return self._redis

    async def close(self):
        """Close Redis connections."""
        if self._pubsub:
            await self._pubsub.close()
            self._pubsub = None
        if self._redis:
            await self._redis.close()
            self._redis = None
        if self._pool:
            await self._pool.disconnect()
            self._pool = None
        logger.info("Redis state service closed")

    # ==================== Fallback Methods ====================

    def _get_fallback(self, key: str) -> Any:
        """Get data from fallback storage."""
        return self._fallback_store.get(key)

    def _set_fallback(self, key: str, value: Any, ttl: int = None):
        """Set data in fallback storage with optional TTL."""
        self._fallback_store[key] = {
            "value": value,
            "expires_at": time.time() + ttl if ttl else None
        }

    def _delete_fallback(self, key: str):
        """Delete data from fallback storage."""
        if key in self._fallback_store:
            del self._fallback_store[key]

    def _cleanup_fallback(self):
        """Remove expired entries from fallback storage."""
        now = time.time()
        expired_keys = [
            k for k, v in self._fallback_store.items()
            if isinstance(v, dict) and v.get("expires_at") and v["expires_at"] < now
        ]
        for k in expired_keys:
            del self._fallback_store[k]

    # ==================== Guest Sessions ====================

    async def set_guest_session(
        self,
        token: str,
        room_id: str,
        guest_name: str,
        ttl: int = GUEST_SESSION_TTL
    ) -> bool:
        """Guest session kaydet."""
        key = f"{GUEST_SESSION_PREFIX}{token}"
        data = {
            "room_id": room_id,
            "guest_name": guest_name,
            "created_at": datetime.utcnow().isoformat()
        }

        redis = await self.get_redis()
        if redis:
            try:
                await redis.setex(key, ttl, json.dumps(data))
                return True
            except RedisError as e:
                logger.warning(f"Redis set_guest_session failed: {e}")

        # Fallback
        self._set_fallback(key, data, ttl)
        return True

    async def get_guest_session(self, token: str) -> Optional[Dict[str, Any]]:
        """Guest session getir."""
        key = f"{GUEST_SESSION_PREFIX}{token}"

        redis = await self.get_redis()
        if redis:
            try:
                data = await redis.get(key)
                if data:
                    return json.loads(data)
            except RedisError:
                pass

        # Fallback
        result = self._get_fallback(key)
        if isinstance(result, dict) and "value" in result:
            return result["value"]
        return None

    async def delete_guest_session(self, token: str) -> bool:
        """Guest session sil."""
        key = f"{GUEST_SESSION_PREFIX}{token}"

        redis = await self.get_redis()
        if redis:
            try:
                await redis.delete(key)
            except RedisError:
                pass

        # Fallback
        self._delete_fallback(key)
        return True

    async def get_room_guest_count(self, room_id: str) -> int:
        """Odadaki guest sayısını getir."""
        redis = await self.get_redis()
        if redis:
            try:
                # Pattern scan ile guest session'ları bul
                pattern = f"{GUEST_SESSION_PREFIX}*"
                count = 0
                async for key in redis.scan_iter(match=pattern, count=100):
                    data = await redis.get(key)
                    if data:
                        try:
                            session = json.loads(data)
                            if session.get("room_id") == room_id:
                                count += 1
                        except (json.JSONDecodeError, TypeError):
                            pass
                return count
            except RedisError:
                pass

        # Fallback
        self._cleanup_fallback()
        count = 0
        for k, v in self._fallback_store.items():
            if k.startswith(GUEST_SESSION_PREFIX):
                data = v.get("value") if isinstance(v, dict) else v
                if isinstance(data, dict) and data.get("room_id") == room_id:
                    count += 1
        return count

    # ==================== Active Users ====================

    async def update_active_user(
        self,
        user_id: str,
        username: str,
        is_guest: bool = False,
        ttl: int = ACTIVE_USER_TTL
    ) -> bool:
        """Aktif kullanıcı güncelle (heartbeat)."""
        key = f"{ACTIVE_USER_PREFIX}{user_id}"
        data = {
            "user_id": user_id,
            "username": username,
            "last_seen": time.time(),
            "is_guest": is_guest
        }

        redis = await self.get_redis()
        if redis:
            try:
                await redis.setex(key, ttl, json.dumps(data))
                return True
            except RedisError as e:
                logger.warning(f"Redis update_active_user failed: {e}")

        # Fallback
        self._set_fallback(key, data, ttl)
        return True

    async def get_active_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Aktif kullanıcı bilgisi getir."""
        key = f"{ACTIVE_USER_PREFIX}{user_id}"

        redis = await self.get_redis()
        if redis:
            try:
                data = await redis.get(key)
                if data:
                    return json.loads(data)
            except RedisError:
                pass

        # Fallback
        result = self._get_fallback(key)
        if isinstance(result, dict) and "value" in result:
            return result["value"]
        return None

    async def get_all_active_users(self, timeout: int = 30) -> List[Dict[str, Any]]:
        """Tüm aktif kullanıcıları getir (timeout kontrolü ile)."""
        redis = await self.get_redis()
        users = {}
        now = time.time()

        if redis:
            try:
                pattern = f"{ACTIVE_USER_PREFIX}*"
                async for key in redis.scan_iter(match=pattern, count=100):
                    data = await redis.get(key)
                    if data:
                        try:
                            user = json.loads(data)
                            last_seen = user.get("last_seen", 0)
                            if now - last_seen < timeout:
                                users[user["user_id"]] = user
                        except (json.JSONDecodeError, TypeError):
                            pass
            except RedisError:
                pass

        # Fallback - in-memory kullanıcıları da ekle
        self._cleanup_fallback()
        for k, v in self._fallback_store.items():
            if k.startswith(ACTIVE_USER_PREFIX):
                data = v.get("value") if isinstance(v, dict) else v
                if isinstance(data, dict):
                    user_id = data.get("user_id")
                    last_seen = data.get("last_seen", 0)
                    if user_id and now - last_seen < timeout:
                        if user_id not in users:
                            users[user_id] = data

        return list(users.values())

    async def delete_active_user(self, user_id: str) -> bool:
        """Aktif kullanıcı sil."""
        key = f"{ACTIVE_USER_PREFIX}{user_id}"

        redis = await self.get_redis()
        if redis:
            try:
                await redis.delete(key)
            except RedisError:
                pass

        # Fallback
        self._delete_fallback(key)
        return True

    # ==================== WebSocket Room State ====================

    async def ws_add_to_room(
        self,
        room_id: str,
        user_id: str,
        username: str,
        is_guest: bool = False,
        ttl: int = WS_STATE_TTL
    ) -> bool:
        """Kullanıcıyı odaya ekle."""
        room_key = f"{WS_ROOM_PREFIX}{room_id}"
        user_key = f"{WS_USER_PREFIX}{user_id}"
        username_key = f"{WS_USERNAME_PREFIX}{user_id}"

        redis = await self.get_redis()
        if redis:
            try:
                pipe = redis.pipeline()
                # Kullanıcıyı odaya ekle (set)
                pipe.sadd(room_key, user_id)
                pipe.expire(room_key, ttl)
                # Kullanıcının oda bilgisini kaydet
                pipe.setex(user_key, ttl, room_id)
                # Username mapping
                pipe.setex(username_key, ttl, username)
                # Guest flag
                if is_guest:
                    guest_key = f"{WS_USER_PREFIX}:guest:{user_id}"
                    pipe.setex(guest_key, ttl, "1")
                await pipe.execute()
                return True
            except RedisError as e:
                logger.warning(f"Redis ws_add_to_room failed: {e}")

        # Fallback
        self._set_fallback(f"{room_key}:{user_id}", {
            "user_id": user_id,
            "username": username,
            "is_guest": is_guest
        }, ttl)
        self._set_fallback(user_key, room_id, ttl)
        self._set_fallback(username_key, username, ttl)
        return True

    async def ws_remove_from_room(self, room_id: str, user_id: str) -> bool:
        """Kullanıcıyı odadan çıkar."""
        room_key = f"{WS_ROOM_PREFIX}{room_id}"
        user_key = f"{WS_USER_PREFIX}{user_id}"
        username_key = f"{WS_USERNAME_PREFIX}{user_id}"
        guest_key = f"{WS_USER_PREFIX}:guest:{user_id}"

        redis = await self.get_redis()
        if redis:
            try:
                pipe = redis.pipeline()
                pipe.srem(room_key, user_id)
                pipe.delete(user_key, username_key, guest_key)
                await pipe.execute()
            except RedisError:
                pass

        # Fallback
        self._delete_fallback(f"{room_key}:{user_id}")
        self._delete_fallback(user_key)
        self._delete_fallback(username_key)
        return True

    async def ws_get_room_users(self, room_id: str) -> List[Dict[str, Any]]:
        """Odadaki kullanıcıları getir."""
        room_key = f"{WS_ROOM_PREFIX}{room_id}"

        redis = await self.get_redis()
        users = []

        if redis:
            try:
                user_ids = await redis.smembers(room_key)
                for user_id in user_ids:
                    username_key = f"{WS_USERNAME_PREFIX}{user_id}"
                    guest_key = f"{WS_USER_PREFIX}:guest:{user_id}"

                    pipe = redis.pipeline()
                    pipe.get(username_key)
                    pipe.exists(guest_key)
                    results = await pipe.execute()

                    username = results[0] or "Unknown"
                    is_guest = bool(results[1])

                    users.append({
                        "user_id": user_id,
                        "username": username,
                        "is_guest": is_guest
                    })
            except RedisError:
                pass

        # Fallback - in-memory kullanıcıları da ekle
        self._cleanup_fallback()
        pattern = f"{room_key}:*"
        for k, v in self._fallback_store.items():
            if k.startswith(pattern.replace("*", "")):
                data = v.get("value") if isinstance(v, dict) else v
                if isinstance(data, dict):
                    user_id = data.get("user_id")
                    if user_id and not any(u["user_id"] == user_id for u in users):
                        users.append(data)

        return users

    async def ws_get_user_room(self, user_id: str) -> Optional[str]:
        """Kullanıcının bulunduğu odayı getir."""
        user_key = f"{WS_USER_PREFIX}{user_id}"

        redis = await self.get_redis()
        if redis:
            try:
                room_id = await redis.get(user_key)
                if room_id:
                    return room_id
            except RedisError:
                pass

        # Fallback
        result = self._get_fallback(user_key)
        if isinstance(result, dict) and "value" in result:
            return result["value"]
        return None

    async def ws_get_username(self, user_id: str) -> Optional[str]:
        """Kullanıcı adını getir."""
        username_key = f"{WS_USERNAME_PREFIX}{user_id}"

        redis = await self.get_redis()
        if redis:
            try:
                username = await redis.get(username_key)
                if username:
                    return username
            except RedisError:
                pass

        # Fallback
        result = self._get_fallback(username_key)
        if isinstance(result, dict) and "value" in result:
            return result["value"]
        return None

    # ==================== Presenter State ====================

    async def ws_add_presenter(
        self,
        room_id: str,
        user_id: str,
        username: str,
        share_type: str = "screen",
        ttl: int = WS_STATE_TTL
    ) -> bool:
        """Presenter ekle."""
        key = f"{WS_PRESENTER_PREFIX}{room_id}:{user_id}"
        data = {
            "username": username,
            "share_type": share_type,
            "added_at": time.time()
        }

        redis = await self.get_redis()
        if redis:
            try:
                await redis.setex(key, ttl, json.dumps(data))
                return True
            except RedisError as e:
                logger.warning(f"Redis ws_add_presenter failed: {e}")

        # Fallback
        self._set_fallback(key, data, ttl)
        return True

    async def ws_remove_presenter(self, room_id: str, user_id: str) -> bool:
        """Presenter çıkar."""
        key = f"{WS_PRESENTER_PREFIX}{room_id}:{user_id}"

        redis = await self.get_redis()
        if redis:
            try:
                await redis.delete(key)
            except RedisError:
                pass

        # Fallback
        self._delete_fallback(key)
        return True

    async def ws_get_presenters(self, room_id: str) -> Dict[str, Dict[str, Any]]:
        """Odadaki presenter'ları getir."""
        pattern = f"{WS_PRESENTER_PREFIX}{room_id}:*"
        presenters = {}

        redis = await self.get_redis()
        if redis:
            try:
                async for key in redis.scan_iter(match=pattern, count=100):
                    data = await redis.get(key)
                    if data:
                        try:
                            presenter_data = json.loads(data)
                            user_id = key.split(":")[-1]
                            presenters[user_id] = presenter_data
                        except (json.JSONDecodeError, TypeError, IndexError):
                            pass
            except RedisError:
                pass

        # Fallback
        self._cleanup_fallback()
        for k, v in self._fallback_store.items():
            if k.startswith(pattern.replace("*", "")):
                data = v.get("value") if isinstance(v, dict) else v
                if isinstance(data, dict):
                    user_id = k.split(":")[-1]
                    presenters[user_id] = data

        return presenters

    async def ws_get_presenter_count(self, room_id: str) -> int:
        """Odadaki presenter sayısını getir."""
        return len(await self.ws_get_presenters(room_id))

    # ==================== Shared Files State ====================

    async def ws_add_shared_file(
        self,
        room_id: str,
        file_info: Dict[str, Any],
        ttl: int = WS_STATE_TTL
    ) -> bool:
        """Paylaşılan dosya ekle."""
        key = f"{WS_SHARED_FILE_PREFIX}{room_id}"
        file_id = file_info.get("id", str(time.time()))

        redis = await self.get_redis()
        if redis:
            try:
                # List olarak sakla (JSON array)
                current_data = await redis.get(key)
                files = json.loads(current_data) if current_data else []
                files.append({**file_info, "id": file_id})
                await redis.setex(key, ttl, json.dumps(files))
                return True
            except (RedisError, json.JSONDecodeError) as e:
                logger.warning(f"Redis ws_add_shared_file failed: {e}")

        # Fallback
        fallback_key = f"{key}:list"
        current = self._get_fallback(fallback_key)
        files = current.get("value") if isinstance(current, dict) and "value" in current else []
        if not isinstance(files, list):
            files = []
        files.append({**file_info, "id": file_id})
        self._set_fallback(fallback_key, files, ttl)
        return True

    async def ws_get_shared_files(self, room_id: str) -> List[Dict[str, Any]]:
        """Paylaşılan dosyaları getir."""
        key = f"{WS_SHARED_FILE_PREFIX}{room_id}"

        redis = await self.get_redis()
        if redis:
            try:
                data = await redis.get(key)
                if data:
                    return json.loads(data)
            except (RedisError, json.JSONDecodeError):
                pass

        # Fallback
        fallback_key = f"{key}:list"
        result = self._get_fallback(fallback_key)
        files = result.get("value") if isinstance(result, dict) and "value" in result else []
        return files if isinstance(files, list) else []

    async def ws_clear_shared_files(self, room_id: str) -> bool:
        """Paylaşılan dosyaları temizle."""
        key = f"{WS_SHARED_FILE_PREFIX}{room_id}"

        redis = await self.get_redis()
        if redis:
            try:
                await redis.delete(key)
            except RedisError:
                pass

        # Fallback
        fallback_key = f"{key}:list"
        self._delete_fallback(fallback_key)
        return True

    # ==================== Pub/Sub for Cross-Instance Communication ====================

    async def publish_message(self, room_id: str, message: Dict[str, Any]) -> bool:
        """
        Odaya mesaj yayınla (diğer instance'lar için).
        Bu, Redis pub/sub kullanarak çoklu instance senkronizasyonu sağlar.
        """
        redis = await self.get_redis()
        if redis:
            try:
                channel = f"{ROOM_PUBSUB_PREFIX}{room_id}"
                await redis.publish(channel, json.dumps(message))
                return True
            except RedisError as e:
                logger.warning(f"Redis publish_message failed: {e}")

        # Fallback - pub/sub için yapılabilecek bir şey yok
        return False

    async def subscribe_to_room(self, room_id: str, callback):
        """
        Oda için pub/sub kanalına abone ol.
        Callback fonksiyonu mesaj geldiğinde çağrılır.
        """
        redis = await self.get_redis()
        if not redis:
            return False

        if self._pubsub is None:
            self._pubsub = redis.pubsub()

        channel = f"{ROOM_PUBSUB_PREFIX}{room_id}"
        try:
            await self._pubsub.subscribe(channel)
            self._subscribed_channels.add(channel)
            logger.info(f"Subscribed to room channel: {channel}")
            return True
        except RedisError as e:
            logger.warning(f"Redis subscribe failed: {e}")
            return False

    async def unsubscribe_from_room(self, room_id: str):
        """Oda aboneliğinden çık."""
        if self._pubsub:
            channel = f"{ROOM_PUBSUB_PREFIX}{room_id}"
            try:
                await self._pubsub.unsubscribe(channel)
                self._subscribed_channels.discard(channel)
                logger.info(f"Unsubscribed from room channel: {channel}")
            except RedisError:
                pass

    async def listen_for_messages(self, callback):
        """
        Pub/sub mesajlarını dinle ve callback ile işle.
        Bu metod ayrı bir task olarak çalıştırılmalıdır.
        """
        if not self._pubsub:
            return

        try:
            async for message in self._pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await callback(data)
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"Failed to parse pub/sub message: {e}")
        except RedisError as e:
            logger.warning(f"Pub/sub listen error: {e}")

    # ==================== Presentation Mode State ====================

    async def ws_set_presentation_mode(
        self,
        room_id: str,
        presenter_id: str,
        presenter_name: str,
        enabled: bool = True,
        ttl: int = WS_STATE_TTL
    ) -> bool:
        """Sunum modunu ayarla."""
        key = f"{WS_PRESENTATION_PREFIX}{room_id}"
        
        if not enabled:
            # Sunum modunu kapat
            return await self._delete_key(key)
        
        data = {
            "enabled": True,
            "presenter_id": presenter_id,
            "presenter_name": presenter_name,
            "started_at": time.time()
        }

        redis = await self.get_redis()
        if redis:
            try:
                await redis.setex(key, ttl, json.dumps(data))
                return True
            except RedisError as e:
                logger.warning(f"Redis ws_set_presentation_mode failed: {e}")

        # Fallback
        self._set_fallback(key, data, ttl)
        return True

    async def ws_get_presentation_mode(self, room_id: str) -> Optional[Dict[str, Any]]:
        """Sunum modu durumunu getir."""
        key = f"{WS_PRESENTATION_PREFIX}{room_id}"

        redis = await self.get_redis()
        if redis:
            try:
                data = await redis.get(key)
                if data:
                    return json.loads(data)
            except RedisError:
                pass

        # Fallback
        result = self._get_fallback(key)
        if isinstance(result, dict) and "value" in result:
            return result["value"]
        return None

    async def ws_stop_presentation_mode(self, room_id: str) -> bool:
        """Sunum modunu kapat."""
        key = f"{WS_PRESENTATION_PREFIX}{room_id}"
        return await self._delete_key(key)

    async def _delete_key(self, key: str) -> bool:
        """Helper: Key sil."""
        redis = await self.get_redis()
        if redis:
            try:
                await redis.delete(key)
            except RedisError:
                pass
        self._delete_fallback(key)
        return True

    # ==================== Voice Chat State ====================

    async def ws_set_voice_chat(
        self,
        room_id: str,
        enabled: bool = True,
        ttl: int = WS_STATE_TTL
    ) -> bool:
        """Sesli iletişim durumunu ayarla."""
        key = f"{WS_VOICE_CHAT_PREFIX}{room_id}"
        
        if not enabled:
            return await self._delete_key(key)
        
        data = {
            "enabled": True,
            "started_at": time.time()
        }

        redis = await self.get_redis()
        if redis:
            try:
                await redis.setex(key, ttl, json.dumps(data))
                return True
            except RedisError as e:
                logger.warning(f"Redis ws_set_voice_chat failed: {e}")

        self._set_fallback(key, data, ttl)
        return True

    async def ws_get_voice_chat(self, room_id: str) -> Optional[Dict[str, Any]]:
        """Sesli iletişim durumunu getir."""
        key = f"{WS_VOICE_CHAT_PREFIX}{room_id}"

        redis = await self.get_redis()
        if redis:
            try:
                data = await redis.get(key)
                if data:
                    return json.loads(data)
            except RedisError:
                pass

        result = self._get_fallback(key)
        if isinstance(result, dict) and "value" in result:
            return result["value"]
        return None

    async def ws_add_audio_user(
        self,
        room_id: str,
        user_id: str,
        username: str,
        ttl: int = WS_STATE_TTL
    ) -> bool:
        """Mikrofonu açık kullanıcı ekle."""
        key = f"{WS_AUDIO_USERS_PREFIX}{room_id}:{user_id}"
        data = {
            "user_id": user_id,
            "username": username,
            "mic_open": True,
            "added_at": time.time()
        }

        redis = await self.get_redis()
        if redis:
            try:
                await redis.setex(key, ttl, json.dumps(data))
                return True
            except RedisError as e:
                logger.warning(f"Redis ws_add_audio_user failed: {e}")

        self._set_fallback(key, data, ttl)
        return True

    async def ws_remove_audio_user(self, room_id: str, user_id: str) -> bool:
        """Mikrofonu açık kullanıcıyı kaldır."""
        key = f"{WS_AUDIO_USERS_PREFIX}{room_id}:{user_id}"
        return await self._delete_key(key)

    async def ws_get_audio_users(self, room_id: str) -> List[Dict[str, Any]]:
        """Mikrofonu açık kullanıcıları getir."""
        pattern = f"{WS_AUDIO_USERS_PREFIX}{room_id}:*"
        users = []

        redis = await self.get_redis()
        if redis:
            try:
                async for key in redis.scan_iter(match=pattern, count=100):
                    data = await redis.get(key)
                    if data:
                        try:
                            user_data = json.loads(data)
                            users.append(user_data)
                        except (json.JSONDecodeError, TypeError):
                            pass
            except RedisError:
                pass

        # Fallback
        self._cleanup_fallback()
        for k, v in self._fallback_store.items():
            if k.startswith(pattern.replace("*", "")):
                data = v.get("value") if isinstance(v, dict) else v
                if isinstance(data, dict):
                    user_id = data.get("user_id")
                    if user_id and not any(u["user_id"] == user_id for u in users):
                        users.append(data)

        return users

    # ==================== Health Check ====================

    async def health_check(self) -> Dict[str, Any]:
        """Redis bağlantı durumunu kontrol et."""
        redis = await self.get_redis()
        is_redis_connected = False

        if redis:
            try:
                await redis.ping()
                is_redis_connected = True
            except RedisError:
                is_redis_connected = False

        return {
            "redis_available": REDIS_AVAILABLE,
            "redis_connected": is_redis_connected,
            "using_fallback": self._use_fallback,
            "fallback_entries": len(self._fallback_store)
        }


# Global singleton instance
_redis_state_service: Optional[RedisStateService] = None


def get_redis_state() -> RedisStateService:
    """Get global Redis state service instance."""
    global _redis_state_service
    if _redis_state_service is None:
        _redis_state_service = RedisStateService()
    return _redis_state_service


async def close_redis_state():
    """Close Redis state service."""
    global _redis_state_service
    if _redis_state_service:
        await _redis_state_service.close()
        _redis_state_service = None
