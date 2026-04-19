#!/usr/bin/env python3
"""
Open Claw Gateway 连接测试脚本
用于诊断连接问题
"""

import websocket
import json
import uuid
import time
import sys
import hmac
import hashlib
from dotenv import load_dotenv
import os

load_dotenv()

def sign_challenge(nonce: str, timestamp: int, device_id: str, private_key: str) -> str:
    """签名挑战"""
    payload = f"{nonce}:{timestamp}:{device_id}"
    return hmac.new(
        private_key.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

def test_connection():
    host = os.getenv('OPENCLAW_HOST', 'localhost')
    port = int(os.getenv('OPENCLAW_PORT', '12244'))
    token = os.getenv('OPENCLAW_TOKEN', '')
    
    ws_url = f"ws://{host}:{port}"
    print(f"🔌 测试连接到: {ws_url}")
    print(f"🔑 Token: {'已配置' if token else '未配置'}")
    print()
    
    # 使用固定的 device ID 以便配对
    device_id = "connclaw-test-device"
    private_key = uuid.uuid4().hex
    
    messages_received = []
    
    def on_open(ws):
        print("✅ WebSocket 连接建立")
    
    def on_message(ws, message):
        try:
            data = json.loads(message)
            messages_received.append(data)
            print(f"\n📨 收到消息 #{len(messages_received)}:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            
            # 如果收到 challenge，发送 connect
            if data.get('type') == 'event' and data.get('event') == 'connect.challenge':
                print("\n🔑 收到 challenge，准备发送 connect...")
                
                nonce = data['payload']['nonce']
                timestamp = int(time.time() * 1000)
                signature = sign_challenge(nonce, timestamp, device_id, private_key)
                
                connect_request = {
                    "type": "req",
                    "id": str(uuid.uuid4()),
                    "method": "connect",
                    "params": {
                        "minProtocol": 3,
                        "maxProtocol": 3,
                        "client": {
                            "id": "test",
                            "version": "1.0.0",
                            "platform": "linux",
                            "mode": "test"
                        },
                        "role": "operator",
                        "scopes": ["operator.read", "operator.write"],
                        "auth": {"token": token} if token else {},
                        "locale": "zh-CN",
                        "userAgent": "test-client/1.0.0",
                        "device": {
                            "id": device_id,
                            "publicKey": private_key,
                            "signature": signature,
                            "signedAt": timestamp,
                            "nonce": nonce
                        }
                    }
                }
                
                print(f"\n📤 发送 connect 请求...")
                print(f"   Device ID: {device_id}")
                print(f"   Signature: {signature[:32]}...")
                ws.send(json.dumps(connect_request))
            
            # 如果收到 hello-ok，测试成功
            elif data.get('type') == 'res' and data.get('ok'):
                payload = data.get('payload', {})
                if payload.get('type') == 'hello-ok':
                    print("\n✅✅✅ 连接成功！")
                    print(f"协议版本: {payload.get('protocol')}")
                    print(f"服务器: {payload.get('server', {}).get('version')}")
                    print(f"可用方法: {len(payload.get('features', {}).get('methods', []))}")
                    print(f"可用事件: {len(payload.get('features', {}).get('events', []))}")
                    
                    # 等待 2 秒后关闭
                    time.sleep(2)
                    ws.close()
        
        except Exception as e:
            print(f"❌ 处理错误: {e}")
            import traceback
            traceback.print_exc()
    
    def on_error(ws, error):
        print(f"❌ WebSocket 错误: {error}")
    
    def on_close(ws, close_status_code, close_msg):
        print(f"\n⚠️  连接关闭: status={close_status_code}, msg={close_msg}")
        print(f"\n总共收到 {len(messages_received)} 条消息")
        
        if len(messages_received) == 0:
            print("\n❌ 未收到任何消息，可能的原因:")
            print("   1. Gateway 未在运行")
            print("   2. 端口配置错误")
            print("   3. 防火墙阻止连接")
        elif len(messages_received) == 1 and messages_received[0].get('event') == 'connect.challenge':
            print("\n⚠️  收到 challenge 但未完成握手")
            print("   可能原因:")
            print("   - connect 请求格式错误")
            print("   - 认证失败（需要 token/password）")
            print("   - 设备未配对")
    
    # 创建连接
    ws = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    
    try:
        ws.run_forever()
    except KeyboardInterrupt:
        print("\n\n用户中断")
        ws.close()

if __name__ == "__main__":
    print("=" * 60)
    print("Open Claw Gateway 连接测试工具")
    print("=" * 60)
    print()
    test_connection()
