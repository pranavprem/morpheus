# Morpheus - Credential Gatekeeper API

> *"This is your last chance. After this, there is no going back."*

Morpheus is a **intentionally dumb** credential gatekeeper that guards Vaultwarden credentials through Discord-based human approvals. No AI, no LLM, no prompt processing—just API key validation, Discord notifications, and human oversight.

## 🏗️ Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│             │    │             │    │             │    │             │
│     Neo     │───▶│  Morpheus   │───▶│   Discord   │───▶│   Pranav    │
│ (AI Agent)  │    │ Gatekeeper  │    │   Bot       │    │  (Human)    │
│             │    │             │    │             │    │             │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                           │                                       │
                           ▼                                       ▼
                   ┌─────────────┐                        ✅ Approve
                   │             │                        ❌ Deny
                   │ Vaultwarden │                        ⏰ Timeout
                   │    Vault    │
                   │             │
                   └─────────────┘
```

## 🔄 Request Flow

1. **Neo** sends `POST /request` with `{service, scope, reason}` + API key
2. **Morpheus** validates API key and checks if service/scope exists in vault
3. Posts approval request to Discord channel `#morpheus-approvals`
4. Returns a `request_id` immediately (non-blocking)
5. **Pranav** reacts with ✅ (approve) or ❌ (deny) on Discord
6. **Neo** polls `POST /pickup` with the `request_id`
7. **If approved**: Morpheus fetches credential from Vaultwarden, returns it
8. **If denied**: returns denial
9. **Timeout**: 10 minutes → auto-deny (fail-safe)
10. All actions logged to Discord channel `#gatekeeper-logs`

## 🛡️ Security Features

- **API key validation** on every request
- **Human approval required** for all credential access
- **Rate limiting**: 10 requests/minute per IP
- **Scope-based access control** via Vaultwarden custom fields
- **Request timeout**: auto-deny after 10 minutes
- **Audit logging** to Discord
- **No credential storage** - fetched on-demand from vault
- **LAN-only deployment** - never publicly exposed

## 🚀 Quick Start

### 1. Set up Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create new application: **"Morpheus"**
3. Create a bot, copy the token
4. Enable **MESSAGE CONTENT** intent
5. Generate invite link with permissions:
   - Send Messages
   - Read Messages  
   - Add Reactions
   - Read Message History
6. Invite bot to your Discord guild

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your values
nano .env
```

Required configuration:
- `DISCORD_BOT_TOKEN` - Bot token from Discord Developer Portal
- `MORPHEUS_API_KEY` - Secure API key for Neo to use
- `VAULTWARDEN_MASTER_PASSWORD` - Master password for your Vaultwarden account
- `VAULTWARDEN_URL` - Your Vaultwarden instance URL

### 3. Deploy

```bash
# Build and start
make build
make up

# Check status
make health
make logs
```

That's it! Morpheus is now running on `http://localhost:8000`

## 📋 API Endpoints

### `POST /request`

Submit a credential request for Discord approval. This does **not** return credentials — it starts the approval flow.

**Headers:**
- `X-API-Key: your_api_key`
- `Content-Type: application/json`

**Body:**
```json
{
  "service": "aws-prod",
  "scope": "read-only", 
  "reason": "Need to check S3 bucket permissions for debugging"
}
```

**Response:**
```json
{
  "request_id": "a1b2c3d4",
  "status": "pending",
  "message": "Request submitted, waiting for approval"
}
```

### `POST /pickup`

Fetch credentials for an approved request. Poll this endpoint after submitting a request.

**Headers:**
- `X-API-Key: your_api_key`
- `Content-Type: application/json`

**Body:**
```json
{
  "request_id": "a1b2c3d4"
}
```

**Response (approved):**
```json
{
  "request_id": "a1b2c3d4",
  "approved": true,
  "credential": {
    "service": "aws-prod",
    "scope": "read-only", 
    "username": "AKIA...",
    "password": "secret...",
    "notes": "Production AWS account",
    "custom_field": "value"
  },
  "message": "Access approved"
}
```

**Response (pending):**
```json
{
  "request_id": "a1b2c3d4",
  "approved": false,
  "message": "Request still pending approval"
}
```

**Response (denied/timeout):**
```json
{
  "request_id": "a1b2c3d4",
  "approved": false,
  "message": "Request denied"
}
```

