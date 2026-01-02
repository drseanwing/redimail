#!/bin/bash
#
# REdI Email API - GitHub Repository Setup Script
# 
# This script initializes a new GitHub repository and pushes the complete codebase.
# 
# Prerequisites:
# 1. GitHub account (seanwing33)
# 2. GitHub CLI installed (gh) or git configured with credentials
# 3. Repository name: redi-email-api
#
# Author: Sean Wing
# Date: 2026-01-02

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}REdI Email API - GitHub Repository Setup${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Check if we're in the right directory
if [ ! -f "Dockerfile" ] || [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}Error: Must run from repository root directory${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Found Docker configuration files"

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo -e "${RED}Error: git is not installed${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Git is installed"

# Repository configuration
GITHUB_USER="seanwing33"
REPO_NAME="redi-email-api"
REPO_URL="https://github.com/${GITHUB_USER}/${REPO_NAME}.git"

echo ""
echo -e "${BLUE}Repository Details:${NC}"
echo "  GitHub User: ${GITHUB_USER}"
echo "  Repository:  ${REPO_NAME}"
echo "  URL:         ${REPO_URL}"
echo ""

# Initialize git repository if not already initialized
if [ ! -d ".git" ]; then
    echo -e "${BLUE}Initializing Git repository...${NC}"
    git init
    echo -e "${GREEN}✓${NC} Git repository initialized"
else
    echo -e "${GREEN}✓${NC} Git repository already initialized"
fi

# Create .env from .env.example if it doesn't exist
if [ ! -f ".env" ]; then
    echo -e "${BLUE}Creating .env file from template...${NC}"
    cp .env.example .env
    echo -e "${GREEN}✓${NC} .env file created"
    echo -e "${RED}⚠${NC}  Remember to edit .env with your actual credentials!"
fi

# Add all files
echo ""
echo -e "${BLUE}Adding files to Git...${NC}"
git add .

# Check if there are changes to commit
if git diff --staged --quiet; then
    echo -e "${GREEN}✓${NC} No new changes to commit"
else
    echo -e "${BLUE}Committing changes...${NC}"
    git commit -m "Initial commit: REdI Email Processing API v2.0

- Docker containerization with PostgreSQL
- Complete API implementation with database logging
- Pre-filtering and sensitivity detection
- GPT-4 integration
- Statistics and monitoring endpoints
- Comprehensive documentation

Features:
- Automated email processing
- Intelligent categorization
- Template-based responses  
- Audit trail in database
- Human review queue
- Cost optimization (40% reduction)
"
    echo -e "${GREEN}✓${NC} Changes committed"
fi

# Check if GitHub CLI is available
if command -v gh &> /dev/null; then
    echo ""
    echo -e "${BLUE}GitHub CLI detected${NC}"
    echo -e "${BLUE}Creating repository on GitHub...${NC}"
    
    # Check if repo already exists
    if gh repo view ${GITHUB_USER}/${REPO_NAME} &> /dev/null; then
        echo -e "${GREEN}✓${NC} Repository already exists on GitHub"
    else
        # Create new repo
        gh repo create ${REPO_NAME} \
            --private \
            --description "Automated email processing API for REdI using GPT-4 and PostgreSQL" \
            --source=. \
            || echo -e "${RED}⚠${NC}  Could not create repo (may already exist)"
        
        echo -e "${GREEN}✓${NC} Repository created on GitHub"
    fi
    
    # Set remote
    git remote remove origin 2>/dev/null || true
    git remote add origin ${REPO_URL}
    echo -e "${GREEN}✓${NC} Remote origin configured"
    
else
    echo ""
    echo -e "${BLUE}GitHub CLI not found${NC}"
    echo -e "${BLUE}Manual repository creation required${NC}"
    echo ""
    echo "Please:"
    echo "  1. Go to https://github.com/new"
    echo "  2. Create repository: ${REPO_NAME}"
    echo "  3. Make it private"
    echo "  4. Do NOT initialize with README"
    echo ""
    read -p "Press Enter when repository is created..."
    
    # Set remote
    git remote remove origin 2>/dev/null || true
    git remote add origin ${REPO_URL}
    echo -e "${GREEN}✓${NC} Remote origin configured"
fi

# Determine default branch name
DEFAULT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "main")

# Rename branch to main if it's master
if [ "$DEFAULT_BRANCH" = "master" ]; then
    git branch -M main
    DEFAULT_BRANCH="main"
    echo -e "${GREEN}✓${NC} Branch renamed to main"
fi

# Push to GitHub
echo ""
echo -e "${BLUE}Pushing to GitHub...${NC}"
git push -u origin ${DEFAULT_BRANCH}

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}✓ Successfully pushed to GitHub!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${BLUE}Repository URL:${NC} ${REPO_URL}"
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo "  1. Edit .env with your credentials"
echo "  2. Start services: docker-compose up -d"
echo "  3. Check health: curl http://localhost:5000/health"
echo "  4. View README: cat README.md"
echo ""
echo -e "${BLUE}Documentation:${NC}"
echo "  - README.md - Complete setup guide"
echo "  - .env.example - Configuration template"
echo "  - docker-compose.yml - Service orchestration"
echo ""
echo -e "${GREEN}Done!${NC}"
