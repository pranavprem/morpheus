"""Vaultwarden/Bitwarden CLI wrapper for credential access."""

import asyncio
import json
import logging
from typing import Optional, Dict, Any
from app.config import settings

logger = logging.getLogger(__name__)


class VaultManager:
    """Manages Bitwarden CLI interactions for credential access."""
    
    def __init__(self):
        self.session_key: Optional[str] = None
        self._logged_in: bool = False
    
    async def _run_command(self, cmd: list[str], timeout: int = 30) -> str:
        """Run a Bitwarden CLI command and return stdout."""
        cmd_str = " ".join(cmd[:3]) + ("..." if len(cmd) > 3 else "")
        logger.debug(f"Running command: {cmd_str}")
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                logger.error(f"Command timed out after {timeout}s: {cmd_str}")
                raise RuntimeError(f"Command timed out: {cmd_str}")
            
            stdout_text = stdout.decode().strip()
            stderr_text = stderr.decode().strip()
            
            if process.returncode != 0:
                logger.error(f"Command failed (rc={process.returncode}): {cmd_str}")
                logger.error(f"  stderr: {stderr_text}")
                if stdout_text:
                    logger.error(f"  stdout: {stdout_text}")
                raise RuntimeError(f"Bitwarden CLI failed: {stderr_text}")
            
            logger.debug(f"Command succeeded: {cmd_str}")
            return stdout_text
            
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Failed to execute command {cmd_str}: {type(e).__name__}: {e}")
            raise
    
    async def login(self) -> bool:
        """Login to Bitwarden and establish session."""
        try:
            # Configure server URL
            logger.info(f"Configuring Vaultwarden server: {settings.vaultwarden_url}")
            await self._run_command([
                "bw", "config", "server", settings.vaultwarden_url
            ])
            
            # Check current login status first
            try:
                status_output = await self._run_command(["bw", "status"])
                status_data = json.loads(status_output)
                current_status = status_data.get("status", "unknown")
                logger.info(f"Current vault status: {current_status}")
                
                if current_status == "unauthenticated":
                    # Need to login
                    logger.info("Vault is unauthenticated, logging in...")
                    process = await asyncio.create_subprocess_exec(
                        "bw", "login", "--raw", "--nointeraction",
                        settings.vaultwarden_email,
                        settings.vaultwarden_master_password,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=30
                    )
                    
                    if process.returncode != 0:
                        error = stderr.decode().strip()
                        logger.error(f"Login failed (rc={process.returncode}): {error}")
                        return False
                    
                    self.session_key = stdout.decode().strip()
                    self._logged_in = True
                    logger.info("Successfully logged into Vaultwarden")
                    return True
                    
                elif current_status == "locked":
                    # Already logged in, just need to unlock
                    logger.info("Vault is locked, skipping login — will unlock")
                    self._logged_in = True
                    return True
                    
                elif current_status == "unlocked":
                    # Already good to go
                    logger.info("Vault is already unlocked")
                    self._logged_in = True
                    # Get session key if we don't have one
                    if not self.session_key:
                        return await self._do_unlock()
                    return True
                    
                else:
                    logger.warning(f"Unknown vault status: {current_status}")
                    return False
                    
            except Exception as e:
                logger.error(f"Failed to check vault status: {type(e).__name__}: {e}")
                return False
            
        except Exception as e:
            logger.error(f"Login process failed: {type(e).__name__}: {e}")
            return False
    
    async def _do_unlock(self) -> bool:
        """Perform the actual unlock operation."""
        logger.info("Unlocking vault...")
        try:
            process = await asyncio.create_subprocess_exec(
                "bw", "unlock", "--raw", "--nointeraction",
                settings.vaultwarden_master_password,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=30
            )
            
            if process.returncode != 0:
                error = stderr.decode().strip()
                logger.error(f"Unlock failed (rc={process.returncode}): {error}")
                return False
            
            self.session_key = stdout.decode().strip()
            logger.info(f"Vault unlocked successfully (session key length: {len(self.session_key)})")
            return True
            
        except asyncio.TimeoutError:
            logger.error("Unlock command timed out after 30s")
            return False
        except Exception as e:
            logger.error(f"Unlock failed: {type(e).__name__}: {e}")
            return False
    
    async def unlock(self) -> bool:
        """Unlock the vault, logging in first if needed."""
        try:
            if not self._logged_in:
                logger.info("Not logged in yet, calling login first...")
                if not await self.login():
                    logger.error("Login failed, cannot unlock")
                    return False
            
            # If login already gave us a session key, verify it works
            if self.session_key:
                try:
                    logger.debug("Testing existing session key...")
                    await self._run_command([
                        "bw", "sync", "--session", self.session_key
                    ])
                    logger.info("Existing session key is valid")
                    return True
                except Exception as e:
                    logger.warning(f"Existing session key invalid: {e}, re-unlocking...")
                    self.session_key = None
            
            # Unlock to get a fresh session key
            return await self._do_unlock()
                
        except Exception as e:
            logger.error(f"Unlock process failed: {type(e).__name__}: {e}")
            return False
    
    async def get_credential(self, service: str, scope: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a credential from the vault.
        
        Args:
            service: The service name to search for
            scope: The specific scope/field to retrieve
            
        Returns:
            Dictionary containing credential data, or None if not found
        """
        logger.info(f"Getting credential for {service}:{scope}")
        
        try:
            if not await self.unlock():
                logger.error(f"Cannot get credential — vault unlock failed")
                return None
            
            # Search for items by name
            logger.debug(f"Searching vault for service: {service}")
            search_result = await self._run_command([
                "bw", "list", "items", "--search", service, 
                "--session", self.session_key
            ])
            
            items = json.loads(search_result)
            logger.debug(f"Found {len(items)} items matching '{service}'")
            
            if not items:
                logger.warning(f"No items found for service: {service}")
                return None
            
            # Find the exact match
            matching_item = None
            for item in items:
                item_name = item.get("name", "")
                if item_name.lower() == service.lower():
                    matching_item = item
                    logger.debug(f"Exact match found: {item_name}")
                    break
            
            if not matching_item:
                logger.warning(f"No exact match found for service: {service}")
                logger.debug(f"Available items: {[i.get('name') for i in items]}")
                return None
            
            # Check if the requested scope exists in custom fields
            custom_fields = matching_item.get("fields", [])
            allowed_scopes = []
            
            for field in custom_fields:
                field_name = field.get("name", "").lower()
                # Accept both "scope" and "scopes" field names
                if field_name in ("scopes", "scope"):
                    allowed_scopes = field.get("value", "").split(",")
                    logger.debug(f"Found scopes field '{field.get('name')}': {field.get('value')}")
                    break
            
            allowed_scopes = [s.strip().lower() for s in allowed_scopes if s.strip()]
            logger.debug(f"Allowed scopes: {allowed_scopes}")
            
            if scope.lower() not in allowed_scopes:
                logger.warning(f"Scope '{scope}' not allowed for service '{service}'. Allowed: {allowed_scopes}")
                return None
            
            logger.info(f"Scope '{scope}' verified for service '{service}'")
            
            # Extract credential data based on item type
            item_type = matching_item.get("type", 1)
            logger.debug(f"Item type: {item_type}")
            
            credential_data = {
                "service": service,
                "scope": scope,
                "name": matching_item.get("name"),
                "notes": matching_item.get("notes"),
            }
            
            if item_type == 3:  # Card
                card = matching_item.get("card", {})
                credential_data.update({
                    "cardholderName": card.get("cardholderName"),
                    "number": card.get("number"),
                    "expMonth": card.get("expMonth"),
                    "expYear": card.get("expYear"),
                    "code": card.get("code"),
                    "brand": card.get("brand"),
                })
            else:  # Login or other
                login_data = matching_item.get("login", {})
                credential_data.update({
                    "username": login_data.get("username"),
                    "password": login_data.get("password"),
                    "uris": login_data.get("uris", []),
                })
                has_password = bool(login_data.get("password"))
                logger.debug(f"Login data — username: {login_data.get('username')}, has_password: {has_password}")
            
            # Check for auto_approve flag in custom fields
            for field in custom_fields:
                if field.get("name", "").lower() == "auto_approve":
                    credential_data["auto_approve"] = field.get("value", "")
                    break
            
            # Add custom fields (exclude internal control fields)
            internal_fields = {"scopes", "scope", "auto_approve"}
            for field in custom_fields:
                field_name = field.get("name", "")
                if field_name.lower() not in internal_fields:
                    credential_data[field_name] = field.get("value")
            
            logger.info(f"Successfully retrieved credential for {service}:{scope}")
            return credential_data
            
        except Exception as e:
            logger.error(f"Failed to get credential for {service}:{scope}: {type(e).__name__}: {e}")
            return None
    
    async def list_services(self) -> list[str]:
        """List all available services (item names) in the vault."""
        logger.info("Listing available services...")
        
        try:
            if not await self.unlock():
                logger.error("Cannot list services — vault unlock failed")
                return []
            
            result = await self._run_command([
                "bw", "list", "items", "--session", self.session_key
            ])
            
            items = json.loads(result)
            services = []
            
            for item in items:
                name = item.get("name")
                if name:
                    custom_fields = item.get("fields", [])
                    has_scopes = any(
                        field.get("name", "").lower() in ("scopes", "scope")
                        for field in custom_fields
                    )
                    
                    if has_scopes:
                        services.append(name)
            
            logger.info(f"Found {len(services)} services with scopes: {services}")
            return sorted(services)
            
        except Exception as e:
            logger.error(f"Failed to list services: {type(e).__name__}: {e}")
            return []
    
    async def logout(self):
        """Logout from Bitwarden."""
        try:
            await self._run_command(["bw", "logout"])
            self.session_key = None
            self._logged_in = False
            logger.info("Logged out from Vaultwarden")
        except Exception as e:
            logger.error(f"Failed to logout: {e}")


# Global vault manager instance
vault_manager = VaultManager()
