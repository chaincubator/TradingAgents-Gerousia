#!/usr/bin/env python3
"""
TradingAgents Web Application Launcher
"""

import sys
import os
import socket
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from web_app import app, socketio
    print("✅ Successfully imported TradingAgents web application")
except ImportError as e:
    print(f"❌ Failed to import required modules: {e}")
    print("Please make sure all dependencies are installed:")
    print("pip install -r requirements_web.txt")
    sys.exit(1)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))

    # Resolve the machine's outbound IP for display purposes
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as _s:
            _s.connect(("8.8.8.8", 80))
            host_ip = _s.getsockname()[0]
    except Exception:
        host_ip = socket.gethostbyname(socket.gethostname())

    print("🚀 Starting TradingAgents Web Application...")
    print(f"📊 Local:   http://localhost:{port}")
    print(f"🌐 Network: http://{host_ip}:{port}")
    print("🔄 Real-time analysis updates via WebSocket")
    print("📱 Responsive design for desktop and mobile")
    print("=" * 50)

    try:
        socketio.run(app, debug=False, host='0.0.0.0', port=port)
    except KeyboardInterrupt:
        print("\n👋 TradingAgents Web Application stopped by user")
    except Exception as e:
        print(f"❌ Error starting web application: {e}")
        sys.exit(1) 