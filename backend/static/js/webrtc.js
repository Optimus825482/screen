// WebRTC Manager - Ekran paylaşımı, kamera paylaşımı ve ses iletimi
class WebRTCManager {
  constructor(roomId, isHost) {
    this.roomId = roomId;
    this.isHost = isHost;
    this.localStream = null;
    this.peerConnections = new Map(); // userId -> RTCPeerConnection
    this.viewerAudioConnections = new Map(); // userId -> RTCPeerConnection (viewer audio için)
    this.ws = null;
    this.onRemoteStream = null;
    this.onViewerAudio = null; // Viewer'dan gelen ses için callback
    this.onParticipantUpdate = null;
    this.onChatMessage = null;
    this.onConnectionStateChange = null;
    this.onPresenterChange = null; // Yeni: Presenter değiştiğinde callback
    this.onWhiteboardDraw = null; // Whiteboard çizim callback
    this.onWhiteboardClear = null; // Whiteboard temizleme callback
    this.onWhiteboardStarted = null; // Whiteboard başladı callback
    this.onWhiteboardStopped = null; // Whiteboard durdu callback
    this.isScreenSharing = false;
    this.isCameraSharing = false; // Kamera paylaşımı durumu
    this.currentFacingMode = "user"; // 'user' = ön kamera, 'environment' = arka kamera
    this.isMuted = true;
    this.currentPresenterId = null; // Şu an kim paylaşıyor
    this.currentPresenterName = null;
    this.currentShareType = null; // 'screen' veya 'camera'
    this.myUserId = null;

    // Metered TURN Server config (API'den güncellenecek)
    this.config = {
      iceServers: [
        { urls: "stun:stun.relay.metered.ca:80" },
        {
          urls: "turn:standard.relay.metered.ca:80",
          username: "a00785389f1b29a83ff4325a",
          credential: "s5K3Fmbw9JY4snea",
        },
        {
          urls: "turn:standard.relay.metered.ca:80?transport=tcp",
          username: "a00785389f1b29a83ff4325a",
          credential: "s5K3Fmbw9JY4snea",
        },
        {
          urls: "turn:standard.relay.metered.ca:443",
          username: "a00785389f1b29a83ff4325a",
          credential: "s5K3Fmbw9JY4snea",
        },
        {
          urls: "turns:standard.relay.metered.ca:443?transport=tcp",
          username: "a00785389f1b29a83ff4325a",
          credential: "s5K3Fmbw9JY4snea",
        },
      ],
    };
  }

  // API'den güncel ICE config al (Metered REST API)
  async fetchIceConfig() {
    try {
      // Önce Metered REST API'den dene (en güncel credentials)
      const meteredResponse = await fetch(
        "https://erkan.metered.live/api/v1/turn/credentials?apiKey=a2278584590ae2fd0bf60959fe0fecb7e3a7"
      );
      if (meteredResponse.ok) {
        const iceServers = await meteredResponse.json();
        this.config = { iceServers };
        console.log("ICE config loaded from Metered API");
        return;
      }
    } catch (error) {
      console.warn("Metered API fetch failed, trying backend:", error);
    }

    // Fallback: Backend API'den al
    try {
      const response = await fetch("/api/rooms/ice-config", {
        headers: Auth.getAuthHeaders(),
      });
      if (response.ok) {
        this.config = await response.json();
        console.log("ICE config loaded from backend");
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

    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log("WebSocket connected");
        this.startPingInterval();
        resolve(true);
      };

      this.ws.onclose = (event) => {
        console.log("WebSocket closed:", event.code, event.reason);
        this.stopPingInterval();
        if (this.onConnectionStateChange) {
          this.onConnectionStateChange("disconnected");
        }
      };

      this.ws.onerror = (error) => {
        console.error("WebSocket error:", error);
        reject(error);
      };

      this.ws.onmessage = (event) => this.handleMessage(JSON.parse(event.data));
    });
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
        // Mevcut kullanıcılar için peer connection oluştur
        for (const participant of data.participants) {
          if (
            participant.user_id !== this.myUserId &&
            !this.peerConnections.has(participant.user_id)
          ) {
            this.createPeerConnection(participant.user_id);
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
        // Ayrılan kişi presenter ise temizle
        if (data.user_id === this.currentPresenterId) {
          this.currentPresenterId = null;
          this.currentPresenterName = null;
          if (this.onPresenterChange) {
            this.onPresenterChange(null, null);
          }
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
        // Birisi ekran paylaşımı başlattı
        this.currentPresenterId = data.presenter_id;
        this.currentPresenterName = data.presenter_name;
        this.currentShareType = data.share_type || "screen";
        if (this.onPresenterChange) {
          this.onPresenterChange(
            data.presenter_id,
            data.presenter_name,
            this.currentShareType
          );
        }
        // Presenter için peer connection oluştur (yoksa)
        if (!this.peerConnections.has(data.presenter_id)) {
          this.createPeerConnection(data.presenter_id);
        }
        // Presenter'dan offer iste
        if (!this.isScreenSharing && !this.isCameraSharing) {
          console.log("Requesting offer from presenter:", data.presenter_id);
          this.send({ type: "request_offer" });
        }
        break;

      case "screen_share_stopped":
        // Paylaşım durduruldu
        this.currentPresenterId = null;
        this.currentPresenterName = null;
        this.currentShareType = null;
        if (this.onPresenterChange) {
          this.onPresenterChange(null, null, null);
        }
        if (this.onRemoteStream) {
          this.onRemoteStream(null);
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
    // Başka biri paylaşıyorsa engelle
    if (
      this.currentPresenterId &&
      !this.isScreenSharing &&
      !this.isCameraSharing
    ) {
      throw new Error("Başka biri ekran paylaşıyor. Lütfen bekleyin.");
    }

    try {
      // Ekran paylaşımı + sistem sesi (tab audio)
      this.localStream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          cursor: "always",
          displaySurface: "monitor",
        },
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 44100,
        },
      });

      // Ekran paylaşımı durduğunda
      this.localStream.getVideoTracks()[0].onended = () => {
        this.stopScreenShare();
      };

      this.isScreenSharing = true;
      this.isCameraSharing = false;
      this.isMuted = false; // Sistem sesi varsa mute değil
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
    // Başka biri paylaşıyorsa engelle
    if (
      this.currentPresenterId &&
      !this.isScreenSharing &&
      !this.isCameraSharing
    ) {
      throw new Error("Başka biri paylaşım yapıyor. Lütfen bekleyin.");
    }

    try {
      this.currentFacingMode = facingMode;

      this.localStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: facingMode,
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      // Kamera durduğunda
      this.localStream.getVideoTracks()[0].onended = () => {
        this.stopCameraShare();
      };

      this.isCameraSharing = true;
      this.isScreenSharing = false;
      this.isMuted = false;
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
      const audioStream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
      const audioTrack = audioStream.getAudioTracks()[0];

      if (this.localStream) {
        this.localStream.addTrack(audioTrack);
      }

      // Mevcut peer connection'lara audio track ekle
      for (const [userId, pc] of this.peerConnections) {
        const sender = pc.getSenders().find((s) => s.track?.kind === "audio");
        if (sender) {
          sender.replaceTrack(audioTrack);
        } else {
          pc.addTrack(audioTrack, this.localStream);
        }
      }

      this.isMuted = false;
      return audioTrack;
    } catch (error) {
      console.error("Audio error:", error);
      throw error;
    }
  }

