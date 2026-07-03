# PORT Regression Analysis

## Expected startup flow

1. Dockerfile defines the runtime image.
   - `ENV PORT=1080`
   - `CMD ["/entrypoint.sh"]`
2. Docker container starts using `entrypoint.sh`.
3. `entrypoint.sh` changes to `/app/backend` and starts Flask with:
   - `python app.py &`
4. `docker-compose.yml` provides the container environment.
   - `PORT=1080` is declared under `services.remote.environment`
5. Flask should inherit `PORT=1080` and bind to port 1080.

## Actual startup flow

- `Dockerfile`
  - defines `ENV PORT=1080`
  - exposes `1080` and `4000`
  - copies `entrypoint.sh`
  - sets `CMD ["/entrypoint.sh"]`

- `entrypoint.sh`
  - `cd /app/backend`
  - starts Flask with `python app.py &`
  - does not explicitly prefix the command with `PORT=1080`
  - waits for `http://127.0.0.1:1080/api/health`
  - starts Express frontend afterwards

- `docker-compose.yml`
  - for service `remote`
  - sets `environment:`
    - `PORT=1080`
    - `FLASK_ENV=production`
    - `PYTHONUNBUFFERED=1`
    - `ENGINE_URL=http://engine:5002`

- The container runtime environment
  - `PORT` is present inside the running `er-remote` container
  - `python app.py` is the actual Flask startup command

## Environment variables

### Actual container checks

- `docker exec er-remote sh -lc 'env | grep PORT || true'`
  - output: `PORT=1080`

- `docker exec er-remote sh -lc 'echo "PORT=$PORT"'`
  - output: `PORT=1080`

- Flask process environment from `/proc/<pid>/environ`
  - `PORT=1080`

### Evidence from the Flask process

- Exact command used to start Flask in the container:
  - `python app.py &`

- Process environment contains:
  - `PORT=1080`

## Root cause

In the inspected Docker container startup path, `app.py` is not defaulting to port 4000; it receives `PORT=1080` from the container environment. The Flask process inherits `PORT=1080`, and the container environment exposes that value.

## Evidence

1. `Dockerfile` defines `ENV PORT=1080`.
2. `docker-compose.yml` passes `PORT=1080` to `services.remote.environment`.
3. `entrypoint.sh` starts Flask with `python app.py &`.
4. Live container environment check:
   - `env | grep PORT` returned `PORT=1080`
   - `echo $PORT` returned `PORT=1080`
5. Flask process `/proc/<pid>/environ` contains `PORT=1080`.

## Recommended fix

- Do not change anything yet.
- Since the Docker startup path currently preserves `PORT=1080`, the next investigation should focus on other runtime variants where `app.py` may be launched without the inherited environment.

## Risk assessment

- Low risk to the current container startup path: Docker and entrypoint flow are consistent with `PORT=1080`.
- The current evidence does not support a Docker path regression in which `PORT=1080` is lost.
- If a failure is observed, it likely occurs outside the inspected container startup path or in a different runtime scenario.
