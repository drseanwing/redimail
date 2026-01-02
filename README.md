# REdI Email Processing API

**Automated email processing system for the Resuscitation Education Initiative (REdI) at Royal Brisbane & Women's Hospital.**

This API intelligently processes incoming emails using GPT-4, applies sensitivity detection, and automatically responds to common queries while flagging complex cases for human review.

## Features

- 🤖 **GPT-4 Powered Analysis** - Intelligent email categorization and response generation
- 🛡️ **Sensitivity Detection** - Automatically blocks responses to complaints, escalations, and HR issues
- ⚡ **Pre-filtering** - Skips GPT for obvious system messages (saves 40% API costs)
- 📊 **Database Logging** - Complete audit trail of all emails and decisions
- 🎯 **Confidence Scoring** - Only responds when confident (prevents inappropriate auto-replies)
- 📧 **Template Engine** - Consistent, professional responses
- 🔍 **Statistics Dashboard** - Track performance and costs

## Architecture

```
Power Automate → API → GPT-4 → Response
                  ↓
              PostgreSQL
              (audit log)
```

**Simple 8-action Power Automate flow:**
1. Email arrives → 2. Lookup context → 3. POST to API → 4. Execute instructions

**API handles all intelligence:**
- Pre-filtering
- Sensitivity detection  
- GPT analysis
- Template selection
- Database logging

## Quick Start

### Prerequisites

- Docker & Docker Compose
- OpenAI API key
- 512MB RAM minimum

### Installation

1. **Clone repository**
```bash
git clone https://github.com/seanwing33/redi-email-api.git
cd redi-email-api
```

2. **Create environment file**
```bash
cp .env.example .env
```

3. **Edit .env with your values**
```bash
nano .env
```

Required variables:
```bash
OPENAI_API_KEY=sk-proj-your-key-here
REDI_API_KEY=generate-secure-random-string
POSTGRES_PASSWORD=strong-password-here
```

Generate secure API key:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

4. **Start services**
```bash
docker-compose up -d
```

5. **Verify health**
```bash
curl http://localhost:5000/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "2.0",
  "database": "connected"
}
```

## API Endpoints

### POST /api/process-email

Process an incoming email.

**Headers:**
```
Authorization: Bearer your-api-key-here
Content-Type: application/json
```

**Request Body:**
```json
{
  "emailId": "unique-email-id",
  "receivedDateTime": "2026-01-02T08:30:00Z",
  "subject": "Certificate request",
  "from": {
    "name": "Dr Sean Wing",
    "email": "sean.wing@health.qld.gov.au"
  },
  "bodyText": "Can I get my ALS certificate?",
  "context": {
    "userBookings": [...],
    "userCertificates": [...]
  }
}
```

**Response:**
```json
{
  "success": true,
  "decision": {
    "shouldRespond": true,
    "confidence": 0.9,
    "action": "send_certificate"
  },
  "response": {
    "bodyHtml": "...",
    "templateId": "certificate_found"
  },
  "actions": [...],
  "humanReview": {
    "required": false
  }
}
```

### GET /api/statistics

Get processing statistics.

**Query Parameters:**
- `days` - Number of days to include (default: 30)

**Example:**
```bash
curl -H "Authorization: Bearer your-key" \
  "http://localhost:5000/api/statistics?days=7"
```

### GET /api/recent-emails

Get recent email records.

**Query Parameters:**
- `limit` - Maximum records to return (default: 50)

### GET /health

Health check endpoint (no authentication required).

## Database Schema

### Tables

- **email_records** - Main email processing records
- **email_responses** - Response content and templates
- **processing_logs** - Detailed reasoning chain

### Views

- **email_statistics** - Daily aggregated stats
- **category_statistics** - Breakdown by email type
- **sensitivity_statistics** - Sensitivity flag analysis

## Accessing the Database

### Option 1: psql Command Line

```bash
docker exec -it redi-db psql -U redi -d redi_emails
```

Example queries:
```sql
-- Recent emails
SELECT subject, category, confidence, created_at 
FROM email_records 
ORDER BY created_at DESC 
LIMIT 10;

-- Statistics
SELECT * FROM email_statistics LIMIT 7;

-- Emails needing review
SELECT subject, human_review_reason 
FROM email_records 
WHERE human_review_required = TRUE;
```

### Option 2: pgAdmin Web Interface

