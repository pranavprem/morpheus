"""
Morpheus - Credential Gatekeeper API

A simple HTTP API that guards Vaultwarden credentials through Discord-based approvals.
"""

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.discord_bot import bot
from app.vault import vault_manager

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# One-time credential pickup store (token -> credential data)
_credential_store: Dict[str, Dict[str, Any]] = {}

# Pydantic models
class CredentialRequest(BaseModel):
    """Model for credential requests."""
    service: str = Field(..., min_length=1, max_length=100, description="Service name")
    scope: str = Field(..., min_length=1, max_length=100, description="Access scope")
    reason: str = Field(..., min_length=10, max_length=500, description="Reason for access")


class CredentialResponse(BaseModel):
    """Model for credential responses."""
    service: str
    scope: str
    request_id: str
    approved: bool
    credential: Optional[Dict[str, Any]] = None
    message: str


class StatusResponse(BaseModel):
    """Model for status responses."""
    status: str
    services: list[str]
    vault_connected: bool
    discord_connected: bool


class HealthResponse(BaseModel):
    """Model for health check responses."""
    status: str
    timestamp: str
    vault_status: str
    discord_status: str


# FastAPI app lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    # Startup
    logger.info("Starting Morpheus...")
    
    # Start Discord bot in background
    bot_task = asyncio.create_task(bot.start(settings.discord_bot_token))
    
    # Wait a bit for bot to initialize
    await asyncio.sleep(2)
    
    # Test vault connection
    try:
        await vault_manager.unlock()
        logger.info("Vault connection successful")
    except Exception as e:
        logger.error(f"Vault connection failed: {e}")
    
    logger.info("Morpheus started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Morpheus...")
    
    # Close Discord bot
    if not bot.is_closed():
        await bot.close()
    
    # Cancel bot task
    if not bot_task.done():
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
    
    # Logout from vault
    await vault_manager.logout()
    
    logger.info("Morpheus shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Morpheus",
    description="Credential Gatekeeper API - Guards Vaultwarden credentials through Discord approvals",
    version="1.0.0",
    lifespan=lifespan
)

# Add rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def verify_api_key(request: Request) -> str:
    """Verify API key from request header."""
    api_key = request.headers.get("X-API-Key")
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header"
        )
    
    if api_key != settings.morpheus_api_key:
        logger.warning(f"Invalid API key attempt from {get_remote_address(request)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    return api_key


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    # Check Discord bot status
    discord_status = "connected" if bot.is_ready() else "disconnected"
    
    # Check vault status
    vault_status = "unknown"
    try:
        services = await vault_manager.list_services()
        vault_status = "connected" if services is not None else "disconnected"
    except Exception:
        vault_status = "disconnected"
    
    overall_status = "healthy" if (
        discord_status == "connected" and vault_status == "connected"
    ) else "degraded"
    
    return HealthResponse(
        status=overall_status,
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        vault_status=vault_status,
        discord_status=discord_status
    )


@app.get("/status", response_model=StatusResponse)
@limiter.limit("5/minute")
async def get_status(request: Request, api_key: str = Depends(verify_api_key)):
    """Get available services and system status."""
    # Get vault connection status
    vault_connected = True
    services = []
    
    try:
        services = await vault_manager.list_services()
        vault_connected = services is not None
    except Exception as e:
        logger.error(f"Failed to get vault services: {e}")
        vault_connected = False
    
    return StatusResponse(
        status="online",
        services=services,
        vault_connected=vault_connected,
        discord_connected=bot.is_ready()
    )


@app.post("/request", response_model=CredentialResponse)
@limiter.limit("10/minute")
async def request_credential(
    request_data: CredentialRequest,
    request: Request,
    api_key: str = Depends(verify_api_key)
):
    """Request a credential with Discord approval workflow."""
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]
    
    logger.info(
        f"Credential request {request_id}: {request_data.service}:{request_data.scope} "
        f"from {get_remote_address(request)}"
    )
    
    try:
        # Validate that the service exists and has the requested scope
        credential = await vault_manager.get_credential(
            request_data.service, 
            request_data.scope
        )
        
        if credential is None:
            logger.warning(f"Request {request_id}: Invalid service/scope combination")
            return CredentialResponse(
                service=request_data.service,
                scope=request_data.scope,
                request_id=request_id,
                approved=False,
                message="Service or scope not found, or scope not allowed"
            )
        
        # Check if this credential has auto_approve enabled
        logger.info(f"Request {request_id}: credential keys={list(credential.keys())}, auto_approve_value={credential.get('auto_approve')!r}")
        auto_approve = str(credential.get("auto_approve", "")).lower() == "true"
        
        if auto_approve:
            logger.info(f"Request {request_id}: Auto-approved (auto_approve=true on vault item)")
            approved = True
        else:
            # Request Discord approval
            logger.info(f"Request {request_id}: Requesting Discord approval...")
            
            approved = await bot.request_approval(
                service=request_data.service,
                scope=request_data.scope,
                reason=request_data.reason,
                request_id=request_id
            )
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Log the request
        await bot.log_request(
            service=request_data.service,
            scope=request_data.scope,
            reason=request_data.reason,
            approved=approved,
            request_id=request_id,
            duration_ms=duration_ms,
            auto_approved=auto_approve
        )
        
        if approved:
            logger.info(f"Request {request_id}: APPROVED")
            # Store credential for one-time pickup (strip internal fields)
            pickup_token = str(uuid.uuid4())
            clean_credential = {k: v for k, v in credential.items() if k != "auto_approve"}
            _credential_store[pickup_token] = {
                "credential": clean_credential,
                "created": time.time(),
                "service": request_data.service,
                "scope": request_data.scope,
            }
            return CredentialResponse(
                service=request_data.service,
                scope=request_data.scope,
                request_id=request_id,
                approved=True,
                credential=None,
                message=f"Access approved. Pickup token: {pickup_token}"
            )
        else:
            logger.info(f"Request {request_id}: DENIED")
            return CredentialResponse(
                service=request_data.service,
                scope=request_data.scope,
                request_id=request_id,
                approved=False,
                message="Access denied"
            )
    
    except Exception as e:
        logger.error(f"Request {request_id}: Error processing request: {e}")
        
        # Log the error
        await bot.log_request(
            service=request_data.service,
            scope=request_data.scope,
            reason=request_data.reason,
            approved=False,
            request_id=request_id,
            duration_ms=int((time.time() - start_time) * 1000)
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@app.post("/pickup")
@limiter.limit("10/minute")
async def pickup_credential(
    request: Request,
    api_key: str = Depends(verify_api_key)
):
    """One-time credential pickup. Token is destroyed after use."""
    body = await request.json()
    token = body.get("token", "")
    
    if token not in _credential_store:
        raise HTTPException(status_code=404, detail="Invalid or expired pickup token")
    
    data = _credential_store.pop(token)  # One-time use — delete immediately
    
    # Expire stale tokens (>5 min old)
    now = time.time()
    expired = [k for k, v in _credential_store.items() if now - v["created"] > 300]
    for k in expired:
        del _credential_store[k]
    
    logger.info(f"Credential picked up for {data['service']}:{data['scope']}")
    return {"credential": data["credential"]}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom HTTP exception handler."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        }
    )


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False
    )