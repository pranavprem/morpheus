"""Discord bot for credential approval workflow."""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any
import discord
from discord.ext import commands

from app.config import settings

logger = logging.getLogger(__name__)


class MorpheusBot(commands.Bot):
    """Discord bot for handling credential approval requests."""
    
    def __init__(self):
        # Bot intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        
        super().__init__(
            command_prefix="!morpheus",
            intents=intents,
            help_command=None
        )
        
        self.pending_requests: Dict[str, asyncio.Future] = {}
        
    async def on_ready(self):
        """Called when the bot is ready."""
        logger.info(f"Morpheus bot logged in as {self.user}")
        
        # Verify access to required channels
        try:
            approval_channel = self.get_channel(settings.discord_approval_channel_id)
            log_channel = self.get_channel(settings.discord_log_channel_id)
            
            if not approval_channel:
                logger.error(f"Cannot access approval channel {settings.discord_approval_channel_id}")
            if not log_channel:
                logger.error(f"Cannot access log channel {settings.discord_log_channel_id}")
                
            if approval_channel and log_channel:
                logger.info("Successfully verified access to Discord channels")
                
        except Exception as e:
            logger.error(f"Failed to verify Discord channel access: {e}")
    
    async def on_reaction_add(self, reaction, user):
        """Handle reaction-based approvals."""
        # Ignore bot reactions and reactions from non-approver
        if user.bot or user.id != settings.discord_approver_id:
            return
        
        # Check if this is an approval request message
        message_id = str(reaction.message.id)
        if message_id not in self.pending_requests:
            return
        
        # Process the reaction
        emoji = str(reaction.emoji)
        future = self.pending_requests[message_id]
        
        if emoji == "✅":
            logger.info(f"Request {message_id} approved by {user}")
            future.set_result(True)
        elif emoji == "❌":
            logger.info(f"Request {message_id} denied by {user}")
            future.set_result(False)
        
        # Clean up
        del self.pending_requests[message_id]
    
    async def request_approval(
        self, 
        service: str, 
        scope: str, 
        reason: str, 
        request_id: str
    ) -> bool:
        """
        Request approval for a credential access.
        
        Args:
            service: Service name being requested
            scope: Scope of access requested
            reason: Reason for the request
            request_id: Unique identifier for this request
            
        Returns:
            True if approved, False if denied or timeout
        """
        try:
            approval_channel = self.get_channel(settings.discord_approval_channel_id)
            if not approval_channel:
                logger.error("Cannot access approval channel")
                return False
            
            # Create approval request embed
            embed = discord.Embed(
                title="🔐 Credential Access Request",
                color=discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Service", value=f"`{service}`", inline=True)
            embed.add_field(name="Scope", value=f"`{scope}`", inline=True)
            embed.add_field(name="Request ID", value=f"`{request_id}`", inline=True)
            embed.add_field(name="Reason", value=reason, inline=False)
            
            embed.set_footer(text="React with ✅ to approve or ❌ to deny")
            
            # Send the message
            message = await approval_channel.send(embed=embed)
            
            # Add reaction buttons
            await message.add_reaction("✅")
            await message.add_reaction("❌")
            
            # Create future for the response
            future = asyncio.Future()
            self.pending_requests[str(message.id)] = future
            
            # Wait for approval with timeout
            try:
                approved = await asyncio.wait_for(
                    future, 
                    timeout=settings.approval_timeout_seconds
                )
                
                # Update the embed with the result
                result_color = discord.Color.green() if approved else discord.Color.red()
                result_text = "APPROVED ✅" if approved else "DENIED ❌"
                
                embed.color = result_color
                embed.title = f"🔐 Credential Access Request - {result_text}"
                
                await message.edit(embed=embed)
                
                return approved
                
            except asyncio.TimeoutError:
                # Timeout - auto-deny
                logger.warning(f"Request {request_id} timed out")
                
                embed.color = discord.Color.red()
                embed.title = "🔐 Credential Access Request - TIMEOUT ⏰"
                embed.add_field(
                    name="Result", 
                    value="Auto-denied due to timeout", 
                    inline=False
                )
                
                await message.edit(embed=embed)
                
                # Clean up
                if str(message.id) in self.pending_requests:
                    del self.pending_requests[str(message.id)]
                
                return False
                
        except Exception as e:
            logger.error(f"Failed to request approval: {e}")
            return False
    
    async def log_request(
        self, 
        service: str, 
        scope: str, 
        reason: str, 
        approved: bool, 
        request_id: str,
        duration_ms: Optional[int] = None
    ):
        """
        Log a credential request to the log channel.
        
        Args:
            service: Service name
            scope: Scope requested
            reason: Reason for request
            approved: Whether the request was approved
            request_id: Unique request identifier
            duration_ms: How long the request took to process
        """
        try:
            log_channel = self.get_channel(settings.discord_log_channel_id)
            if not log_channel:
                logger.error("Cannot access log channel")
                return
            
            # Create log embed
            status = "APPROVED" if approved else "DENIED"
            color = discord.Color.green() if approved else discord.Color.red()
            
            embed = discord.Embed(
                title=f"📊 Gatekeeper Log - {status}",
                color=color,
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Service", value=f"`{service}`", inline=True)
            embed.add_field(name="Scope", value=f"`{scope}`", inline=True)
            embed.add_field(name="Status", value=status, inline=True)
            embed.add_field(name="Request ID", value=f"`{request_id}`", inline=True)
            
            if duration_ms:
                duration_sec = duration_ms / 1000
                embed.add_field(name="Duration", value=f"{duration_sec:.1f}s", inline=True)
            
            # Add reason but truncate if too long
            reason_text = reason[:500] + "..." if len(reason) > 500 else reason
            embed.add_field(name="Reason", value=reason_text, inline=False)
            
            await log_channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Failed to log request: {e}")


# Global bot instance
bot = MorpheusBot()


async def start_bot():
    """Start the Discord bot."""
    try:
        await bot.start(settings.discord_bot_token)
    except Exception as e:
        logger.error(f"Failed to start Discord bot: {e}")
        raise


async def stop_bot():
    """Stop the Discord bot."""
    try:
        await bot.close()
    except Exception as e:
        logger.error(f"Error stopping Discord bot: {e}")