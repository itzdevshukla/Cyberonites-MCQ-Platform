/**
 * WebSocket Manager
 * Handles connection, reconnection, and message routing.
 */
class WebSocketManager {
    constructor(path, handlers = {}) {
        this.path = path;
        this.handlers = handlers;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 2000;
        this.isConnected = false;
        this.connect();
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${window.location.host}${this.path}`;
        
        try {
            this.ws = new WebSocket(url);
        } catch (e) {
            console.warn('WebSocket not available, falling back to polling');
            return;
        }

        this.ws.onopen = () => {
            this.isConnected = true;
            this.reconnectAttempts = 0;
            console.log('WebSocket connected:', this.path);
            if (this.handlers.onConnect) this.handlers.onConnect();
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const type = data.type;
                
                // Route to specific handler
                if (this.handlers[type]) {
                    this.handlers[type](data);
                }
                
                // Always call generic handler if exists
                if (this.handlers.onMessage) {
                    this.handlers.onMessage(data);
                }
            } catch (e) {
                console.error('WebSocket message parse error:', e);
            }
        };

        this.ws.onclose = (event) => {
            this.isConnected = false;
            console.log('WebSocket closed:', event.code);
            this._attemptReconnect();
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    }

    _attemptReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('Max reconnect attempts reached');
            return;
        }
        
        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.min(this.reconnectAttempts, 5);
        
        setTimeout(() => {
            console.log(`Reconnecting... attempt ${this.reconnectAttempts}`);
            this.connect();
        }, delay);
    }

    close() {
        if (this.ws) {
            this.ws.close();
        }
    }
}
