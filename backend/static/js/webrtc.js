// WebRTC Manager - Ekran paylaşımı ve ses iletimi
class WebRTCManager {
  constructor(roomId, isHost) {
    this.roomId = roomId;
    this.isHost = isHost;
    this.localStream = null;
    this.peerConnections = new Map(); // userId -> RTCPeerConnection
    this.ws = null;
    this.onRemoteStream = null;
    this.onParticipantUpdate = null;
    this.onChatMessage = null;
    this.onConnectionStateChange = null;
    this.isScreenSharing = false;
    this.isMuted = true;

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
        break;

      case "user_joined":
        if (this.onParticipantUpdate) {
          this.onParticipantUpdate(data.participants, data);
        }
        // Host ise yeni kullanıcıya offer gönder
        if (this.isHost && this.isScreenSharing) {
          await this.createOfferForUser(data.user_id);
        }
        break;

      case "user_left":
        this.closePeerConnection(data.user_id);
        if (this.onParticipantUpdate) {
          this.onParticipantUpdate(data.participants, data);
        }
        break;

      case "request_offer":
        // Viewer offer istiyor
        if (this.isHost && this.isScreenSharing) {
          await this.createOfferForUser(data.from);
        }
        break;

      case "offer":
        // Viewer olarak offer aldık
        if (!this.isHost) {
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
        // Host ekran paylaşımı başlattı, offer iste
        if (!this.isHost) {
          this.send({ type: "request_offer" });
        }
        break;

      case "screen_share_stopped":
        if (!this.isHost && this.onRemoteStream) {
          this.onRemoteStream(null);
        }
        break;

      case "chat":
        if (this.onChatMessage) {
          this.onChatMessage(data);
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
    try {
      this.localStream = await navigator.mediaDevices.getDisplayMedia({
        video: { cursor: "always", displaySurface: "monitor" },
        audio: false,
      });

      // Ekran paylaşımı durduğunda
      this.localStream.getVideoTracks()[0].onended = () => {
        this.stopScreenShare();
      };

      this.isScreenSharing = true;
      this.send({ type: "screen_share_started" });

      // Mevcut viewer'lara offer gönder
      for (const [userId] of this.peerConnections) {
        await this.createOfferForUser(userId);
      }

      return this.localStream;
    } catch (error) {
      console.error("Screen share error:", error);
      throw error;
    }
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
    this.send({ type: "screen_share_stopped" });

    // Tüm peer connection'ları kapat
    for (const [userId] of this.peerConnections) {
      this.closePeerConnection(userId);
    }
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
    const pc = this.peerConnections.get(fromUserId);
    if (pc && candidate) {
      await pc.addIceCandidate(new RTCIceCandidate(candidate));
    }
  }

  closePeerConnection(userId) {
    const pc = this.peerConnections.get(userId);
    if (pc) {
      pc.close();
      this.peerConnections.delete(userId);
    }
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

    if (this.ws) {
      this.ws.close();
    }
  }
}

window.WebRTCManager = WebRTCManager;
