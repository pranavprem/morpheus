.PHONY: build up down logs restart clean status health

# Build the Docker image
build:
	@echo "🔨 Building Morpheus Docker image..."
	docker compose build

# Start services
up:
	@echo "🚀 Starting Morpheus..."
	docker compose up -d

# Stop services
down:
	@echo "🛑 Stopping Morpheus..."
	docker compose down

# View logs
logs:
	@echo "📋 Viewing Morpheus logs..."
	docker compose logs -f

# Restart services
restart: down up

# Clean up containers and images
clean:
	@echo "🧹 Cleaning up Docker resources..."
	docker compose down --rmi all --volumes --remove-orphans

# Show service status
status:
	@echo "📊 Morpheus service status:"
	docker compose ps

# Check health
health:
	@echo "🏥 Checking Morpheus health..."
	@curl -s http://localhost:8000/health | python -m json.tool || echo "❌ Health check failed"

# Show help
help:
	@echo "Morpheus - Credential Gatekeeper API"
	@echo ""
	@echo "Available commands:"
	@echo "  build    - Build Docker image"
	@echo "  up       - Start services"
	@echo "  down     - Stop services"
	@echo "  logs     - View logs"
	@echo "  restart  - Restart services"
	@echo "  clean    - Clean up Docker resources"
	@echo "  status   - Show service status"
	@echo "  health   - Check API health"
	@echo "  help     - Show this help message"
	@echo ""
	@echo "Quick start:"
	@echo "  1. Copy .env.example to .env and configure"
	@echo "  2. Run 'make build && make up'"
	@echo "  3. Check status with 'make health'"

# Pull latest, rebuild, and redeploy
redeploy:
	@echo "🔄 Pulling latest changes..."
	git pull
	@echo "🔨 Building fresh image..."
	docker compose build --no-cache
	@echo "♻️  Redeploying Morpheus..."
	docker compose up -d
	@echo "✅ Morpheus redeployed."

# Default target
all: help