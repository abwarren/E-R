#!/bin/bash
# W4P Remote Control - Local Stop Script
echo "Stopping W4P Remote Control local stack..."
pkill -f "python app.py" 2>/dev/null && echo "  Backend stopped" || echo "  No backend process found"
pkill -f "node server.js" 2>/dev/null && echo "  Frontend stopped" || echo "  No frontend process found"
sleep 1
echo "Done."
