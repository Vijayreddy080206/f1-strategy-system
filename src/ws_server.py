import asyncio
import websockets
import redis.asyncio as redis
import json

async def broadcast_telemetry(websocket):
    print("🟢 Dashboard UI Connected to F1 Stream!")
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    pubsub = r.pubsub()
    
    await pubsub.subscribe('f1_strategy_stream')
    
    try:
        async for message in pubsub.listen():
            if message['type'] == 'message':
                await websocket.send(message['data'])
                
    # 🔥 THE FIX: Silently catch browser refreshes so the terminal doesn't crash
    except (websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedError):
        print("🔴 Dashboard UI Disconnected (Browser Refreshed).")
    finally:
        await pubsub.aclose()
        await r.aclose()

async def main():
    print("🚀 F1 WebSocket API Gateway running on ws://localhost:8000")
    async with websockets.serve(broadcast_telemetry, "localhost", 8000):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())