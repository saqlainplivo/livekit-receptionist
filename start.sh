#!/bin/bash
# Start both the LiveKit agent worker and the FastAPI server

# Start the LiveKit agent in the background
python agent.py start &
AGENT_PID=$!

# Start the FastAPI server in the foreground
python server.py &
SERVER_PID=$!

# If either process exits, shut down both
trap "kill $AGENT_PID $SERVER_PID 2>/dev/null" EXIT

wait -n
exit $?
