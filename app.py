import gradio as gr
import subprocess
import json
import uuid
import time
import re
from datetime import datetime
from typing import List, Dict, Optional
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class OpenClawCLI:
    """Open Claw CLI 客户端 - 通过命令行调用实现收发消息"""
    
    def __init__(self):
        self.channel = "whatsapp"
        self.contacts_cache = []
        self.current_contact = None
        
    def run_command(self, cmd: str, timeout: int = 60) -> tuple:
        """执行 Open Claw CLI 命令"""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"命令执行超时（{timeout}秒）"
        except Exception as e:
            return -1, "", f"执行错误: {str(e)}"
    
    def connect(self) -> bool:
        """测试与 Open Claw Gateway 的连接"""
        print("🔌 测试 Open Claw 连接...")
        
        # 通过 channels status 命令测试连接
        code, stdout, stderr = self.run_command(
            "openclaw channels status 2>&1 | grep -v 'Config warnings'"
        )
        
        if code != 0:
            print(f"❌ 连接失败: {stderr}")
            return False
        
        # 检查 WhatsApp 通道状态
        if 'WhatsApp' in stdout and ('connected' in stdout or 'running' in stdout):
            print("✅ Open Claw Gateway 连接成功")
            print("✅ WhatsApp 通道正常运行")
            return True
        else:
            print("⚠️  Gateway 可访问，但 WhatsApp 通道可能未就绪")
            print(stdout[:500])
            return True  # 仍然返回 True，允许继续操作
    
    def get_contacts(self) -> List[Dict]:
        """获取联系人列表"""
        print("📇 获取联系人列表...")
        
        contacts = []
        
        # 方法1: 从 Gateway 状态中获取允许的联系人
        code, stdout, stderr = self.run_command(
            "openclaw channels status 2>&1 | grep 'WhatsApp'"
        )
        
        if code == 0 and stdout:
            # 查找 allow: 行
            for line in stdout.split('\n'):
                if 'allow:' in line:
                    try:
                        numbers = line.split('allow:')[1].strip()
                        contacts = [
                            {"id": num.strip(), "name": num.strip()} 
                            for num in numbers.split(',') 
                            if num.strip()
                        ]
                        break
                    except:
                        pass
        
        # 方法2: 如果上面失败，从会话历史中提取联系人
        if not contacts:
            print("⚠️  从通道状态获取失败，尝试从会话历史提取...")
            code, stdout, stderr = self.run_command(
                "openclaw sessions 2>&1 | grep whatsapp"
            )
            
            if code == 0 and stdout:
                for line in stdout.split('\n'):
                    if 'whats' in line.lower():
                        # 提取号码部分 (如 whats...290897)
                        matches = re.findall(r'whats\.\.\.(\d+)', line)
                        if matches:
                            for match in matches:
                                contact_id = f"+86{match}"
                                contacts.append({
                                    "id": contact_id,
                                    "name": contact_id
                                })
        
        # 方法3: 硬编码已知联系人（作为最后的备选）
        if not contacts:
            print("⚠️  自动检测失败，使用默认联系人列表...")
            contacts = [
                {"id": "+8618610290897", "name": "+8618610290897"},
                {"id": "+8618510173921", "name": "+8618510173921"}
            ]
        
        self.contacts_cache = contacts
        print(f"✅ 找到 {len(contacts)} 个联系人")
        return contacts
    
    def send_message(self, to: str, content: str) -> Dict:
        """发送消息到指定号码"""
        print(f"📤 发送消息到 {to}...")
        
        # 转义消息中的特殊字符
        escaped_content = content.replace('"', '\\"').replace('$', '\\$')
        
        cmd = f'openclaw message send --channel {self.channel} --target {to} --message "{escaped_content}" --json 2>&1 | grep -v "Config warnings"'
        
        code, stdout, stderr = self.run_command(cmd, timeout=60)
        
        if code != 0:
            error_msg = stderr if stderr else "未知错误"
            print(f"❌ 发送失败: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        
        try:
            # 解析 JSON 输出
            result = json.loads(stdout)
            
            if result.get('payload', {}).get('result'):
                msg_result = result['payload']['result']
                print(f"✅ 消息发送成功!")
                
                return {
                    "success": True,
                    "runId": msg_result.get('runId', ''),
                    "messageId": msg_result.get('messageId', ''),
                    "toJid": msg_result.get('toJid', ''),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            else:
                print(f"❌ 发送失败: 未收到确认")
                return {
                    "success": False,
                    "error": "未收到发送确认",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                
        except json.JSONDecodeError:
            print(f"❌ 解析响应失败")
            return {
                "success": False,
                "error": f"解析响应失败: {stdout[:200]}",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
    
    def get_messages(self, contact_id: str, limit: int = 50) -> List[Dict]:
        """获取历史消息（通过查看会话信息）"""
        print(f"📜 获取与 {contact_id} 的会话历史...")
        
        messages = []
        
        # 获取会话信息
        code, stdout, stderr = self.run_command(
            f"openclaw sessions 2>&1 | grep '{contact_id[-6:]}'"
        )
        
        if code == 0 and stdout.strip():
            # 解析会话信息
            lines = stdout.strip().split('\n')
            for line in lines:
                if contact_id[-6:] in line:
                    messages.append({
                        "role": "system",
                        "content": f"会话信息: {line.strip()}",
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
        
        # 注意：Open Claw CLI 目前没有直接获取历史消息的命令
        # 这里返回一个提示消息
        if not messages:
            messages.append({
                "role": "system",
                "content": "💡 提示：当前 CLI 模式暂不支持查看完整历史消息。\n您可以直接发送新消息开始对话。",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        
        print(f"✅ 获取到 {len(messages)} 条记录")
        return messages
    
    def select_contact(self, contact_id: str):
        """选择当前联系人"""
        self.current_contact = contact_id
        print(f"✅ 已选择联系人: {contact_id}")


# 全局变量
client = None
current_contact_name = ""


def init_client():
    """初始化客户端"""
    global client
    
    try:
        client = OpenClawCLI()
        if client.connect():
            contacts = client.get_contacts()
            # 转换联系人格式以适应 Dropdown
            contact_choices = [c['name'] for c in contacts]
            return contact_choices, "✅ 连接成功！请选择联系人开始聊天"
        else:
            return [], "❌ 连接失败：无法连接到 Open Claw Gateway"
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"❌ 连接错误:\n{error_detail}")
        return [], f"❌ 连接失败: {str(e)}"


def select_contact(contact_name: str):
    """选择联系人"""
    global current_contact_name
    
    if not client:
        return [], "❌ 未初始化客户端"
    
    # 查找联系人
    contact = next((c for c in client.contacts_cache if c['name'] == contact_name), None)
    if not contact:
        return [], f"❌ 找不到联系人: {contact_name}"
    
    current_contact_name = contact_name
    client.select_contact(contact['id'])
    
    # 加载历史消息
    messages = client.get_messages(contact['id'])
    
    return messages, f"💬 正在与 {contact_name} 聊天"


def send_message(user_message: str, chat_history: List):
    """发送消息"""
    global current_contact_name
    
    if not user_message.strip():
        return chat_history, ""
    
    if not client:
        return chat_history + [{"role": "assistant", "content": "❌ 未初始化客户端"}], ""
    
    if not client.current_contact:
        return chat_history + [{"role": "assistant", "content": "❌ 请先选择联系人"}], ""
    
    # 发送消息
    try:
        result = client.send_message(client.current_contact, user_message)
        
        if result.get('success'):
            # 更新聊天历史
            updated_history = chat_history + [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": "✅ 消息已发送"}
            ]
            return updated_history, ""
        else:
            return chat_history + [{"role": "assistant", "content": f"❌ 发送失败: {result.get('error')}"}], ""
            
    except Exception as e:
        return chat_history + [{"role": "assistant", "content": f"❌ 发送异常: {str(e)}"}], ""


def refresh_messages(chat_history: List):
    """刷新消息（CLI 模式下暂不支持实时接收）"""
    # CLI 模式通过 subprocess 调用，无法实现真正的实时推送
    # 如需接收新消息，建议定期手动刷新或使用官方 Web UI
    return chat_history


# 创建 Gradio 界面
with gr.Blocks(title="ConnClaw - WhatsApp Chat (CLI Mode)", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🐾 ConnClaw - WhatsApp 聊天 (CLI 模式)")
    gr.Markdown("通过 Open Claw CLI 与 WhatsApp 好友聊天 - **无需 WebSocket 配对**")
    
    with gr.Row():
        # 左侧：联系人列表
        with gr.Column(scale=1):
            gr.Markdown("### 📇 联系人")
            status_text = gr.Textbox(label="状态", value="点击连接按钮开始", interactive=False)
            connect_btn = gr.Button("🔌 连接到 Open Claw", variant="primary")
            contact_dropdown = gr.Dropdown(
                label="选择联系人", 
                choices=[], 
                interactive=False,
                allow_custom_value=True  # 允许手动输入号码
            )
            gr.Markdown("""
            **💡 提示:**
            - 如果联系人列表为空，可以手动输入号码
            - 格式: +8618610290897
            """)
        
        # 右侧：聊天界面
        with gr.Column(scale=3):
            gr.Markdown("### 💬 聊天")
            chatbot = gr.Chatbot(label="消息记录", height=500)
            with gr.Row():
                msg_input = gr.Textbox(
                    label="输入消息", 
                    placeholder="输入消息后按 Enter 或点击发送...", 
                    lines=2, 
                    interactive=False
                )
                send_btn = gr.Button("📤 发送", variant="primary", interactive=False)
            
            gr.Markdown("""
            **⚠️ 注意:**
            - CLI 模式仅支持**发送消息**
            - 接收消息请使用 [Open Claw 官方 Web UI](http://localhost:12244) 或手机查看
            - 发送成功后会显示 Message ID
            """)
    
    # 事件绑定
    connect_btn.click(
        fn=init_client,
        outputs=[contact_dropdown, status_text]
    ).then(
        fn=lambda: gr.update(interactive=True),
        outputs=[contact_dropdown]
    )
    
    contact_dropdown.change(
        fn=select_contact,
        inputs=[contact_dropdown],
        outputs=[chatbot, status_text]
    ).then(
        fn=lambda: (gr.update(interactive=True), gr.update(interactive=True)),
        outputs=[msg_input, send_btn]
    )
    
    send_btn.click(
        fn=send_message,
        inputs=[msg_input, chatbot],
        outputs=[chatbot, msg_input]
    )
    
    msg_input.submit(
        fn=send_message,
        inputs=[msg_input, chatbot],
        outputs=[chatbot, msg_input]
    )


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 ConnClaw Gradio 版本启动中... (CLI 模式)")
    print("=" * 60)
    print("✅ 使用 Open Claw CLI 进行消息收发")
    print("ℹ️  无需 WebSocket 设备配对")
    print("=" * 60)
    demo.launch(server_name="0.0.0.0", server_port=7689, share=False)
