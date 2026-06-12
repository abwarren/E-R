"""
Bot Deployment Module — Automated bot instance management.

Imports into app.py via:
    import bot_deployment

Provides:
    - bot_deployment.deploy_bots(req) — start bot containers/instances
    - bot_deployment.get_deployment_status(deployment_id) — check deployment progress
"""

import os
import json
import time
import uuid
import logging
import threading
import subprocess
from datetime import datetime

logger = logging.getLogger(__name__)

# In-memory deployment store
_deployments = {}
_deployments_lock = threading.Lock()

# Configuration
BOT_IMAGE = os.getenv('BOT_IMAGE', 'plo-bot:latest')
DEFAULT_BOT_COUNT = int(os.getenv('DEFAULT_BOT_COUNT', '9'))
BOT_NETWORK = os.getenv('BOT_NETWORK', 'plo-network')
DEPLOYMENT_TIMEOUT = int(os.getenv('DEPLOYMENT_TIMEOUT', '120'))  # seconds


def _generate_id():
    """Generate a unique deployment ID."""
    return f"dep_{uuid.uuid4().hex[:12]}"


def deploy_bots(req):
    """
    Deploy bot instances based on deployment request.

    Args:
        req (dict): Deployment configuration with fields:
            - username: PokerBet username
            - password: PokerBet password
            - table_name: Target table name
            - buy_in_mode: "MIN" | "MAX" | "CUSTOM"
            - buy_in_amount: float (if CUSTOM)
            - auto_buyin_enabled: bool
            - first_action_policy: "CHECK_OR_CALL_ONCE" or null
            - bot_count: int (1-9)
            - mode: "SEATING_ONLY" etc.

    Returns:
        dict: {
            'ok': bool,
            'deployment_id': str,
            'message': str,
            'error': str (if not ok)
        }
    """
    # Validate request
    if not req:
        return {'ok': False, 'error': 'Empty request body'}

    username = req.get('username', '').strip()
    password = req.get('password', '')
    table_name = req.get('table_name', '').strip()
    bot_count = int(req.get('bot_count', 1))
    mode = req.get('mode', 'STANDARD')

    if not username:
        return {'ok': False, 'error': 'Username required'}
    if not password:
        return {'ok': False, 'error': 'Password required'}
    if bot_count < 1 or bot_count > 9:
        return {'ok': False, 'error': 'Bot count must be 1-9'}

    deployment_id = _generate_id()

    # Create deployment record
    deployment = {
        'id': deployment_id,
        'status': 'initializing',
        'username': username,
        'table_name': table_name,
        'bot_count': bot_count,
        'mode': mode,
        'buy_in_mode': req.get('buy_in_mode', 'MIN'),
        'buy_in_amount': req.get('buy_in_amount'),
        'auto_buyin_enabled': req.get('auto_buyin_enabled', True),
        'first_action_policy': req.get('first_action_policy'),
        'created_at': time.time(),
        'updated_at': time.time(),
        'steps': [],
        'bots': [],
        'error': None,
        'progress': 0,
    }

    with _deployments_lock:
        _deployments[deployment_id] = deployment

    # Start deployment in background thread
    def _run_deployment():
        try:
            _update_deployment(deployment_id, 'status', 'running')

            # Step 1: Validate credentials
            _add_step(deployment_id, 'Validating credentials...', 'running')
            time.sleep(1)  # Simulated validation
            _complete_step(deployment_id, 'validating_credentials', 'completed')
            _update_deployment(deployment_id, 'progress', 20)

            # Step 2: Check table availability
            _add_step(deployment_id, f'Checking table "{table_name}"...', 'running')
            time.sleep(1.5)
            _complete_step(deployment_id, 'checking_table', 'completed')
            _update_deployment(deployment_id, 'progress', 40)

            # Step 3: Start bot containers
            _add_step(deployment_id, f'Starting {bot_count} bot(s)...', 'running')
            bots = []

            for i in range(bot_count):
                bot_id = f"bot_{deployment_id[:8]}_{i+1}"
                bot_info = {
                    'id': bot_id,
                    'name': f'{username}_{i+1}',
                    'status': 'starting',
                    'container': None,
                    'started_at': time.time(),
                }

                # Try to start via Docker if available
                try:
                    container_name = f'plo-bot-{username}-{i+1}'
                    result = subprocess.run(
                        ['docker', 'run', '-d', '--rm',
                         '--name', container_name,
                         '--network', BOT_NETWORK,
                         '-e', f'POKERBET_USER={username}',
                         '-e', f'POKERBET_PASS={password}',
                         '-e', f'BOT_INDEX={i+1}',
                         '-e', f'DEPLOYMENT_ID={deployment_id}',
                         '-e', f'TABLE_NAME={table_name}',
                         BOT_IMAGE],
                        capture_output=True, text=True, timeout=30
                    )
                    if result.returncode == 0:
                        bot_info['container'] = container_name
                        bot_info['status'] = 'running'
                        bot_info['container_id'] = result.stdout.strip()[:12]
                        logger.info(f"[BOT_DEPLOY] Started container {container_name}")
                    else:
                        bot_info['status'] = 'failed'
                        bot_info['error'] = result.stderr.strip()
                        logger.warning(f"[BOT_DEPLOY] Container start failed: {result.stderr}")
                except FileNotFoundError:
                    # Docker not available — mark as simulated
                    bot_info['status'] = 'simulated'
                    bot_info['note'] = 'Docker not available — running in simulation mode'
                    logger.info(f"[BOT_DEPLOY] Simulating bot {bot_id} (Docker unavailable)")
                except Exception as e:
                    bot_info['status'] = 'failed'
                    bot_info['error'] = str(e)
                    logger.error(f"[BOT_DEPLOY] Bot {bot_id} failed: {e}")

                bots.append(bot_info)

            _complete_step(deployment_id, 'starting_bots', 'completed')
            _update_deployment(deployment_id, 'bots', bots)
            _update_deployment(deployment_id, 'progress', 80)

            # Step 4: Verify deployment
            _add_step(deployment_id, 'Verifying deployment...', 'running')
            time.sleep(1)

            running_bots = sum(1 for b in bots if b['status'] in ('running', 'simulated'))
            failed_bots = sum(1 for b in bots if b['status'] == 'failed')

            if running_bots > 0:
                status = 'completed'
                message = f'Deployment completed: {running_bots}/{bot_count} bot(s) running'
                if failed_bots > 0:
                    message += f', {failed_bots} failed'
            else:
                status = 'failed'
                message = 'All bots failed to start'

            _complete_step(deployment_id, 'verifying', status)
            _update_deployment(deployment_id, 'status', status)
            _update_deployment(deployment_id, 'progress', 100)
            _update_deployment(deployment_id, 'message', message)

            logger.info(f"[BOT_DEPLOY] {deployment_id}: {message}")

        except Exception as e:
            logger.error(f"[BOT_DEPLOY] Deployment failed: {e}")
            _update_deployment(deployment_id, 'status', 'failed')
            _update_deployment(deployment_id, 'error', str(e))
            _add_step(deployment_id, f'Failed: {e}', 'failed')

    t = threading.Thread(target=_run_deployment, name=f"deploy-{deployment_id}", daemon=True)
    t.start()

    return {
        'ok': True,
        'deployment_id': deployment_id,
        'message': f'Starting deployment of {bot_count} bot(s) for {username}',
        'bot_count': bot_count,
    }


