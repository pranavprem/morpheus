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
    
    async def _run_command(self, cmd: list[str]) -> str:
        """Run a Bitwarden CLI command and return stdout."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                logger.error(f"Bitwarden CLI error: {error_msg}")
                raise RuntimeError(f"Bitwarden CLI failed: {error_msg}")
            
            return stdout.decode().strip()
        except Exception as e:
            logger.error(f"Failed to execute Bitwarden command: {e}")
            raise
    
    async def login(self) -> bool:
        """Login to Bitwarden and establish session."""
        try:
            # Configure server URL
            await self._run_command([
                "bw", "config", "server", settings.vaultwarden_url
            ])
            
            # Login and get session key
            process = await asyncio.create_subprocess_exec(
                "bw", "login", "--raw", "--nointeraction",
                settings.vaultwarden_email,
                settings.vaultwarden_master_password,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error = stderr.decode().strip()
                if "already logged in" in error.lower():
                    return await self.unlock()
                logger.error(f"Login failed: {error}")
                return False
            
            result = stdout.decode().strip()
            
            self.session_key = result
            logger.info("Successfully logged into Vaultwarden")
            return True
            
        except Exception as e:
            logger.error(f"Failed to login to Vaultwarden: {e}")
            return False
    
    async def unlock(self) -> bool:
        """Unlock the vault if needed."""
        try:
            if not self.session_key:
                await self.login()
            
            # Test if vault is already unlocked
            try:
                await self._run_command([
                    "bw", "list", "items", "--session", self.session_key
                ])
                return True
            except:
                # Need to unlock
                process = await asyncio.create_subprocess_exec(
                    "bw", "unlock", "--raw", "--nointeraction",
                    settings.vaultwarden_master_password,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    raise RuntimeError(f"Unlock failed: {stderr.decode().strip()}")
                
                result = stdout.decode().strip()
                self.session_key = result
                logger.info("Vault unlocked successfully")
                return True
                
        except Exception as e:
            logger.error(f"Failed to unlock vault: {e}")
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
        try:
            if not await self.unlock():
                return None
            
            # Search for items by name
            search_result = await self._run_command([
                "bw", "list", "items", "--search", service, 
                "--session", self.session_key
            ])
            
            items = json.loads(search_result)
            
            if not items:
                logger.warning(f"No items found for service: {service}")
                return None
            
            # Find the exact match
            matching_item = None
            for item in items:
                if item.get("name", "").lower() == service.lower():
                    matching_item = item
                    break
            
            if not matching_item:
                logger.warning(f"No exact match found for service: {service}")
                return None
            
            # Check if the requested scope exists in custom fields
            custom_fields = matching_item.get("fields", [])
            allowed_scopes = []
            
            for field in custom_fields:
                if field.get("name", "").lower() == "scopes":
                    allowed_scopes = field.get("value", "").split(",")
                    break
            
            allowed_scopes = [s.strip().lower() for s in allowed_scopes]
            
            if scope.lower() not in allowed_scopes:
                logger.warning(f"Scope '{scope}' not allowed for service '{service}'. Allowed: {allowed_scopes}")
                return None
            
            # Extract credential data based on scope
            credential_data = {
                "service": service,
                "scope": scope,
                "name": matching_item.get("name"),
                "username": matching_item.get("login", {}).get("username"),
                "password": matching_item.get("login", {}).get("password"),
                "notes": matching_item.get("notes"),
                "uris": matching_item.get("login", {}).get("uris", [])
            }
            
            # Add custom fields
            for field in custom_fields:
                field_name = field.get("name", "")
                if field_name.lower() != "scopes":  # Don't expose the scopes field
                    credential_data[field_name] = field.get("value")
            
            logger.info(f"Successfully retrieved credential for {service}:{scope}")
            return credential_data
            
        except Exception as e:
            logger.error(f"Failed to get credential for {service}:{scope}: {e}")
            return None
    
    async def list_services(self) -> list[str]:
        """List all available services (item names) in the vault."""
        try:
            if not await self.unlock():
                return []
            
            # Get all items
            result = await self._run_command([
                "bw", "list", "items", "--session", self.session_key
            ])
            
            items = json.loads(result)
            services = []
            
            for item in items:
                name = item.get("name")
                if name:
                    # Check if item has scopes defined
                    custom_fields = item.get("fields", [])
                    has_scopes = any(
                        field.get("name", "").lower() == "scopes" 
                        for field in custom_fields
                    )
                    
                    if has_scopes:
                        services.append(name)
            
            logger.info(f"Found {len(services)} services with scopes")
            return sorted(services)
            
        except Exception as e:
            logger.error(f"Failed to list services: {e}")
            return []
    
    async def logout(self):
        """Logout from Bitwarden."""
        try:
            await self._run_command(["bw", "logout"])
            self.session_key = None
            logger.info("Logged out from Vaultwarden")
        except Exception as e:
            logger.error(f"Failed to logout: {e}")


# Global vault manager instance
vault_manager = VaultManager()