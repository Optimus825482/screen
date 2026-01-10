// WebRTC Manager - Ekran paylaşımı, kamera paylaşımı ve ses iletimi
// V2: Çoklu presenter, annotation, dosya paylaşımı desteği
// V3: WebSocket otomatik yeniden bağlanma desteği
class WebRTCManager {
  constructor(roomId, isHost) {
    this.roomId = roomId;
    this.isHost = isHost;
    this.localStream = null;
    this.peerConnections = new Map(); // userId -> RTCPeerConnection
    this.viewerAudioConnections = new Map(); // userId -> RTCPeerConnection (viewer audio için)
    this.remoteStreams = new Map(); // presenterId -> MediaStream (çoklu presenter için)
    this.ws = null;

    // Callbacks
    this.onRemoteStream = null; // Eski: tek stream
    this.onRemoteStreams = null; // Yeni: çoklu stream {presenterId -> stream}
    this.onViewerAudio = null;
    this.onParticipantUpdate = null;
    this.onChatMessage = null;
    this.onConnectionStateChange = null;
    this.onPresenterChange = null;
    this.onPresentersUpdate = null; // Yeni: Tüm presenter listesi güncellendiğinde
    this.onAnnotation = null; // Yeni: Annotation callback
    this.onFileShared = null; // Yeni: Dosya paylaşıldığında
    this.onError = null; // Yeni: Hata callback
    this.onWhiteboardDraw = null;
    this.onWhiteboardClear = null;
    this.onWhiteboardStarted = null;
    this.onWhiteboardStopped = null;
    this.onReconnecting = null; // Yeni: Reconnect başladığında
    this.onReconnected = null; // Yeni: Reconnect başarılı olduğunda
    this.onReconnectFailed = null; // Yeni: Reconnect başarısız olduğunda

    // State
    this.isScreenSharing = false;
    this.isCameraSharing = false;
    this.currentFacingMode = "user";
    this.isMuted = true;
    this.myUserId = null;

    // Çoklu presenter desteği
    this.presenters = {}; // {presenterId: {username, share_type}}
    this.maxPresenters = 2;

    // Dosya paylaşımı
    this.sharedFiles = [];

    // WebSocket Reconnect State
    this.wsState = "disconnected"; // disconnected, connecting, connected, reconnecting
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 10; // Maksimum deneme sayısı
    this.reconnectDelay = 1000; // Başlangıç gecikmesi (1s)
    this.maxReconnectDelay = 30000; // Maksimum gecikme (30s)
    this.reconnectTimeoutId = null;
    this.shouldReconnect = true; // Manuel disconnect edilirse false olur
    this.manualDisconnect = false; // Kullanıcı odadan ayrıldıysa true

    // WebRTC ICE config - Backend API'den yüklenecek (GÜVENLİ)
    // Credentials artık backend'den geliyor, frontend'de hard-coded YOK
    this.config = {
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    };
  }

  // WebSocket bağlantı durumunu al
  getConnectionState() {
    return this.wsState;
  }

  // Yeniden bağlanma durumunu al
  getReconnectInfo() {
    return {
      isReconnecting: this.wsState === "reconnecting",
      attempt: this.reconnectAttempts,
      maxAttempts: this.maxReconnectAttempts,
      delay: this.reconnectDelay,
    };
  }

  // API'den güncel ICE config al (Backend proxy üzerinden - GÜVENLİ)
  // Credentials server-side environment variable'dan okunur
  async fetchIceConfig() {
    try {
      // Backend API'den al (API key server-side olarak yönetilir)
      const response = await fetch("/api/rooms/ice-config", {
        headers: Auth.getAuthHeaders(),
      });
      if (response.ok) {
        const data = await response.json();
        this.config = data;
        console.log("ICE config loaded from backend");
      } else {
        console.warn("Backend ICE config returned status:", response.status);
      }
    } catch (error) {
      console.warn("Backend ICE config fetch failed, using defaults:", error);
    }
  }