### `GET /status`

List available services and system status.

**Headers:**
- `X-API-Key: your_api_key`

**Response:**
```json
{
  "status": "online",
  "services": ["aws-prod", "github-api", "openai-api"],
  "vault_connected": true,
  "discord_connected": true
}
```

### `GET /health`

Health check endpoint (no authentication required).

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-02-15 20:30:00 UTC",
  "vault_status": "connected",
  "discord_status": "connected"
}
```

## 🔧 Vaultwarden Setup

For each service in your Vaultwarden vault:

1. **Item Name**: Use as the `service` parameter (e.g., "aws-prod")
2. **Custom Field**: Add `scopes` field with comma-separated allowed scopes:
   ```
   Field Name: scopes
   Field Value: read-only,admin,billing
   ```
3. **Credentials**: Store in username/password fields as usual
4. **Additional Fields**: Any custom fields will be included in the response

### Example Vault Item

```
Name: github-api
Username: pranavprem
Password: ghp_xxxxxxxxxxxx
Custom Fields:
  scopes: repo,admin,webhook
  api_url: https://api.github.com
Notes: GitHub API token for automation
```

## 🐳 Docker Commands

```bash
# Management
make build    # Build Docker image
make up       # Start services  
make down     # Stop services
make restart  # Restart services
make logs     # View logs
make status   # Show container status
make health   # Check API health
make clean    # Clean up everything

# Manual Docker commands
docker-compose up -d                    # Start detached
docker-compose logs -f morpheus         # Follow logs
docker-compose exec morpheus /bin/bash  # Shell access
```

## 📊 Monitoring

### Health Checks

- **HTTP**: `GET /health` - API health status
- **Docker**: Built-in health check every 30s
- **Discord**: Bot status visible in health response

### Logging

- **Application logs**: `make logs`
- **Discord audit trail**: `#gatekeeper-logs` channel
- **Request/response logs**: Include request ID for tracking

### Metrics

Monitor these key metrics:
- Request success/failure rates
- Average approval times  
- Timeout frequency
- Vault connection health
- Discord bot connectivity

## 🛠️ Development

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DISCORD_BOT_TOKEN="your_token"
export MORPHEUS_API_KEY="your_key"
# ... other vars

# Run locally
cd app
python -m uvicorn main:app --reload --port 8000
```

### Project Structure

```
morpheus/
├── app/
│   ├── main.py          # FastAPI application
│   ├── discord_bot.py   # Discord bot for approvals
│   ├── vault.py         # Vaultwarden/bw CLI wrapper
│   └── config.py        # Configuration management
├── docker-compose.yml   # Docker services
├── Dockerfile          # Container image
├── Makefile            # Build automation
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
├── .gitignore         # Git ignore rules
└── README.md          # This file
```

## 🔒 Security Considerations

- **Never commit `.env`** - credentials should never be in git
- **Rotate API keys** regularly
- **Monitor Discord channels** for unusual activity
- **Use least-privilege scopes** in Vaultwarden items
- **Deploy LAN-only** - never expose publicly
- **Regular backups** of Vaultwarden vault
- **Bot token security** - treat like a password

## 🚨 Troubleshooting

### Common Issues

**Bot not responding to reactions:**
- Check MESSAGE CONTENT intent is enabled
- Verify bot has permissions in channels
- Check bot is in the correct guild

**Vault connection failed:**
- Verify Vaultwarden URL is accessible from container
- Check master password is correct
- Ensure Bitwarden CLI is properly installed

**API key rejected:**
- Verify `X-API-Key` header is included
- Check API key matches `.env` configuration
- Ensure no extra whitespace in key

**Timeouts:**
- Default timeout is 10 minutes
- Check Discord notifications are working
- Verify approver user ID is correct

### Debug Commands

```bash
# Check container logs
make logs

# Test health endpoint
curl http://localhost:8000/health

# Test API key validation
curl -H "X-API-Key: your_key" http://localhost:8000/status

# Check Discord bot status
docker-compose exec morpheus python -c "from app.discord_bot import bot; print(bot.is_ready())"
```

## 📝 License

MIT License - See LICENSE file for details.

## 🤝 Contributing

This is a personal project, but improvements are welcome:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

---

*"Welcome to the real world."* - Morpheus