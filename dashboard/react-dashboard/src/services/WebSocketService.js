export class WebSocketService {
  constructor(url) {
    this.url = url
    this.socket = null
    this.listeners = new Set()
    this.statusListeners = new Set()
    this.reconnectTimer = null
  }

  connect() {
    if (this.socket) return
    this.socket = new WebSocket(this.url)
    this._emitStatus('connecting')

    this.socket.onopen = () => this._emitStatus('connected')
    this.socket.onerror = () => this._emitStatus('error')
    this.socket.onclose = () => {
      this._emitStatus('disconnected')
      this.socket = null
      this.reconnectTimer = setTimeout(() => this.connect(), 2000)
    }
    this.socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data)
        this.listeners.forEach((listener) => listener(payload))
      } catch {
        // Ignore malformed payloads.
      }
    }
  }

  subscribe(listener) {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  onStatus(listener) {
    this.statusListeners.add(listener)
    return () => this.statusListeners.delete(listener)
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.socket) {
      this.socket.close()
      this.socket = null
    }
  }

  _emitStatus(status) {
    this.statusListeners.forEach((listener) => listener(status))
  }
}