  async connect() {
    const token = Auth.getToken();
    if (!token) return false;

    // Önce ICE config'i API'den al
    await this.fetchIceConfig();

    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/room/${this.roomId}?token=${token}`;

    return this.createWebSocketConnection(wsUrl);
  }

  // WebSocket bağlantısı oluştur
  createWebSocketConnection(wsUrl) {
    return new Promise((resolve, reject) => {
      this.wsState = "connecting";

      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log("WebSocket connected");
        this.wsState = "connected";

        // Bağlantı başarılı, reconnect durumlarını sıfırla
        if (this.reconnectAttempts > 0) {
          console.log(
            `WebSocket reconnected after ${this.reconnectAttempts} attempts`
          );
          this.reconnectAttempts = 0;
          this.reconnectDelay = 1000;

          // Reconnect başarılı callback
          if (this.onReconnected) {
            this.onReconnected();
          }
        }

        this.startPingInterval();
        resolve(true);
      };

      this.ws.onclose = (event) => {
        console.log("WebSocket closed:", event.code, event.reason);
        this.wsState = "disconnected";
        this.stopPingInterval();

        // Manuel disconnect değilse ve hata kodu geçici bir hata ise, yeniden bağlan
        // 1000: Normal close, 4001: Kicked, 4002: Room ended (manuel disconnect)
        const isManualClose = event.code === 1000 || event.code >= 4000;

        if (!isManualClose && !this.manualDisconnect && this.shouldReconnect) {
          this.startReconnect();
        } else {
          // Manuel disconnect veya kalıcı hata
          if (this.onConnectionStateChange) {
            this.onConnectionStateChange("disconnected");
          }
        }
      };

      this.ws.onerror = (error) => {
        console.error("WebSocket error:", error);

        // İlk bağlantı hatası ise reject et
        if (this.wsState === "connecting" && this.reconnectAttempts === 0) {
          reject(error);
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleMessage(data);
        } catch (e) {
          console.error("Failed to parse WebSocket message:", e);
        }
      };
    });
  }

  // Exponential backoff ile yeniden bağlan
  startReconnect() {
    // Maksimum deneme sayısına ulaşıldı mı kontrol et
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error(
        `Max reconnect attempts (${this.maxReconnectAttempts}) reached`
      );
      this.wsState = "failed";

      if (this.onReconnectFailed) {
        this.onReconnectFailed();
      }

      if (this.onConnectionStateChange) {
        this.onConnectionStateChange("failed");
      }

      return;
    }

    // Zaten reconnecting durumundaysak, tekrar başlatma
    if (this.wsState === "reconnecting") {
      return;
    }

    this.wsState = "reconnecting";
    this.reconnectAttempts++;

    // Exponential backoff: her denemede gecikmeyi ikiye kat
    // 1s, 2s, 4s, 8s, 16s, 30s (max)
    const currentDelay = Math.min(
      this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
      this.maxReconnectDelay
    );

    console.log(
      `Reconnecting... Attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts}, delay: ${currentDelay}ms`
    );

    // Reconnect başlangıç callback
    if (this.onReconnecting) {
      this.onReconnecting(
        this.reconnectAttempts,
        this.maxReconnectAttempts,
        currentDelay
      );
    }

    if (this.onConnectionStateChange) {
      this.onConnectionStateChange("reconnecting");
    }

    // Belirtilen süre sonra yeniden bağlanmayı dene
    this.reconnectTimeoutId = setTimeout(async () => {
      const token = Auth.getToken();
      if (!token) {
        console.error("No token for reconnect");
        this.startReconnect();
        return;
      }

      const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${wsProtocol}//${window.location.host}/ws/room/${this.roomId}?token=${token}`;