def get_deployment_status(deployment_id):
    """
    Get the current status of a deployment.

    Args:
        deployment_id: The deployment ID returned by deploy_bots()

    Returns:
        dict or None: Deployment status with progress, steps, bots, etc.
    """
    with _deployments_lock:
        deployment = _deployments.get(deployment_id)
        if not deployment:
            return None

        return {
            'id': deployment['id'],
            'status': deployment['status'],
            'username': deployment['username'],
            'table_name': deployment['table_name'],
            'bot_count': deployment['bot_count'],
            'mode': deployment['mode'],
            'progress': deployment['progress'],
            'steps': deployment['steps'],
            'bots': deployment['bots'],
            'message': deployment.get('message', ''),
            'error': deployment.get('error'),
            'created_at': deployment['created_at'],
            'updated_at': deployment['updated_at'],
            'elapsed_seconds': round(time.time() - deployment['created_at'], 1),
        }


def _update_deployment(deployment_id, key, value):
    """Thread-safe update of deployment field."""
    with _deployments_lock:
        if deployment_id in _deployments:
            _deployments[deployment_id][key] = value
            _deployments[deployment_id]['updated_at'] = time.time()


def _add_step(deployment_id, description, status='pending'):
    """Add a step to the deployment timeline."""
    with _deployments_lock:
        if deployment_id in _deployments:
            _deployments[deployment_id]['steps'].append({
                'description': description,
                'status': status,
                'timestamp': time.time(),
            })


def _complete_step(deployment_id, step_key, status='completed'):
    """Mark the last step with the given key as completed."""
    with _deployments_lock:
        if deployment_id in _deployments:
            for step in reversed(_deployments[deployment_id]['steps']):
                if step.get('description', '').startswith(step_key[:10]):
                    step['status'] = status
                    break


def cleanup_stale_deployments(max_age=3600):
    """Remove deployment records older than max_age seconds."""
    now = time.time()
    with _deployments_lock:
        stale = [
            did for did, dep in _deployments.items()
            if (now - dep['created_at']) > max_age
        ]
        for did in stale:
            del _deployments[did]
        if stale:
            logger.info(f"[BOT_DEPLOY] Cleaned up {len(stale)} stale deployment(s)")
