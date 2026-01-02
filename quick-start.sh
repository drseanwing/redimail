#!/bin/bash
#
# REdI Email API - Quick Start Script
# 
# Quickly deploys the API locally for testing
#
# Author: Sean Wing
# Date: 2026-01-02

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}REdI Email API - Quick Start${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Check prerequisites
echo -e "${BLUE}Checking prerequisites...${NC}"

if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}⚠${NC}  Docker not found. Please install Docker first."
    exit 1
fi
echo -e "${GREEN}✓${NC} Docker installed"

if ! command -v docker-compose &> /dev/null; then
    echo -e "${YELLOW}⚠${NC}  Docker Compose not found. Please install Docker Compose first."
    exit 1
fi
echo -e "${GREEN}✓${NC} Docker Compose installed"

# Create .env if it doesn't exist
if [ ! -f ".env" ]; then
    echo ""
    echo -e "${BLUE}Creating .env file...${NC}"
    cp .env.example .env
    
    echo -e "${YELLOW}⚠${NC}  Please edit .env and set:"
    echo "     - OPENAI_API_KEY"
    echo "     - REDI_API_KEY"
    echo "     - POSTGRES_PASSWORD"
    echo ""
    echo "Generate API key: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
    echo ""
    read -p "Press Enter after editing .env..."
fi

# Check if .env has placeholders
if grep -q "your-openai-api-key-here" .env; then
    echo -e "${YELLOW}⚠${NC}  Warning: .env still contains placeholders!"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Build and start services
echo ""
echo -e "${BLUE}Building and starting services...${NC}"
docker-compose up -d --build

# Wait for services to be healthy
echo ""
echo -e "${BLUE}Waiting for services to start...${NC}"
sleep 10

# Check health
echo ""
echo -e "${BLUE}Checking API health...${NC}"
if curl -s http://localhost:5000/health | grep -q "healthy"; then
    echo -e "${GREEN}✓${NC} API is healthy!"
else
    echo -e "${YELLOW}⚠${NC}  API may not be ready yet. Check logs: docker logs redi-api"
fi

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}✓ Services Started!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${BLUE}Service URLs:${NC}"
echo "  API:      http://localhost:5000"
echo "  Health:   http://localhost:5000/health"
echo "  Database: localhost:5432"
echo ""
echo -e "${BLUE}View Logs:${NC}"
echo "  API:      docker logs -f redi-api"
echo "  Database: docker logs -f redi-db"
echo ""
echo -e "${BLUE}Stop Services:${NC}"
echo "  docker-compose down"
echo ""
echo -e "${BLUE}Test API:${NC}"
echo '  curl -H "Authorization: Bearer \$REDI_API_KEY" http://localhost:5000/api/statistics'
echo ""
echo -e "${GREEN}Ready!${NC}"
