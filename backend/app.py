from flask import Flask, request, jsonify, send_from_directory, Response
import threading, time, uuid, random, os, json

APP_ROOT = os.path.dirname(os.path.dirname(__file__))
SOURCE_DIR = os.path.join(APP_ROOT, '..', 'source') if 'source' in os.listdir(APP_ROOT) else os.path.join(APP_ROOT, '..', 'source')
STATE_DIR = os.path.join(os.path.dirname(APP_ROOT), 'state')
os.makedirs(STATE_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)

jobs = {}

@app.route('/')
@app.route('/engine/')
def index():
    return send_from_directory(os.path.join(os.path.dirname(APP_ROOT), 'source'), 'engine.html')

@app.route('/api/health')
def health():
    return jsonify({'ok': True})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    if data.get('username') == 'admin' and data.get('password') == 'PokerPass12345':
        token = 'local-token-' + uuid.uuid4().hex
        return jsonify({'ok': True, 'token': token})
    return jsonify({'ok': False, 'error': 'invalid credentials'}), 401

@app.route('/api/run', methods=['POST'])
def run_job():
    data = request.get_json() or {}
    run_id = 'run-' + uuid.uuid4().hex[:8]
    samples = int(data.get('samples', 2000))
    hands = data.get('hands', [])
    jobs[run_id] = {'status': 'queued', 'samples': samples, 'hands': hands, 'result': None}

    def worker(rid, smpl, hs):
        jobs[rid]['status'] = 'running'
        # simulate work and stream progress into file
        total = smpl
        hits = [0]*len(hs or [1])
        for i in range(total):
            # random simulate equities
            for j in range(len(hs)):
                hits[j] += random.random()
            if i % max(1, total//10) == 0:
                jobs[rid]['progress'] = int((i/total)*100)
            time.sleep(0.0005)
        # build simple result
        matchups = []
        for idx, h in enumerate(hs):
            fav = 100.0 * hits[idx] / max(1, sum(hits))
            matchups.append({'favourite_hand': h, 'underdog_hand': '', 'fav_real': round(fav,2), 'und_real': round(100-fav,2)})
        result = {'matchups': matchups, 'cores': 1}
        jobs[rid]['status'] = 'done'
        jobs[rid]['result'] = result
        # persist to state file
        try:
            with open(os.path.join(STATE_DIR, rid + '.json'), 'w') as f:
                json.dump({'run_id': rid, 'data': result}, f)
        except Exception:
            pass

    t = threading.Thread(target=worker, args=(run_id, samples, hands), daemon=True)
    t.start()
    return jsonify({'ok': True, 'run_id': run_id})

@app.route('/api/results/<run_id>')
def results(run_id):
    j = jobs.get(run_id)
    if not j:
        return jsonify({'ok': False, 'error': 'not found'}), 404
    if j['status'] == 'done':
        return jsonify({'ok': True, 'status': 'done', 'data': j['result']})
    return jsonify({'ok': True, 'status': j.get('status','queued'), 'progress': j.get('progress',0)})

@app.route('/api/stream/<run_id>')
def stream(run_id):
    def event_stream():
        last_progress = -1
        while True:
            j = jobs.get(run_id)
            if not j:
                yield 'event: error\ndata: not found\n\n'
                break
            progress = j.get('progress',0)
            if progress != last_progress:
                yield f'data: {json.dumps({"progress": progress})}\n\n'
                last_progress = progress
            if j.get('status') == 'done':
                yield f'data: {json.dumps({"progress":100, "status":"done"})}\n\n'
                break
            time.sleep(0.5)
    return Response(event_stream(), mimetype='text/event-stream')

# Static assets route (serve from source)
@app.route('/<path:filename>')
def static_files(filename):
    base = os.path.join(os.path.dirname(APP_ROOT), 'source')
    if os.path.exists(os.path.join(base, filename)):
        return send_from_directory(base, filename)
    return jsonify({'error': 'not found'}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002)
