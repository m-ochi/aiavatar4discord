# pip install discord.py
import os, asyncio
import discord
import yaml
import os
from yaml.loader import SafeLoader
from google.adk.agents import Agent, SequentialAgent, LlmAgent
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types


# configの読み込み
with open('./config.yml') as file:
        config = yaml.load(file, Loader=SafeLoader)

TOKEN = config["discord_bot_token"]
BOT_NAME = config["discord_bot_name"]
TARGET_USER_ID = int(config["target_user_id"])
TARGET_CHANNEL_ID = int(config["target_channel_id"])

os.environ["GOOGLE_API_KEY"] = config["gemini_api_key"]
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"


intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

async def channelPost(text: str) -> str:
    '''
    指定されたチャンネルへポストを行う。公式な意見と見做される。
    '''
    # CHANNELにメッセージを投稿
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    await channel.send(text)

    return

async def privateMessage(text: str) -> str:
    '''
    ユーザへ伝える。意見を個人へ伝達する役割。
    '''
    # USERにDMを送信
    user = await bot.fetch_user(TARGET_USER_ID)
    print(user)
    await user.send(text)

    return

# 会話Agent
SECRETARY_U2C_INSTRUCTION = """
あなたはチャットユーザのための有能な秘書です。
ユーザが発言する場合に発言内容を見て、投稿に適切な内容に加筆修正を行なった上で、必ずchannelPostを使って投稿します。
また、チャンネルに投稿すべき内容でないと判断される場合、privateMessageを使って、ユーザに警告します。
聞き返すのは絶対禁止です。channelPostを使わない判断をしたらかならずprivateMessageを使ってください。
投稿は１回だけにしてください。
"""

SECRETARY_C2U_INSTRUCTION = """
あなたはチャットユーザのための有能な秘書です。
チャンネル上での議論においてユーザに取って有益な情報や、ユーザが返信が必要な内容を取捨選択し、privateMessageを使ってユーザに取り次ぎます。
何かを聞いたり、許可を求めるのは禁止です。連絡は必ずprivateMessageを使ってください。
また、自分で返信できる内容についてはchannelPostを使って返信してください。
返事を自分でする場合はchannelPostを必ず使ってください。
投稿は１回だけにしてください。
"""

u2c_agent = LlmAgent(
    name="chat_secretary_v1",
    model=config["model_gemini"],
    description="chatでの会話内容について、ユーザの発言を、内容の公正さや丁重さを高めた上で指定のchannelへ投稿を行います。",
    instruction=SECRETARY_U2C_INSTRUCTION,
    tools=[channelPost, privateMessage],
)

c2u_agent = LlmAgent(
    name="chat_secretary_v1",
    model=config["model_gemini"],
    description="chatでの会話内容について、channel上の議論のうち、取り次ぐべき内容を判断し、ユーザへ要約して伝えます。",
    instruction=SECRETARY_C2U_INSTRUCTION,
    tools=[channelPost, privateMessage],
)

def event_text(ev) -> str:
   if getattr(ev, "content", None) and getattr(ev.content, "parts", None):
       # partsの中に text があるものだけ連結
       return "".join(getattr(p, "text", "") or "" for p in ev.content.parts if hasattr(p, "text"))

   return ""

def is_final(ev) -> bool:
     attr = getattr(ev, "is_final_response", None)
     return attr() if callable(attr) else bool(attr)  # メソッド/プロパティどちらにも対応

@bot.event
async def on_ready():
    print(f"Connected to Discord!")
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    print(channel)
    await channel.send('テスト！')

@bot.event
async def on_message(message):

    # 自分からBOTへのDMの処理
    if isinstance(message.channel, discord.DMChannel):
        if message.author.id == TARGET_USER_ID:
            print(f"[DM1] from {message.author.name} -> {message.content}")

            # CHANNELにメッセージを投稿
            session_service = InMemorySessionService()
            app, user, sid = "SynologyChatAgentApp", "user_1", "sess_001"
            session = await session_service.create_session(app_name=app, user_id=user, session_id=sid)
  
            runner = Runner(agent=u2c_agent, app_name=app, session_service=session_service)
  
            # 最初のユーザ入力（必要なら）
            user_msg = types.Content(
                role="user",
                parts=[types.Part(text=message.content)]
            )
  
            full_text = []
            async for event in runner.run_async(user_id=user, session_id=session.id, new_message=user_msg):
### af af after
                calls = event.get_function_calls()
                if calls:
                    for i, c in enumerate(calls, 1):
                        fname = getattr(c, "name", None) or getattr(c, "function", None)
                        fargs = getattr(c, "arguments", None) or getattr(c, "args", None)
                        print(f"CALL[{i}]: {fname}({fargs})")
  
                        rets = event.get_function_responses()
                        if rets:
                            for i, r in enumerate(rets, 1):
                                fname = getattr(r, "name", None) or getattr(r, "function", None)
                                out   = (getattr(r, "response", None) or getattr(r, "output", None) or getattr(r, "result", None))
                                print(f"RET [{i}]: {fname} -> {out}")
  
                t = event_text(event)
                if not t:
                    continue
  
                # ストリーミング途中か最終かで蓄積
                if getattr(event, "partial", False):
                    full_text.append(t)
                elif is_final(event):
                    full_text.append(t)
  
            print("--- FINAL ---")
            print("".join(full_text))

#            channel = bot.get_channel(TARGET_CHANNEL_ID)
#            await channel.send(f"[DM1] from {message.author.name} -> {message.content}")

    # channelからの投稿の処理
    else:
        if message.channel.id == TARGET_CHANNEL_ID:
            # 送信者がbotである場合は弾く
            if message.author.name == BOT_NAME:
                print("Messageは自分が投稿したやつでした")
                return 
            else:
                print(f"[CHANNEL] from {message.author.name} -> {message.content}")
                # USERにDMを送信
                session_service = InMemorySessionService()
                app, user, sid = "SynologyChatAgentApp", "user_1", "sess_001"
                session = await session_service.create_session(app_name=app, user_id=user, session_id=sid)
   
                runner = Runner(agent=c2u_agent, app_name=app, session_service=session_service)
   
                # 最初のユーザ入力（必要なら）
                user_msg = types.Content(
                    role="user",
                    parts=[types.Part(text=message.content)]
                )
   
                full_text = []
                async for event in runner.run_async(user_id=user, session_id=session.id, new_message=user_msg):
#### af af af after
                    calls = event.get_function_calls()
                    if calls:
                        for i, c in enumerate(calls, 1):
                            fname = getattr(c, "name", None) or getattr(c, "function", None)
                            fargs = getattr(c, "arguments", None) or getattr(c, "args", None)
                            print(f"CALL[{i}]: {fname}({fargs})")
   
                            rets = event.get_function_responses()
                            if rets:
                                for i, r in enumerate(rets, 1):
                                    fname = getattr(r, "name", None) or getattr(r, "function", None)
                                    out   = (getattr(r, "response", None) or getattr(r, "output", None) or getattr(r, "result", None))
                                    print(f"RET [{i}]: {fname} -> {out}")
   
                    t = event_text(event)
                    if not t:
                        continue
   
                    # ストリーミング途中か最終かで蓄積
                    if getattr(event, "partial", False):
                        full_text.append(t)
                    elif is_final(event):
                        full_text.append(t)
   
                print("--- FINAL ---")
                print("".join(full_text))


#                user = await bot.fetch_user(TARGET_USER_ID)
#                print(user)
#                await user.send(f"[CHANNEL] from {message.author.name} -> {message.content}")

    return

bot.run(TOKEN)
