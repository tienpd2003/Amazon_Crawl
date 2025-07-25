#!/usr/bin/env python3
"""
Script để chuyển cấu hình từ database sang .env
"""
import os
from dotenv import load_dotenv
import json
from database.connection import get_db_session
from database.models import NotificationSettings, UserSettings

def migrate_settings_to_env():
    """Di chuyển cấu hình từ database sang .env"""
    print("🔄 MIGRATING SETTINGS TO .ENV...")
    
    # Load current .env
    load_dotenv()
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    
    # Get settings from database
    session = get_db_session()
    try:
        # Get notification settings
        notification_settings = session.query(NotificationSettings).all()
        user_settings = session.query(UserSettings).all()
        
        # Build new env content
        env_lines = []
        
        # Read existing .env content
        if os.path.exists(env_file):
            with open(env_file, 'r', encoding='utf-8') as f:
                env_lines = f.read().splitlines()
        
        # Update notification settings
        for setting in notification_settings:
            if setting.notification_type == 'telegram':
                config = json.loads(setting.config)
                env_lines.extend([
                    f"TELEGRAM_BOT_TOKEN={config.get('bot_token', '')}",
                    f"TELEGRAM_CHAT_ID={config.get('chat_id', '')}",
                    f"TELEGRAM_ENABLED={str(setting.enabled).lower()}"
                ])
            elif setting.notification_type == 'discord':
                config = json.loads(setting.config)
                env_lines.extend([
                    f"DISCORD_WEBHOOK_URL={config.get('webhook_url', '')}",
                    f"DISCORD_ENABLED={str(setting.enabled).lower()}"
                ])
            elif setting.notification_type == 'email':
                config = json.loads(setting.config)
                env_lines.extend([
                    f"EMAIL_SMTP_SERVER={config.get('smtp_server', 'smtp.gmail.com')}",
                    f"EMAIL_SMTP_PORT={config.get('smtp_port', '587')}",
                    f"EMAIL_USERNAME={config.get('username', '')}",
                    f"EMAIL_PASSWORD={config.get('password', '')}",
                    f"EMAIL_RECIPIENTS={','.join(config.get('recipients', []))}",
                    f"EMAIL_ENABLED={str(setting.enabled).lower()}"
                ])
            
            # Add notification triggers
            env_lines.extend([
                f"NOTIFY_ON_PRICE_CHANGE={str(setting.price_change).lower()}",
                f"NOTIFY_ON_AVAILABILITY_CHANGE={str(setting.availability_change).lower()}",
                f"NOTIFY_ON_RATING_CHANGE={str(setting.rating_change).lower()}",
                f"NOTIFY_ON_NEW_COUPON={str(setting.new_coupon).lower()}",
                f"NOTIFY_ON_NEW_DEAL={str(setting.new_deal).lower()}"
            ])
        
        # Update user settings
        for setting in user_settings:
            env_lines.append(f"{setting.setting_key.upper()}={setting.setting_value}")
        
        # Write back to .env
        with open(env_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(env_lines))
        
        print("✅ Settings migrated successfully!")
        print(f"   Settings written to: {env_file}")
        
    except Exception as e:
        print(f"❌ Error migrating settings: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    print("🚀 Starting Settings Migration...")
    migrate_settings_to_env() 