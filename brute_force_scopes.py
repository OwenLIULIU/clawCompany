import asyncio
import json
import uuid
import websockets
import os

OPENCLAW_TOKEN = os.environ.get("OPENCLAW_TOKEN", "4a0c81fbca000a1211db1b06dc19b323")
# Assuming the script is run on the server where the gateway is on localhost
GATEWAY_WS = "ws://127.0.0.1:18788"

async def test_connect(variation_name, payload_update_fn):
    req_id = str(uuid.uuid4())
    payload = {
        "type": "req",
        "id": req_id,
        "method": "connect",
        "params": {
            "client": {
                "id": "gateway-client",
                "version": "1.0",
                "mode": "backend",
                "platform": "linux",
            },
            "auth": {"token": OPENCLAW_TOKEN},
            "minProtocol": 3,
            "maxProtocol": 3,
        }
    }
    
    payload_update_fn(payload)
    
    try:
        async with websockets.connect(GATEWAY_WS, ping_interval=None) as ws:
            await ws.send(json.dumps(payload))
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(msg)
            
            if not data.get("ok"):
                print(f"[{variation_name}] ❌ Connect Error: {data.get('error')}")
                return
            
            # Now test chat.send (operator.write)
            req_id2 = str(uuid.uuid4())
            await ws.send(json.dumps({
                "type": "req",
                "id": req_id2,
                "method": "chat.send",
                "params": {
                    "sessionKey": "test_session",
                    "message": "hello"
                }
            }))
            msg2 = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data2 = json.loads(msg2)
            
            if not data2.get("ok"):
                print(f"[{variation_name}] ⚠️ Chat Send Error: {data2.get('error')}")
            else:
                print(f"[{variation_name}] ✅ SUCCESS! Chat Send worked.")
                return True
                
    except Exception as e:
        print(f"[{variation_name}] ❌ Exception: {type(e).__name__} - {e}")
        
    return False

def make_mode_fn(mode):
    def fn(p): p["params"]["client"]["mode"] = mode
    return fn

def make_scope_fn(mode, loc):
    def fn(p):
        p["params"]["client"]["mode"] = mode
        if loc == "params.scopes":
            p["params"]["scopes"] = ["*"]
        elif loc == "client.scopes":
            p["params"]["client"]["scopes"] = ["*"]
        elif loc == "auth.scopes":
            p["params"]["auth"]["scopes"] = ["*"]
    return fn

async def main():
    print(f"Testing via {GATEWAY_WS}")
    print("-" * 50)
    
    modes_to_test = ["backend", "cli", "frontend", "desktop", "control", "operator", "agent", "app"]
    
    # 1. Test bare modes first
    for mode in modes_to_test:
        success = await test_connect(f"mode={mode}", make_mode_fn(mode))
        if success:
            print("\n>>> FOUND WORKING CONFIGURATION! <<<")
            return
            
    # 2. Test scopes injection if bare modes fail
    print("-" * 50)
    print("Testing scope injections...")
    for mode in ["backend", "cli"]:
        for loc in ["params.scopes", "client.scopes", "auth.scopes"]:
            await test_connect(f"mode={mode}, {loc}=[*]", make_scope_fn(mode, loc))

if __name__ == "__main__":
    asyncio.run(main())