      try {
        await this.createWebSocketConnection(wsUrl);
      } catch (e) {
        console.error("Reconnect failed:", e);
        // Başarısız olursa tekrar dene
        this.startReconnect();
      }
    }, currentDelay);
  }

  // Reconnect'i iptal et (manuel disconnect için)
  cancelReconnect() {
    if (this.reconnectTimeoutId) {
      clearTimeout(this.reconnectTimeoutId);
      this.reconnectTimeoutId = null;
    }
    this.shouldReconnect = false;
    this.manualDisconnect = true;
    this.wsState = "disconnected";
  }

  startPingInterval() {
    this.pingInterval = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "ping" }));
      }
    }, 30000);
  }

  stopPingInterval() {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
    }
  }

  async handleMessage(data) {
    switch (data.type) {
      case "room_state":
        if (this.onParticipantUpdate) {
          this.onParticipantUpdate(data.participants, data);
        }
        // Kendi user_id'mizi kaydet
        this.myUserId = data.participants.find(
          (p) => p.username === data.room_name
        )?.user_id;

        // Mevcut presenter'ları yükle
        if (data.presenters) {
          this.presenters = data.presenters;
          if (this.onPresentersUpdate) {
            this.onPresentersUpdate(this.presenters);
          }
        }

        // Paylaşılan dosyaları yükle
        if (data.shared_files) {
          this.sharedFiles = data.shared_files;
        }

        // Mevcut kullanıcılar için peer connection oluştur
        for (const participant of data.participants) {
          if (
            participant.user_id !== this.myUserId &&
            !this.peerConnections.has(participant.user_id)
          ) {
            this.createPeerConnection(participant.user_id);
          }
        }

        // Mevcut presenter'lardan offer iste
        for (const presenterId of Object.keys(this.presenters)) {
          if (presenterId !== this.myUserId) {
            this.send({ type: "request_offer", target: presenterId });
          }
        }
        break;

      case "user_joined":
        if (this.onParticipantUpdate) {
          this.onParticipantUpdate(data.participants, data);
        }
        // Yeni kullanıcı için peer connection oluştur
        if (!this.peerConnections.has(data.user_id)) {
          this.createPeerConnection(data.user_id);
        }
        // Eğer biz paylaşıyorsak yeni kullanıcıya offer gönder
        if (this.isScreenSharing || this.isCameraSharing) {
          await this.createOfferForUser(data.user_id);
        }
        break;

      case "user_left":
        this.closePeerConnection(data.user_id);
        if (this.onParticipantUpdate) {
          this.onParticipantUpdate(data.participants, data);
        }
        // Ayrılan kişi presenter ise listeden çıkar
        if (this.presenters[data.user_id]) {
          delete this.presenters[data.user_id];
          this.remoteStreams.delete(data.user_id);
          if (this.onPresentersUpdate) {
            this.onPresentersUpdate(this.presenters);
          }
          // Remote stream'i temizle
          if (this.onRemoteStream) {
            this.onRemoteStream(null);
          }
        }
        break;

      case "request_offer":
        // Birisi bizden offer istiyor (biz paylaşıyorsak)
        if (this.isScreenSharing || this.isCameraSharing) {
          console.log("Received request_offer from:", data.from);
          await this.createOfferForUser(data.from);
        }
        // Eğer karşı taraf da presenter ise ve biz henüz onun stream'ini almadıysak, biz de offer isteyelim
        if (
          this.presenters[data.from] &&
          !this.remoteStreams.has(data.from) &&
          data.from !== this.myUserId
        ) {
          console.log("Also requesting offer from presenter:", data.from);
          // Küçük bir gecikme ile gönder (race condition önlemek için)
          setTimeout(() => {
            this.send({ type: "request_offer", target: data.from });
          }, 100);
        }
        break;

      case "offer":
        // Birisi bize offer gönderiyor (biz izliyoruz)
        if (!this.isScreenSharing) {
          await this.handleOffer(data.from, data.sdp);
        }
        break;

      case "answer":
        // Host olarak answer aldık
        await this.handleAnswer(data.from, data.sdp);
        break;

      case "ice_candidate":
        await this.handleIceCandidate(data.from, data.candidate);
        break;

      case "screen_share_started":
        // Birisi ekran/kamera paylaşımı başlattı (çoklu presenter desteği)
        console.log(
          "Screen share started by:",
          data.presenter_name,
          "type:",
          data.share_type
        );

        // Presenter listesini güncelle
        if (data.presenters) {
          this.presenters = data.presenters;
        } else {
          this.presenters[data.presenter_id] = {
            username: data.presenter_name,
            share_type: data.share_type || "screen",
          };
        }

        // Callbacks
        if (this.onPresentersUpdate) {
          this.onPresentersUpdate(this.presenters);
        }
        if (this.onPresenterChange) {
          this.onPresenterChange(
            data.presenter_id,
            data.presenter_name,
            data.share_type
          );
        }

        // Presenter için peer connection oluştur (yoksa)
        if (!this.peerConnections.has(data.presenter_id)) {
          this.createPeerConnection(data.presenter_id);
        }

        // Yeni presenter'dan offer iste (kendimiz değilsek)
        // NOT: Biz de paylaşıyor olsak bile, diğer presenter'ın stream'ini almak için offer istememiz gerekiyor
        if (data.presenter_id !== this.myUserId) {
          console.log(
            "Requesting offer from new presenter:",
            data.presenter_id
          );
          this.send({ type: "request_offer", target: data.presenter_id });
        }
        break;

      case "screen_share_stopped":
        // Paylaşım durduruldu
        console.log("Screen share stopped by:", data.presenter_id);

        // Presenter listesini güncelle
        if (data.presenters) {
          this.presenters = data.presenters;
        } else {
          delete this.presenters[data.presenter_id];
        }

        // Remote stream'i kaldır
        this.remoteStreams.delete(data.presenter_id);

        // Eğer bu presenter'ı izliyorsak, currentPresenter'ı temizle
        if (this.currentPresenterId === data.presenter_id) {
          this.currentPresenterId = null;
          this.currentPresenterName = null;
        }

        // Callbacks
        if (this.onPresentersUpdate) {
          this.onPresentersUpdate(this.presenters);
        }
        if (this.onPresenterChange) {
          this.onPresenterChange(data.presenter_id, null, null);
        }

        // Remote stream callback'i de çağır (UI'ın temizlenmesi için)
        if (this.onRemoteStream && Object.keys(this.presenters).length === 0) {
          this.onRemoteStream(null);
        }
        break;

      case "error":
        // Sunucudan hata mesajı
        console.error("Server error:", data.message);
        if (this.onError) {
          this.onError(data.message);
        } else {
          alert(data.message);
        }
        break;

      case "annotation":
        // Ekran üzerine çizim/işaretleme
        if (this.onAnnotation) {
          this.onAnnotation(data);
        }
        break;

      case "file_shared":
        // Dosya paylaşıldı
        this.sharedFiles.push(data);
        if (this.onFileShared) {
          this.onFileShared(data);
        }
        break;

      case "chat":
        if (this.onChatMessage) {
          this.onChatMessage(data);
        }
        break;

      case "whiteboard_draw":
        if (this.onWhiteboardDraw) {
          this.onWhiteboardDraw(data);
        }
        break;

      case "whiteboard_clear":
        if (this.onWhiteboardClear) {
          this.onWhiteboardClear();
        }
        break;

      case "whiteboard_started":
        if (this.onWhiteboardStarted) {
          this.onWhiteboardStarted(data.user_id, data.username);
        }
        break;

      case "whiteboard_stopped":
        if (this.onWhiteboardStopped) {
          this.onWhiteboardStopped();
        }
        break;

      case "kicked":
        alert(data.reason);
        window.location.href = "/dashboard";
        break;

      case "room_ended":
        alert(data.reason);
        window.location.href = "/dashboard";
        break;

      case "viewer_audio_answer":
        // Viewer olarak answer aldık
        await this.handleViewerAudioAnswer(data.sdp);
        break;

      case "viewer_audio_offer":
        // Viewer mikrofon açtı, host olarak answer ver
        if (this.isHost) {
          await this.handleViewerAudioOffer(data.from, data.username, data.sdp);
        }
        break;

      case "viewer_audio_stopped":
        // Viewer mikrofonu kapattı
        if (this.isHost) {
          this.closeViewerAudioConnection(data.from);
          if (this.onViewerAudio) {
            this.onViewerAudio(data.from, data.username, null);
          }
        }
        break;

      case "pong":
        // Ping response, ignore
        break;
    }
  }

  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  async startScreenShare() {
    // Çoklu presenter kontrolü - maksimum 2 presenter
    if (!this.canShare()) {
      throw new Error(
        "Maksimum presenter sayısına (2) ulaşıldı. Lütfen bekleyin."
      );
    }

    try {
      // Ekran paylaşımı - ses OLMADAN başlat (kullanıcı mikrofonu açarsa eklenecek)
      this.localStream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          cursor: "always",
          displaySurface: "monitor",
        },
        audio: false, // Ses varsayılan olarak kapalı
      });

      // Ekran paylaşımı durduğunda
      this.localStream.getVideoTracks()[0].onended = () => {
        this.stopScreenShare();
      };

      this.isScreenSharing = true;
      this.isCameraSharing = false;
      this.isMuted = true; // Mikrofon varsayılan kapalı
      this.send({ type: "screen_share_started", share_type: "screen" });

      // Mevcut kullanıcılara offer gönder
      for (const [userId] of this.peerConnections) {
        await this.createOfferForUser(userId);
      }

      return this.localStream;
    } catch (error) {
      console.error("Screen share error:", error);
      throw error;
    }
  }

  // Mobil için kamera paylaşımı
  async startCameraShare(facingMode = "user") {
    // Çoklu presenter kontrolü - maksimum 2 presenter
    if (!this.canShare()) {
      throw new Error(
        "Maksimum presenter sayısına (2) ulaşıldı. Lütfen bekleyin."
      );
    }

    try {
      this.currentFacingMode = facingMode;

      // Kamera paylaşımı - ses OLMADAN başlat
      this.localStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: facingMode,
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false, // Ses varsayılan olarak kapalı
      });

      // Kamera durduğunda
      this.localStream.getVideoTracks()[0].onended = () => {
        this.stopCameraShare();
      };

      this.isCameraSharing = true;
      this.isScreenSharing = false;
      this.isMuted = true; // Mikrofon varsayılan kapalı
      this.send({ type: "screen_share_started", share_type: "camera" });

      // Mevcut kullanıcılara offer gönder
      console.log("Sending offers to peers:", this.peerConnections.size);
      for (const [userId] of this.peerConnections) {
        console.log("Creating offer for user:", userId);
        await this.createOfferForUser(userId);
      }

      return this.localStream;
    } catch (error) {
      console.error("Camera share error:", error);
      throw error;
    }
  }

  // Kamera değiştir (ön/arka)
  async switchCamera() {
    if (!this.isCameraSharing) return;

    const newFacingMode =
      this.currentFacingMode === "user" ? "environment" : "user";

    try {
      // Eski stream'i durdur
      if (this.localStream) {
        this.localStream.getVideoTracks().forEach((track) => track.stop());
      }

      // Yeni kamera ile stream al
      const newStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: newFacingMode,
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false, // Ses track'ini koru
      });

      const newVideoTrack = newStream.getVideoTracks()[0];

      // Eski video track'i yenisiyle değiştir
      const oldVideoTrack = this.localStream.getVideoTracks()[0];
      this.localStream.removeTrack(oldVideoTrack);
      this.localStream.addTrack(newVideoTrack);

      // Peer connection'lardaki track'i güncelle
      for (const [userId, pc] of this.peerConnections) {
        const sender = pc.getSenders().find((s) => s.track?.kind === "video");
        if (sender) {
          await sender.replaceTrack(newVideoTrack);
        }
      }

      this.currentFacingMode = newFacingMode;

      // Track durduğunda
      newVideoTrack.onended = () => {
        this.stopCameraShare();
      };

      return this.localStream;
    } catch (error) {
      console.error("Camera switch error:", error);
      throw error;
    }
  }

  // Kamera paylaşımını durdur
  stopCameraShare() {
    if (this.localStream) {
      this.localStream.getTracks().forEach((track) => track.stop());
      this.localStream = null;
    }
    this.isCameraSharing = false;
    this.send({ type: "screen_share_stopped" });

    // Tüm peer connection'ları kapat
    for (const [userId] of this.peerConnections) {
      this.closePeerConnection(userId);
    }
  }

  // Mobil cihaz mı kontrol et
  static isMobileDevice() {
    return (
      /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
        navigator.userAgent
      ) ||
      (navigator.maxTouchPoints && navigator.maxTouchPoints > 2)
    );
  }

  // Ekran paylaşımı destekleniyor mu
  static isScreenShareSupported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia);
  }

  async addAudioTrack() {
    try {
      // Mikrofon izni al
      const audioStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const audioTrack = audioStream.getAudioTracks()[0];

      // CASE 1: Presenter (ekran/kamera paylaşan kişi)
      if (this.localStream && (this.isScreenSharing || this.isCameraSharing)) {
        console.log("Adding audio to presenter stream");

        // Mevcut audio track varsa kaldır
        const existingAudio = this.localStream.getAudioTracks()[0];
        if (existingAudio) {
          this.localStream.removeTrack(existingAudio);
          existingAudio.stop();
        }
        this.localStream.addTrack(audioTrack);

        // Mevcut peer connection'lara audio track ekle/güncelle
        for (const [userId, pc] of this.peerConnections) {
          try {
            const sender = pc
              .getSenders()
              .find((s) => s.track?.kind === "audio");
            if (sender) {
              await sender.replaceTrack(audioTrack);
            } else {
              pc.addTrack(audioTrack, this.localStream);
            }
          } catch (e) {
            console.warn(`Failed to add audio to peer ${userId}:`, e);
          }
        }

        this.isMuted = false;
        return audioTrack;
      }

      // CASE 2: Viewer (izleyici) - Presenter'a ses göndermek istiyor
      if (this.currentPresenterId) {
        console.log(
          "Viewer sending audio to presenter:",
          this.currentPresenterId
        );

        // audioStream'i sakla
        this.audioStream = audioStream;

        // Viewer audio için ayrı peer connection oluştur
        await this.setupViewerAudioConnection(audioTrack, audioStream);

        this.isMuted = false;
        return audioTrack;
      }

      // CASE 3: Hiçbir paylaşım yok, sadece mikrofon aç (standalone)
      console.log("Standalone audio mode - no active share");
      this.audioStream = audioStream;
      this.isMuted = false;
      return audioTrack;
    } catch (error) {
      console.error("Audio error:", error);
      throw error;
    }
  }

  // Viewer için ayrı audio peer connection
  async setupViewerAudioConnection(audioTrack, audioStream) {
    // Eski bağlantı varsa kapat
    if (this.viewerAudioPc) {
      this.viewerAudioPc.close();
      this.viewerAudioPc = null;
    }

    const pc = new RTCPeerConnection(this.config);
    this.viewerAudioPc = pc;

    pc.onicecandidate = (event) => {
      if (event.candidate) {
        this.send({
          type: "ice_candidate",
          target: this.currentPresenterId,
          candidate: event.candidate,
        });
      }
    };

    pc.onconnectionstatechange = () => {
      console.log("Viewer audio connection state:", pc.connectionState);
      if (pc.connectionState === "failed") {
        console.error("Viewer audio connection failed");
      }
    };

    // Audio track'i ekle - audioStream ile birlikte
    pc.addTrack(audioTrack, audioStream);

    // Offer oluştur ve gönder
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    this.send({
      type: "viewer_audio_offer",
      target: this.currentPresenterId,
      sdp: pc.localDescription,
    });

    console.log("Viewer audio offer sent to presenter");
  }

  // Viewer audio answer'ı handle et
  async handleViewerAudioAnswer(sdp) {
    if (this.viewerAudioPc) {
      await this.viewerAudioPc.setRemoteDescription(
        new RTCSessionDescription(sdp)
      );
      console.log("Viewer audio answer received and set");
    }
  }

  // Viewer audio'yu durdur
  stopViewerAudio() {
    if (this.audioStream) {
      this.audioStream.getTracks().forEach((track) => track.stop());
      this.audioStream = null;
    }
    if (this.viewerAudioPc) {
      this.viewerAudioPc.close();
      this.viewerAudioPc = null;
    }
    // Presenter'a bildir
    if (this.currentPresenterId) {
      this.send({ type: "viewer_audio_stopped" });
    }
  }

  toggleMute() {
    // Presenter için: localStream'deki audio track'i toggle et
    if (this.localStream) {
      const audioTracks = this.localStream.getAudioTracks();
      audioTracks.forEach((track) => {
        track.enabled = !track.enabled;
      });
      this.isMuted = audioTracks.length > 0 ? !audioTracks[0].enabled : true;
    }
    // Viewer için: audioStream'deki audio track'i toggle et
    else if (this.audioStream) {
      const audioTracks = this.audioStream.getAudioTracks();
      audioTracks.forEach((track) => {
        track.enabled = !track.enabled;
      });
      this.isMuted = audioTracks.length > 0 ? !audioTracks[0].enabled : true;
    }
    return this.isMuted;
  }

  stopScreenShare() {
    if (this.localStream) {
      this.localStream.getTracks().forEach((track) => track.stop());
      this.localStream = null;
    }
    this.isScreenSharing = false;
    this.isCameraSharing = false;
    this.send({ type: "screen_share_stopped" });

    // Tüm peer connection'ları kapat
    for (const [userId] of this.peerConnections) {
      this.closePeerConnection(userId);
    }
  }

  // Herhangi bir paylaşım aktif mi
  isSharing() {
    return this.isScreenSharing || this.isCameraSharing;
  }

  createPeerConnection(userId) {
    // Mevcut connection varsa ve stable state'deyse, yeniden oluşturma
    const existingPc = this.peerConnections.get(userId);
    if (
      existingPc &&
      existingPc.connectionState !== "failed" &&
      existingPc.connectionState !== "closed"
    ) {
      console.log(`Reusing existing peer connection for ${userId}`);
      return existingPc;
    }

    const pc = new RTCPeerConnection(this.config);

    pc.onicecandidate = (event) => {
      if (event.candidate) {
        this.send({
          type: "ice_candidate",
          target: userId,
          candidate: event.candidate,
        });
      }
    };

    pc.ontrack = (event) => {
      console.log(
        `Received track from ${userId}:`,
        event.track.kind,
        "stream:",
        event.streams[0],
        "active:",
        event.streams[0]?.active
      );
      const stream = event.streams[0];

      if (!stream) {
        console.warn(`No stream in ontrack event from ${userId}`);
        return;
      }

      // Stream'i sakla (çoklu presenter için)
      this.remoteStreams.set(userId, stream);

      // Track event listeners ekle
      event.track.onended = () => {
        console.log(`Track ended from ${userId}:`, event.track.kind);
        // Track bittiğinde stream'i kontrol et, stream aktif değilse kaldır
        const storedStream = this.remoteStreams.get(userId);
        if (storedStream) {
          const activeTracks = storedStream
            .getTracks()
            .filter((t) => t.readyState === "live");
          if (activeTracks.length === 0) {
            console.log(`All tracks ended for ${userId}, removing stream`);
            this.remoteStreams.delete(userId);
          }
        }
      };
      event.track.onmute = () => {
        console.log(`Track muted from ${userId}:`, event.track.kind);
      };
      event.track.onunmute = () => {
        console.log(`Track unmuted from ${userId}:`, event.track.kind);
      };

      // Eski callback: tek stream (geriye uyumluluk)
      if (this.onRemoteStream) {
        this.onRemoteStream(stream);
      }

      // Yeni callback: tüm presenter stream'leri
      if (this.onRemoteStreams) {
        this.onRemoteStreams(this.remoteStreams);
      }
    };

    pc.onconnectionstatechange = () => {
      console.log(`Connection state with ${userId}:`, pc.connectionState);
      if (this.onConnectionStateChange) {
        this.onConnectionStateChange(pc.connectionState, userId);
      }
      // Connection failed veya disconnected ise temizlik yap
      if (
        pc.connectionState === "failed" ||
        pc.connectionState === "disconnected"
      ) {
        console.log(
          `Connection ${pc.connectionState} for ${userId}, cleaning up resources`
        );
        // Pending ICE candidates'ı temizle
        if (
          this.pendingIceCandidates &&
          this.pendingIceCandidates.has(userId)
        ) {
          this.pendingIceCandidates.delete(userId);
          console.log(
            `Cleared pending ICE candidates for ${userId} due to ${pc.connectionState}`
          );
        }
      }
      // Connection closed ise tam temizlik
      if (pc.connectionState === "closed") {
        this.cleanupUserResources(userId);
      }
    };

    this.peerConnections.set(userId, pc);
    return pc;
  }

  async createOfferForUser(userId) {
    if (!this.localStream) {
      console.log(`No local stream for offer to ${userId}`);
      return;
    }

    let pc = this.peerConnections.get(userId);
    if (!pc) {
      pc = this.createPeerConnection(userId);
    }

    console.log(
      `Creating offer for ${userId}, signalingState: ${pc.signalingState}`
    );

    // Eğer zaten stable state'deyse ve track'ler ekliyse, sadece renegotiate et
    const senders = pc.getSenders();

    // Track'leri ekle veya güncelle
    for (const track of this.localStream.getTracks()) {
      const sender = senders.find((s) => s.track?.kind === track.kind);
      if (sender) {
        // Mevcut sender varsa track'i değiştir
        try {
          await sender.replaceTrack(track);
          console.log(`Replaced ${track.kind} track for ${userId}`);
        } catch (e) {
          console.warn(`Replace track error for ${userId}:`, e);
        }
      } else {
        // Yeni track ekle
        try {
          pc.addTrack(track, this.localStream);
          console.log(`Added ${track.kind} track for ${userId}`);
        } catch (e) {
          console.warn(`Add track error for ${userId}:`, e);
        }
      }
    }

    // Sadece stable state'deyken offer oluştur
    if (pc.signalingState === "stable") {
      try {
        const offer = await pc.createOffer({
          offerToReceiveAudio: true,
          offerToReceiveVideo: true,
        });
        await pc.setLocalDescription(offer);

        this.send({
          type: "offer",
          target: userId,
          sdp: pc.localDescription,
        });
        console.log(`Offer sent to ${userId}`);
      } catch (e) {
        console.error(`Error creating offer for ${userId}:`, e);
      }
    } else {
      console.log(`Skipping offer for ${userId}, state: ${pc.signalingState}`);
    }
  }

  async handleOffer(fromUserId, sdp) {
    console.log(`Handling offer from ${fromUserId}`);

    let pc = this.peerConnections.get(fromUserId);
    if (!pc) {
      pc = this.createPeerConnection(fromUserId);
    }

    try {
      await pc.setRemoteDescription(new RTCSessionDescription(sdp));
      console.log(`Remote description set for ${fromUserId}`);

      // Bekleyen ICE candidate'leri işle
      if (
        this.pendingIceCandidates &&
        this.pendingIceCandidates.has(fromUserId)
      ) {
        const candidates = this.pendingIceCandidates.get(fromUserId);
        console.log(
          `Processing ${candidates.length} queued ICE candidates for ${fromUserId}`
        );
        for (const candidate of candidates) {
          try {
            await pc.addIceCandidate(new RTCIceCandidate(candidate));
          } catch (e) {
            console.warn("Error adding queued ICE candidate:", e);
          }
        }
        this.pendingIceCandidates.delete(fromUserId);
      }

      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);

      this.send({
        type: "answer",
        target: fromUserId,
        sdp: pc.localDescription,
      });
      console.log(`Answer sent to ${fromUserId}`);
    } catch (e) {
      console.error(`Error handling offer from ${fromUserId}:`, e);
    }
  }

  async handleAnswer(fromUserId, sdp) {
    const pc = this.peerConnections.get(fromUserId);
    if (pc) {
      // Sadece have-local-offer state'indeyken answer kabul et
      if (pc.signalingState === "have-local-offer") {
        await pc.setRemoteDescription(new RTCSessionDescription(sdp));
      } else {
        console.warn(
          `Ignoring answer from ${fromUserId}, wrong state: ${pc.signalingState}`
        );
      }
    }
  }

  async handleIceCandidate(fromUserId, candidate) {
    // Video peer connection için
    const pc = this.peerConnections.get(fromUserId);
    if (pc && candidate) {
      try {
        // Remote description varsa ekle, yoksa beklet
        if (pc.remoteDescription && pc.remoteDescription.type) {
          await pc.addIceCandidate(new RTCIceCandidate(candidate));
        } else {
          console.log(
            `Queuing ICE candidate for ${fromUserId}, no remote description yet`
          );
          // ICE candidate'leri kuyrukta tut
          if (!this.pendingIceCandidates) {
            this.pendingIceCandidates = new Map();
          }
          if (!this.pendingIceCandidates.has(fromUserId)) {
            this.pendingIceCandidates.set(fromUserId, []);
          }
          // Memory leak koruması: Maksimum 50 candidate sakla
          const candidates = this.pendingIceCandidates.get(fromUserId);
          if (candidates.length < 50) {
            candidates.push(candidate);
          } else {
            console.warn(
              `ICE candidate queue full for ${fromUserId}, dropping candidate`
            );
          }
        }
      } catch (e) {
        console.warn("Video ICE candidate error:", e);
      }
    }

    // Viewer audio peer connection için (host tarafı)
    const audioPc = this.viewerAudioConnections.get(fromUserId);
    if (audioPc && candidate) {
      try {
        if (audioPc.remoteDescription && audioPc.remoteDescription.type) {
          await audioPc.addIceCandidate(new RTCIceCandidate(candidate));
        }
      } catch (e) {
        console.warn("Viewer audio ICE candidate error:", e);
      }
    }
  }

  closePeerConnection(userId) {
    const pc = this.peerConnections.get(userId);
    if (pc) {
      pc.close();
      this.peerConnections.delete(userId);
    }

    // Pending ICE candidates'ı temizle
    if (this.pendingIceCandidates && this.pendingIceCandidates.has(userId)) {
      this.pendingIceCandidates.delete(userId);
      console.log(`Cleared pending ICE candidates for ${userId}`);
    }

    // Remote stream'i temizle
    if (this.remoteStreams.has(userId)) {
      const stream = this.remoteStreams.get(userId);
      // Stream'deki tüm track'leri durdur
      stream.getTracks().forEach((track) => {
        track.stop();
      });
      this.remoteStreams.delete(userId);
      console.log(`Cleared remote stream for ${userId}`);
    }
  }

  // Viewer audio handling (host tarafı)
  async handleViewerAudioOffer(fromUserId, username, sdp) {
    console.log(`Viewer audio offer received from ${username} (${fromUserId})`);

    const pc = new RTCPeerConnection(this.config);

    pc.ontrack = (event) => {
      console.log(`Viewer audio track received from ${username}`);
      if (this.onViewerAudio) {
        this.onViewerAudio(fromUserId, username, event.streams[0]);
      }
    };

    pc.onicecandidate = (event) => {
      if (event.candidate) {
        console.log(`Sending ICE candidate to viewer ${username}`);
        this.send({
          type: "ice_candidate",
          target: fromUserId,
          candidate: event.candidate,
        });
      }
    };

    pc.onconnectionstatechange = () => {
      console.log(
        `Viewer audio connection state (${username}):`,
        pc.connectionState
      );
    };

    this.viewerAudioConnections.set(fromUserId, pc);

    await pc.setRemoteDescription(new RTCSessionDescription(sdp));
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);

    this.send({
      type: "viewer_audio_answer",
      target: fromUserId,
      sdp: pc.localDescription,
    });

    console.log(`Viewer audio answer sent to ${username}`);
  }

  closeViewerAudioConnection(userId) {
    const pc = this.viewerAudioConnections.get(userId);
    if (pc) {
      pc.close();
      this.viewerAudioConnections.delete(userId);
    }

    // Viewer audio için de pending ICE candidates temizle
    if (this.pendingIceCandidates && this.pendingIceCandidates.has(userId)) {
      this.pendingIceCandidates.delete(userId);
      console.log(`Cleared pending ICE candidates for viewer audio ${userId}`);
    }
  }

  // Belirli bir kullanıcı için tüm kaynakları temizle
  cleanupUserResources(userId) {
    // Pending ICE candidates temizle
    if (this.pendingIceCandidates && this.pendingIceCandidates.has(userId)) {
      this.pendingIceCandidates.delete(userId);
      console.log(`Cleared pending ICE candidates for ${userId}`);
    }

    // Remote stream'i temizle
    if (this.remoteStreams.has(userId)) {
      const stream = this.remoteStreams.get(userId);
      stream.getTracks().forEach((track) => track.stop());
      this.remoteStreams.delete(userId);
      console.log(`Cleared remote stream for ${userId}`);
    }
  }

  // Tüm pending ICE candidates'ı temizle
  cleanupAllCandidates() {
    if (this.pendingIceCandidates) {
      const size = this.pendingIceCandidates.size;
      this.pendingIceCandidates.clear();
      console.log(`Cleared all pending ICE candidates (${size} users)`);
    }
  }

  // Tüm remote stream'leri temizle
  cleanupAllRemoteStreams() {
    for (const [userId, stream] of this.remoteStreams) {
      stream.getTracks().forEach((track) => track.stop());
    }
    const size = this.remoteStreams.size;
    this.remoteStreams.clear();
    console.log(`Cleared all remote streams (${size} users)`);
  }

  // Başka biri paylaşıyor mu kontrol et (çoklu presenter desteği)
  canShare() {
    // Zaten paylaşıyorsak true
    if (this.isScreenSharing || this.isCameraSharing) return true;
    // Maksimum presenter sayısına ulaşılmadıysa true
    return Object.keys(this.presenters).length < this.maxPresenters;
  }

  // Şu anki presenter bilgisi
  getCurrentPresenter() {
    return {
      id: this.currentPresenterId,
      name: this.currentPresenterName,
    };
  }

  // Tüm presenter'ları getir
  getPresenters() {
    return this.presenters;
  }

  // Presenter sayısı
  getPresenterCount() {
    return Object.keys(this.presenters).length;
  }

  // Annotation gönder (ekran üzerine çizim)
  sendAnnotation(annotationData) {
    this.send({
      type: "annotation",
      tool: annotationData.tool, // pen, laser, highlight, eraser
      color: annotationData.color,
      size: annotationData.size,
      fromX: annotationData.fromX,
      fromY: annotationData.fromY,
      toX: annotationData.toX,
      toY: annotationData.toY,
      presenterId: annotationData.presenterId, // Hangi presenter'ın ekranına çiziliyor
    });
  }

  // Dosya paylaş (FormData ile multipart upload, progress callback destekli)
  async shareFile(file, onProgress) {
    // Dosya boyutu kontrolü (max 10MB)
    const maxSize = 10 * 1024 * 1024;
    if (file.size > maxSize) {
      throw new Error("Dosya boyutu 10MB'dan büyük olamaz");
    }

    try {
      // FormData ile multipart upload
      const formData = new FormData();
      formData.append("file", file);
      formData.append("room_id", this.roomId);

      // Authorization header'ı al (Content-Type yok, browser otomatik ekler)
      const token = Auth.getToken();
      const headers = token ? { Authorization: `Bearer ${token}` } : {};

      const response = await fetch("/api/files/upload", {
        method: "POST",
        headers: headers,
        body: formData,
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Dosya yüklenemedi");
      }

      const result = await response.json();

      // WebSocket üzerinden sadece file_id gönder
      this.send({
        type: "file_share",
        file_id: result.file_id,
        timestamp: new Date().toISOString(),
      });

      return result;
    } catch (error) {
      throw new Error(error.message || "Dosya yüklenirken hata oluştu");
    }
  }

  // Dosyayı indir (file_id ile)
  async downloadFile(fileId, filename) {
    try {
      // Authorization header'ı al
      const token = Auth.getToken();
      const headers = token ? { Authorization: `Bearer ${token}` } : {};

      const response = await fetch(`/api/files/download/${fileId}`, {
        headers: headers,
      });

      if (!response.ok) {
        throw new Error("Dosya indirilemedi");
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Download error:", error);
      throw error;
    }
  }

  // Paylaşılan dosyaları getir
  getSharedFiles() {
    return this.sharedFiles;
  }

  sendChatMessage(message) {
    this.send({
      type: "chat",
      message: message,
      timestamp: new Date().toISOString(),
    });
  }

  kickUser(userId) {
    this.send({ type: "kick_user", target: userId });
  }

  endRoom() {
    this.send({ type: "end_room" });
  }

  disconnect() {
    this.stopPingInterval();
    this.stopScreenShare();
    this.stopViewerAudio(); // Viewer audio'yu temizle

    for (const [userId] of this.peerConnections) {
      this.closePeerConnection(userId);
    }

    for (const [userId] of this.viewerAudioConnections) {
      this.closeViewerAudioConnection(userId);
    }

    // Tüm kalan kaynakları temizle
    this.cleanupAllCandidates();
    this.cleanupAllRemoteStreams();

    // Reconnect'i iptal et (manuel disconnect)
    this.cancelReconnect();

    if (this.ws) {
      this.ws.close();
    }
  }
}

window.WebRTCManager = WebRTCManager;
