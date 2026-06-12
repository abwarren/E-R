"""
Windows Instance Management Routes.
Handles Chrome browser window management for bot instances on Windows.
Imports into app.py via:
    from windows_routes import register_windows_routes
    register_windows_routes(app)
"""

import os
import json
import time
import signal
import logging
import subprocess
import threading

logger = logging.getLogger(__name__)

# In-memory store for window instances
_windows_instances = {}
_windows_lock = threading.Lock()

# Configuration
DEFAULT_CHROME_PATH = os.getenv(
    'CHROME_PATH',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
)
REMOTE_DEBUGGING_PORT = int(os.getenv('REMOTE_DEBUGGING_PORT', '9222'))


def _kill_process(pid):
    """Kill a process cross-platform."""
    import platform
    if platform.system() == 'Windows':
        subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                       capture_output=True, timeout=5)
    else:
        os.kill(pid, signal.SIGKILL)


def _discover_windows_instances():
    """Discover running Chrome instances via remote debugging ports."""
    instances = {}
    # Check common debugging ports
    for port_offset in range(10):
        port = REMOTE_DEBUGGING_PORT + port_offset
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        if result == 0:
            # Port is open - likely a Chrome debugging instance
            try:
                import requests
                resp = requests.get(f'http://127.0.0.1:{port}/json/version', timeout=2)
                if resp.status_code == 200:
                    info = resp.json()
                    instances[str(port)] = {
                        'port': port,
                        'pid': info.get('Browser', '').split('/')[-1] if '/' in info.get('Browser', '') else None,
                        'user_data_dir': info.get('userDataDir', 'unknown'),
                        'web_socket_url': info.get('webSocketDebuggerUrl', ''),
                        'discovered_at': time.time(),
                        'status': 'running',
                    }
            except Exception:
                instances[str(port)] = {
                    'port': port,
                    'status': 'unknown',
                    'discovered_at': time.time(),
                }
    return instances


