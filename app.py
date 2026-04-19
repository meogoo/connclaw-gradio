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
        """获取联系人列表（优化版：优先从配置文件读取）"""
        print("📇 获取联系人列表...")
        
        contacts = []
        source_method = "未知"
        
        # 方法1: 直接从 Open Claw 配置文件读取 allowFrom（最快最可靠）
        print("🔍 尝试从配置文件读取 allowFrom...")
        
        # 优先检查项目目录下的配置文件，其次检查用户主目录
        local_config = os.path.join(os.path.dirname(__file__), "openclaw.json")
        user_config = os.path.expanduser("~/.openclaw/openclaw.json")
        
        config_path = None
        if os.path.exists(local_config):
            config_path = local_config
            print(f"   📄 使用项目目录配置: {local_config}")
        elif os.path.exists(user_config):
            config_path = user_config
            print(f"   📄 使用用户配置: {user_config}")
        else:
            print(f"   ⚠️  配置文件不存在 (已检查: {local_config}, {user_config})")
        
        if config_path:
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                print(f"   ✅ JSON 解析成功")
                
                # 多种方式查找 WhatsApp 配置（兼容不同格式）
                whatsapp_config = None
                
                # 方式1: channels.whatsapp (标准格式)
                if 'channels' in config:
                    if isinstance(config['channels'], dict):
                        whatsapp_config = config['channels'].get('whatsapp', {})
                        if whatsapp_config:
                            print(f"   📋 找到路径: channels.whatsapp")
                    else:
                        print(f"   ⚠️  channels 字段类型错误: {type(config['channels']).__name__}，期望 dict")
                
                # 方式2: 直接在根级别 (简化格式)
                if not whatsapp_config and 'whatsapp' in config:
                    whatsapp_config = config['whatsapp']
                    if isinstance(whatsapp_config, dict):
                        print(f"   📋 找到路径: whatsapp (根级别)")
                    else:
                        print(f"   ⚠️  whatsapp 字段类型错误: {type(whatsapp_config).__name__}，期望 dict")
                        whatsapp_config = None
                
                if whatsapp_config and isinstance(whatsapp_config, dict):
                    # 尝试多个可能的字段名（按优先级）
                    allow_from = None
                    found_field = None
                    
                    for field_name in ['allowFrom', 'allow_from', 'allowedNumbers', 'contacts']:
                        if field_name in whatsapp_config:
                            allow_from = whatsapp_config[field_name]
                            found_field = field_name
                            print(f"   📋 找到字段: {field_name} (类型: {type(allow_from).__name__})")
                            break
                    
                    if allow_from is not None:
                        if isinstance(allow_from, list):
                            # 过滤并转换联系人列表
                            contacts = []
                            for num in allow_from:
                                if num is None:
                                    continue
                                num_str = str(num).strip()
                                if num_str:
                                    contacts.append({"id": num_str, "name": num_str})
                            
                            if contacts:
                                source_method = f"配置文件 {found_field} ({len(contacts)} 个联系人)"
                                print(f"   ✅ 从配置文件找到 {len(contacts)} 个联系人:")
                                for c in contacts:
                                    print(f"      - {c['id']}")
                                self.contacts_cache = contacts
                                print(f"   📌 联系人来源: {source_method}")
                                return contacts
                            else:
                                print(f"   ⚠️  {found_field} 列表为空或所有条目无效")
                        else:
                            print(f"   ⚠️  {found_field} 字段类型错误: {type(allow_from).__name__}，期望 list")
                            print(f"      实际值: {allow_from}")
                    else:
                        print(f"   ⚠️  WhatsApp 配置中未找到任何联系人字段")
                        print(f"      可用字段: {list(whatsapp_config.keys())}")
                else:
                    print("   ⚠️  配置文件中未找到 WhatsApp 通道配置")
                    # 显示可用的顶级键以便调试
                    if isinstance(config, dict):
                        top_keys = list(config.keys())
                        print(f"      配置文件顶级键: {top_keys[:10]}{'...' if len(top_keys) > 10 else ''}")
                    
            except json.JSONDecodeError as e:
                print(f"   ❌ JSON 解析失败: {e}")
                print(f"      文件: {config_path}")
                print(f"      提示: 请检查 JSON 格式是否正确")
            except PermissionError as e:
                print(f"   ❌ 权限不足，无法读取配置文件: {e}")
                print(f"      文件: {config_path}")
                print(f"      提示: 请检查文件权限 (当前需要可读)")
            except Exception as e:
                print(f"   ❌ 读取配置文件失败: {type(e).__name__}: {e}")
                import traceback
                print(f"      详细错误:\n{traceback.format_exc()}")
        
        # 方法2: 从 Gateway 状态中获取允许的联系人
        print("⚠️  从配置文件读取失败，尝试从 channels status 获取...")
        stdout = getattr(self, '_cached_status_output', None)
        
        if not stdout:
            print("⚠️  无缓存状态，重新执行 channels status 命令...")
            code, stdout, stderr = self.run_command(
                "openclaw channels status 2>&1 | grep 'WhatsApp'"
            )
        
        if stdout:
            print(f"📋 解析 channels status 输出 (长度: {len(stdout)} 字符)")
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
                        if contacts:
                            source_method = "channels status (allow 列表)"
                            print(f"✅ 从通道配置找到 {len(contacts)} 个联系人:")
                            for c in contacts:
                                print(f"   - {c['id']}")
                            self.contacts_cache = contacts
                            print(f"📌 联系人来源: {source_method}")
                            return contacts
                    except Exception as e:
                        print(f"⚠️  解析 allow 字段失败: {e}")
                        pass
        
        # 方法3: 如果上面失败，从会话历史中提取联系人
        print("⚠️  从通道配置获取失败，尝试从会话历史提取...")
        code, stdout, stderr = self.run_command(
            "openclaw sessions 2>&1 | grep whatsapp"
        )
        
        if code == 0 and stdout:
            print(f"📋 解析 sessions 输出 (长度: {len(stdout)} 字符)")
            session_count = 0
            for line in stdout.split('\n'):
                if 'whats' in line.lower():
                    session_count += 1
                    # 提取号码部分 (如 whats...290897)
                    matches = re.findall(r'whats\.\.\.(\d+)', line)
                    if matches:
                        for match in matches:
                            contact_id = f"+86{match}"
                            contacts.append({
                                "id": contact_id,
                                "name": contact_id
                            })
            
            if contacts:
                source_method = f"sessions 历史 ({session_count} 个会话)"
                print(f"✅ 从会话历史找到 {len(contacts)} 个联系人:")
                for c in contacts:
                    print(f"   - {c['id']}")
                self.contacts_cache = contacts
                print(f"📌 联系人来源: {source_method}")
                return contacts
            else:
                print(f"⚠️  找到 {session_count} 个会话但未能提取到有效号码")
        
        # 方法4: 硬编码已知联系人（作为最后的备选）
        print("⚠️  自动检测失败，使用默认联系人列表...")
        contacts = [
            {"id": "+8618610290897", "name": "+8618610290897"},
            {"id": "+8618510173921", "name": "+8618510173921"}
        ]
        
        source_method = "硬编码默认列表"
        self.contacts_cache = contacts
        print(f"✅ 使用默认联系人列表 ({len(contacts)} 个):")
        for c in contacts:
            print(f"   - {c['id']}")
        print(f"📌 联系人来源: {source_method}")
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
contact_buttons_state = []  # 存储联系人按钮组件引用