  toggleMute() {
    if (this.localStream) {
      const audioTracks = this.localStream.getAudioTracks();
      audioTracks.forEach((track) => {
        track.enabled = !track.enabled;
      });
      this.isMuted = !this.isMuted;
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
      if (this.onRemoteStream) {
        this.onRemoteStream(event.streams[0]);
      }
    };

    pc.onconnectionstatechange = () => {
      console.log(`Connection state with ${userId}:`, pc.connectionState);
      if (this.onConnectionStateChange) {
        this.onConnectionStateChange(pc.connectionState, userId);
      }
    };

    this.peerConnections.set(userId, pc);
    return pc;
  }

  async createOfferForUser(userId) {
    if (!this.localStream) return;

    let pc = this.peerConnections.get(userId);
    if (!pc) {
      pc = this.createPeerConnection(userId);
    }

    // Track'leri ekle
    this.localStream.getTracks().forEach((track) => {
      const sender = pc.getSenders().find((s) => s.track?.kind === track.kind);
      if (!sender) {
        pc.addTrack(track, this.localStream);
      }
    });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    this.send({
      type: "offer",
      target: userId,
      sdp: pc.localDescription,
    });
  }

  async handleOffer(fromUserId, sdp) {
    let pc = this.peerConnections.get(fromUserId);
    if (!pc) {
      pc = this.createPeerConnection(fromUserId);
    }

    await pc.setRemoteDescription(new RTCSessionDescription(sdp));
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);

    this.send({
      type: "answer",
      target: fromUserId,
      sdp: pc.localDescription,
    });
  }

  async handleAnswer(fromUserId, sdp) {
    const pc = this.peerConnections.get(fromUserId);
    if (pc) {
      await pc.setRemoteDescription(new RTCSessionDescription(sdp));
    }
  }

  async handleIceCandidate(fromUserId, candidate) {
    // Video peer connection için
    const pc = this.peerConnections.get(fromUserId);
    if (pc && candidate) {
      try {
        await pc.addIceCandidate(new RTCIceCandidate(candidate));
      } catch (e) {
        console.warn("Video ICE candidate error:", e);
      }
    }

    // Viewer audio peer connection için (host tarafı)
    const audioPc = this.viewerAudioConnections.get(fromUserId);
    if (audioPc && candidate) {
      try {
        await audioPc.addIceCandidate(new RTCIceCandidate(candidate));
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
  }

  // Başka biri paylaşıyor mu kontrol et
  canShare() {
    return (
      !this.currentPresenterId || this.isScreenSharing || this.isCameraSharing
    );
  }

  // Şu anki presenter bilgisi
  getCurrentPresenter() {
    return {
      id: this.currentPresenterId,
      name: this.currentPresenterName,
    };
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

    for (const [userId] of this.peerConnections) {
      this.closePeerConnection(userId);
    }

    for (const [userId] of this.viewerAudioConnections) {
      this.closeViewerAudioConnection(userId);
    }

    if (this.ws) {
      this.ws.close();
    }
  }
}

window.WebRTCManager = WebRTCManager;
