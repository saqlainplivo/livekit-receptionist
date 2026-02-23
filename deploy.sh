#!/bin/bash
#
# Day6_live: Deploy LiveKit + Groq agent to Railway
#

set -e

echo "=========================================="
echo "  Day6_live — Railway Deployment"
echo "=========================================="

# Step 1: Initialize Railway project
echo ""
echo "Step 1: Initialize Railway project"
echo "----------------------------------"
echo "  railway init"
echo "  railway link"
echo ""
read -p "Press Enter once you've initialized and linked the project..."

# Step 2: Set environment variables
echo ""
echo "Step 2: Set environment variables"
echo "----------------------------------"
echo "Run these commands (replace with your actual keys):"
echo ""
echo '  railway variables set DEEPGRAM_API_KEY="..."'
echo '  railway variables set GROQ_API_KEY="..."'
echo '  railway variables set LIVEKIT_API_KEY="..."'
echo '  railway variables set LIVEKIT_API_SECRET="..."'
echo '  railway variables set LIVEKIT_URL="wss://..."'
echo '  railway variables set POSTGRES_URL="postgresql://..."'
echo ""
read -p "Press Enter once you've set all environment variables..."

# Step 3: Deploy
echo ""
echo "Step 3: Deploy to Railway"
echo "----------------------------------"
echo "Running: railway up"
echo ""
railway up

# Step 4: Get public domain
echo ""
echo "Step 4: Get your public URL"
echo "----------------------------------"
echo "Running: railway domain"
echo ""
railway domain

echo ""
echo "=========================================="
echo "  Deployment Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Copy your Railway URL"
echo "  2. Test health: curl https://<your-app>.up.railway.app/health"
echo "  3. Check logs: railway logs"
echo ""