def init_client():
    """初始化客户端"""
    global client, contact_buttons_state
    
    try:
        print("\n" + "="*60)
        print("🔄 正在初始化 ConnClaw...")
        print("="*60)
        
        # 步骤 1: 创建客户端
        print("\n[1/3] 创建 CLI 客户端...")
        client = OpenClawCLI()
        
        # 步骤 2: 测试连接
        print("[2/3] 测试与 Open Claw Gateway 的连接...")
        if not client.connect():
            print("❌ 连接失败")
            return gr.update(choices=[]), "❌ 连接失败：无法连接到 Open Claw Gateway", gr.update(visible=False)
        
        # 步骤 3: 获取联系人
        print("[3/3] 获取联系人列表...")
        contacts = client.get_contacts()
        
        # 转换联系人格式以适应 Radio - 使用 tuple() 确保是元组
        contact_choices = [tuple([c['name'], c['id']]) for c in contacts]
        
        print("\n" + "="*60)
        print(f"✅ 初始化完成！找到 {len(contacts)} 个联系人")
        print(f"   联系人格式: {contact_choices[:2]}")  # 打印前两个用于调试
        print("="*60 + "\n")
        
        # 返回联系人列表、状态信息和显示联系人区域的更新
        return gr.update(choices=contact_choices), f"✅ 连接成功！找到 {len(contacts)} 个联系人，请点击选择开始聊天", gr.update(visible=True)
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"\n❌ 连接错误:\n{error_detail}")
        return gr.update(choices=[]), f"❌ 连接失败: {str(e)}", gr.update(visible=False)


def select_contact(contact_id: str):
    """选择联系人（通过 Radio 组件）"""
    global current_contact_name
    
    if not client:
        return [], "❌ 未初始化客户端"
    
    if not contact_id:
        return [], "⚠️  请先选择一个联系人"
    
    print(f"📌 尝试选择联系人 ID: {contact_id}")
    
    # 查找联系人（支持按 ID 匹配）
    contact = next((c for c in client.contacts_cache if c['id'] == contact_id), None)
    
    if not contact:
        print(f"❌ 在缓存中未找到联系人: {contact_id}")
        print(f"   当前缓存的联系人: {[c['id'] for c in client.contacts_cache]}")
        return [], f"❌ 找不到联系人: {contact_id}"
    
    current_contact_name = contact['name']
    client.select_contact(contact['id'])
    
    # 加载历史消息
    messages = client.get_messages(contact['id'])
    
    status_msg = f"💬 正在与 {contact['name']} 聊天"
    print(f"✅ {status_msg}")
    
    return messages, status_msg


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
            
            # 联系人选择区域（初始隐藏）
            with gr.Column(visible=False) as contacts_section:
                gr.Markdown("**选择联系人:**")
                contact_radio = gr.Radio(
                    label="",
                    choices=[],
                    interactive=True,
                    info="点击选择联系人"
                )
                gr.Markdown("""
                **💡 提示:**
                - 点击任意联系人即可开始聊天
                - 历史消息会自动加载
                """)
        
        # 右侧：聊天界面
        with gr.Column(scale=3):
            gr.Markdown("### 💬 聊天")
            chatbot = gr.Chatbot(label="消息记录", height=500)
            with gr.Row():
                msg_input = gr.Textbox(
                    label="输入消息", 
                    placeholder="请先选择联系人...", 
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
        outputs=[contact_radio, status_text, contacts_section]
    ).then(
        fn=lambda: gr.update(interactive=True),
        outputs=[contact_radio]
    )
    
    contact_radio.change(
        fn=select_contact,
        inputs=[contact_radio],
        outputs=[chatbot, status_text]
    ).then(
        fn=lambda: (gr.update(interactive=True, placeholder="输入消息后按 Enter 或点击发送..."), gr.update(interactive=True)),
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