Start pgAdmin:
```bash
docker-compose --profile admin up -d
```

Access at: http://localhost:5050
- Email: admin@redi.local
- Password: admin (from .env)

Add server:
- Name: REdI Database
- Host: db
- Port: 5432
- Username: redi
- Password: (from .env)

## Configuration

### Confidence Thresholds

Adjust in `.env`:

```bash
CONFIDENCE_THRESHOLD_HIGH=0.8     # Auto-respond with actions
CONFIDENCE_THRESHOLD_MODERATE=0.5 # Info only responses
CONFIDENCE_THRESHOLD_LOW=0.3      # No response
```

### GPT Settings

```bash
OPENAI_MODEL=gpt-4o              # Model to use
OPENAI_TEMPERATURE=0             # Consistency (0-1)
OPENAI_MAX_TOKENS=1000           # Response length
```

## Monitoring

### View Logs

```bash
# API logs
docker logs -f redi-api

# Database logs
docker logs -f redi-db

# Application logs (inside container)
docker exec redi-api tail -f /var/log/redi/email_processor.log
```

### Statistics

```bash
# Get 7-day statistics
curl -H "Authorization: Bearer $REDI_API_KEY" \
  "http://localhost:5000/api/statistics?days=7" | jq
```

### Metrics to Track

- Total emails processed
- Response rate
- Pre-filter effectiveness
- GPT token usage
- Average processing time
- Human review queue size

## Deployment

### Development

```bash
docker-compose up
```

Includes hot-reload for code changes.

### Production

```bash
docker-compose -f docker-compose.yml up -d
```

Recommendations:
- Use reverse proxy (nginx/Traefik)
- Enable HTTPS
- Set up backup for database
- Configure log rotation
- Monitor with Prometheus/Grafana

### Azure Deployment

See `docs/azure-deployment.md` for detailed instructions.

## Testing

### Unit Tests

```bash
# Install dev dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src --cov-report=html
```

### Integration Tests

```bash
# Start services
docker-compose up -d

# Run integration tests
python tests/test_integration.py
```

### Manual Testing

```bash
# Certificate request (high confidence)
curl -X POST http://localhost:5000/api/process-email \
  -H "Authorization: Bearer $REDI_API_KEY" \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/certificate_request.json

# Complaint (should be blocked)
curl -X POST http://localhost:5000/api/process-email \
  -H "Authorization: Bearer $REDI_API_KEY" \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/complaint.json
```

## Troubleshooting

### API returns 401

Check API key in `.env` and request header.

### Database connection fails

```bash
# Check if database is running
docker ps | grep redi-db

# View database logs
docker logs redi-db

# Test connection
docker exec redi-db pg_isready -U redi
```

### GPT API errors

- Verify OpenAI API key
- Check account has credits
- Review rate limits

### High processing times

- Enable response caching
- Reduce OPENAI_MAX_TOKENS
- Use gpt-3.5-turbo for faster responses

## Security

### API Key Management

- Generate strong keys (32+ characters)
- Rotate every 90 days
- Never commit to Git
- Use Azure Key Vault in production

### Database Security

- Change default passwords
- Restrict network access
- Enable SSL connections
- Regular backups

### Container Security

- Runs as non-root user (UID 1000)
- Read-only file systems where possible
- Minimal base images
- Regular security updates

## Cost Analysis

### Monthly Costs (Estimated)

**Current (Power Automate + GPT):**
- Power Automate: $15/month
- GPT API: $3-5/month
- Total: ~$18-20/month

**With This System:**
- Hosting (Azure Container Instances): $5-10/month
- Database (Azure PostgreSQL): $5/month
- GPT API (40% reduction): $2-3/month
- Total: ~$12-18/month

**Savings:** 10-40% reduction

**Plus benefits:**
- Better reliability
- Complete audit trail
- Easier to maintain
- Faster development

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## License

Internal use only - Royal Brisbane & Women's Hospital

## Support

**Technical Issues:**
- Sean Wing: sean.wing@health.qld.gov.au

**REdI Team:**
- Email: redi@health.qld.gov.au
- Phone: (07) 3647 0106

## Changelog

### Version 2.0 (2026-01-02)
- Initial Docker deployment
- PostgreSQL database integration
- Complete API rewrite
- Statistics endpoints
- Comprehensive logging

---

**Built with ❤️ by Sean Wing for REdI**
