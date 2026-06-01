import asyncio
from telegram import Bot

async def testar_conexao():
    bot = Bot(token="7292574457:AAGcBrQ6v-VWr8eOq0nS0VjzVF2U4-NKXUU")
    await bot.send_message(
        chat_id="5067376115", 
        text="🛡️ **Frank Investigator Conectado!**\n\nMonitorando B3 e eventos globais para sua meta de R$ 5.000,00.",
        parse_mode='Markdown'
    )

if __name__ == "__main__":
    asyncio.run(testar_conexao())