def register_windows_routes(app):
    """Register all Windows instance management routes on the Flask app."""

    @app.route('/api/windows/instances', methods=['GET'])
    def list_windows_instances():
        """List all known Windows Chrome instances."""
        # Auto-discover running instances
        discovered = _discover_windows_instances()

        with _windows_lock:
            # Merge discovered with known instances
            for port, info in discovered.items():
                if port not in _windows_instances:
                    _windows_instances[port] = info
                else:
                    _windows_instances[port].update(info)
                    _windows_instances[port]['last_seen'] = time.time()

            instances = [
                {
                    'port': info.get('port'),
                    'pid': info.get('pid'),
                    'user_data_dir': info.get('user_data_dir'),
                    'web_socket_url': info.get('web_socket_url'),
                    'status': info.get('status', 'unknown'),
                    'label': info.get('label'),
                    'discovered_at': info.get('discovered_at'),
                    'last_seen': info.get('last_seen'),
                }
                for info in _windows_instances.values()
            ]

        return jsonify({
            'ok': True,
            'instances': instances,
            'count': len(instances),
        })

    @app.route('/api/windows/instances', methods=['POST'])
    def launch_windows_instance():
        """
        Launch a new Chrome instance with remote debugging.
        Request body:
        {
            "label": "bot-1",              # optional label
            "user_data_dir": "~/chrome-bot1",  # optional user data dir
            "port": 9223,                   # optional debug port (auto if omitted)
            "url": "https://pokerbet.co.za", # optional URL to open
            "window_size": "1400,900"        # optional window size
        }
        """
        try:
            data = request.get_json(force=True) or {}

            label = data.get('label', f'instance-{int(time.time())}')
            user_data_dir = data.get('user_data_dir', f'/tmp/chrome-{label}')
            port = int(data.get('port', REMOTE_DEBUGGING_PORT + len(_windows_instances)))
            target_url = data.get('url', 'about:blank')
            window_size = data.get('window_size', '1400,900')

            # Ensure user data directory exists
            os.makedirs(user_data_dir, exist_ok=True)

            # Build Chrome command
            chrome_path = data.get('chrome_path', DEFAULT_CHROME_PATH)
            cmd = [
                chrome_path,
                f'--remote-debugging-port={port}',
                f'--user-data-dir={user_data_dir}',
                f'--window-size={window_size}',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-sync',
                '--disable-background-networking',
                target_url,
            ]

            logger.info(f"[WINDOWS] Launching Chrome instance '{label}' on port {port}")

            # Launch Chrome process
            if os.name == 'nt':  # Windows
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:  # Linux/Mac
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            instance_info = {
                'port': port,
                'pid': process.pid,
                'label': label,
                'user_data_dir': user_data_dir,
                'status': 'launching',
                'url': target_url,
                'window_size': window_size,
                'created_at': time.time(),
                'chrome_path': chrome_path,
            }

            with _windows_lock:
                _windows_instances[str(port)] = instance_info

            return jsonify({
                'ok': True,
                'instance': instance_info,
                'message': f'Chrome instance "{label}" launching on port {port}',
            })

        except Exception as e:
            logger.error(f"[WINDOWS] Failed to launch instance: {e}")
            return jsonify({'ok': False, 'error': str(e)}), 500

    @app.route('/api/windows/instances/<port>', methods=['GET'])
    def get_windows_instance(port):
        """Get details of a specific Chrome instance."""
        with _windows_lock:
            instance = _windows_instances.get(port)
            if not instance:
                return jsonify({'ok': False, 'error': 'Instance not found'}), 404

            # Check if still alive
            if instance.get('pid'):
                try:
                    os.kill(instance['pid'], 0)
                    instance['status'] = 'running'
                except (OSError, ProcessLookupError):
                    instance['status'] = 'stopped'

            return jsonify({
                'ok': True,
                'instance': instance,
            })

    @app.route('/api/windows/instances/<port>', methods=['DELETE'])
    def kill_windows_instance(port):
        """Kill a Chrome instance by debug port."""
        with _windows_lock:
            instance = _windows_instances.get(port)
            if not instance:
                return jsonify({'ok': False, 'error': 'Instance not found'}), 404

            pid = instance.get('pid')
            if pid:
                try:
                    _kill_process(pid)
                    logger.info(f"[WINDOWS] Killed instance on port {port} (PID {pid})")
                except (OSError, ProcessLookupError):
                    pass

            del _windows_instances[port]

        return jsonify({'ok': True, 'message': f'Instance on port {port} terminated'})

    @app.route('/api/windows/instances/<port>/navigate', methods=['POST'])
    def navigate_windows_instance(port):
        """Navigate a Chrome instance to a URL."""
        data = request.get_json(force=True) or {}
        url = data.get('url', '')

        if not url:
            return jsonify({'ok': False, 'error': 'URL required'}), 400

        try:
            import requests
            # Use Chrome DevTools Protocol to navigate
            resp = requests.post(
                f'http://127.0.0.1:{port}/json/new?{url}',
                timeout=5
            )
            if resp.status_code == 200:
                return jsonify({'ok': True, 'message': f'Navigated to {url}'})
            else:
                return jsonify({'ok': False, 'error': f'CDP returned {resp.status_code}'}), 500
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500

    @app.route('/api/windows/status', methods=['GET'])
    def windows_platform_status():
        """Check if running on Windows and Chrome availability."""
        chrome_found = os.path.exists(DEFAULT_CHROME_PATH)
        alt_chrome_found = os.path.exists(os.getenv('CHROME_PATH_ALT',
            'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'))

        return jsonify({
            'ok': True,
            'platform': os.name,
            'is_windows': os.name == 'nt',
            'chrome_installed': chrome_found or alt_chrome_found,
            'default_chrome_path': DEFAULT_CHROME_PATH,
            'active_instances': len(_windows_instances),
            'debugging_port_range': [REMOTE_DEBUGGING_PORT, REMOTE_DEBUGGING_PORT + 9],
        })
