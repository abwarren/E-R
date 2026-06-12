Backend files were not cloned from EC2.

The Flask backend runs on EC2 at port 5003 (/opt/plo-equity/backend/app.py).
Per critical rules: EC2 was used in read-only mode only.

The /api/* calls from the remote UI are proxied to the production API at haaats.xyz,
so the remote control functions fully without a local backend.

To run the backend locally in the future:
1. rsync /opt/plo-equity/ from EC2
2. Create a Python venv and install requirements
3. Set up .env with the environment variables
4. Run: gunicorn -w 1 --timeout 60 --bind 0.0.0.0:5003 app:app

