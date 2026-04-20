import gradio as gr
import subprocess
import json
import uuid
import time
import re
import threading
from datetime import datetime
from typing import List, Dict, Optional
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 导入 WhatsApp 消息解析器
from whatsapp_message_parser import WhatsAppMessageParser


class MessageCache:
    """本地消息缓存管理器"""
    
    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(__file__), ".message_cache")
        
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.cache_file = os.path.join(cache_dir, "messages.json")
        self.messages = self._load_cache()
    
    def _load_cache(self) -> Dict[str, List[Dict]]:
        """从文件加载缓存"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️  加载缓存失败: {e}")
                return {}
        return {}
    
    def _save_cache(self):
        """保存缓存到文件"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.messages, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"❌ 保存缓存失败: {e}")
    
    def add_message(self, contact_id: str, message: Dict):
        """添加消息到缓存"""
        if contact_id not in self.messages:
            self.messages[contact_id] = []
        
        # 检查是否已存在（基于 messageId 去重）
        message_id = message.get('metadata', {}).get('messageId', '')
        if message_id:
            for existing in self.messages[contact_id]:
                if existing.get('metadata', {}).get('messageId') == message_id:
                    return  # 已存在，跳过
        
        self.messages[contact_id].append(message)
        
        # 限制每个联系人的消息数量（保留最近 500 条）
        if len(self.messages[contact_id]) > 500:
            self.messages[contact_id] = self.messages[contact_id][-500:]
        
        # 定期保存（每添加 10 条消息保存一次）
        if len(self.messages[contact_id]) % 10 == 0:
            self._save_cache()
    
    def get_messages(self, contact_id: str, limit: int = 50) -> List[Dict]:
        """获取指定联系人的消息"""
        if contact_id not in self.messages:
            return []
        
        messages = self.messages[contact_id]
        # 按时间排序
        messages.sort(key=lambda x: x.get('timestamp', ''))
        # 返回最近的 limit 条
        return messages[-limit:]
    
    def save_all(self):
        """强制保存所有缓存"""
        self._save_cache()


class LogMessageParser:
    """Open Claw 日志消息解析器（预留接口）"""
    
    def __init__(self, message_cache: MessageCache = None):
        self.message_cache = message_cache or MessageCache()


class OpenClawCLI:
    """Open Claw CLI 客户端 - 通过命令行调用实现收发消息"""
    
    def __init__(self, user_number: str = None):
        self.channel = "whatsapp"
        self.contacts_cache = []
        self.current_contact = None
        self.log_parser = LogMessageParser()  # 初始化日志解析器
        
        # 强制从环境变量读取用户号码
        if not user_number:
            user_number = os.environ.get('CURRENT_USER_NUMBER', '').strip()
        
        # 验证用户号码
        if not user_number:
            print("❌ 错误: 未设置 CURRENT_USER_NUMBER 环境变量")
            print("   请确保通过 start.sh 启动应用")
            print("   或手动设置: export CURRENT_USER_NUMBER='+86xxxxxxxxxxx'")
            sys.exit(1)
        
        self.user_number = user_number
        print(f"✅ 当前用户号码: {self.user_number}")
        
        # 初始化 WhatsApp 消息解析器
        log_file_path = os.path.join(os.path.dirname(__file__), "whatsapp_messages.log")
        self.whatsapp_parser = WhatsAppMessageParser(log_file=log_file_path)
        
        # 设置用户号码到解析器
        self.whatsapp_parser.set_user_number(self.user_number)
    
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
    
    def get_contacts_excluding_self(self) -> List[Dict]:
        """获取联系人列表，排除当前用户自己"""
        all_contacts = self.get_contacts()
        
        if not self.user_number:
            print("⚠️  未设置用户号码，返回所有联系人")
            return all_contacts
        
        # 过滤掉当前用户自己的号码
        filtered_contacts = [
            contact for contact in all_contacts 
            if contact['id'] != self.user_number
        ]
        
        excluded_count = len(all_contacts) - len(filtered_contacts)
        if excluded_count > 0:
            print(f"✅ 已排除 {excluded_count} 个自己的号码: {self.user_number}")
            print(f"   剩余联系人: {len(filtered_contacts)} 个")
        else:
            print(f"✅ 返回所有联系人: {len(filtered_contacts)} 个")
        
        return filtered_contacts
    
    def send_message(self, to: str, content: str) -> Dict:
        """发送消息到指定号码"""
        print(f"📤 发送消息到 {to}...")
        
        # 转义消息中的特殊字符
        escaped_content = content.replace('"', '\\"').replace('$', '\\$')
        
        # 构建 CLI 命令（不使用 --json）
        cmd = f'openclaw message send --channel {self.channel} --target {to} --message "{escaped_content}" 2>&1 | grep -v "Config warnings"'
        
        # 🔍 打印执行的命令
        print(f"🔧 执行命令: openclaw message send --channel {self.channel} --target {to} --message \"{content}\"")
        
        code, stdout, stderr = self.run_command(cmd, timeout=60)
        
        # 🔍 打印完整输出
        print(f"📋 命令返回码: {code}")
        if stdout:
            print(f"📋 命令输出:\n{stdout}")
        if stderr:
            print(f"⚠️  标准错误:\n{stderr}")
        
        if code != 0:
            error_msg = stderr if stderr else "未知错误"
            print(f"❌ 发送失败 (退出码 {code}): {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        
        # 非 JSON 模式：检查输出中是否包含成功标识
        # 成功的输出通常包含 "Message sent" 或类似的成功提示
        if "Error" in stdout or "error" in stdout.lower():
            print(f"❌ 发送失败: 输出中包含错误信息")
            return {
                "success": False,
                "error": f"发送失败: {stdout[:200]}",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        
        # 假设没有错误即为成功
        print(f"✅ 消息发送成功!")
        print(f"   - 目标: {to}")
        print(f"   - 内容: {content[:50]}{'...' if len(content) > 50 else ''}")
        
        return {
            "success": True,
            "runId": "",
            "messageId": "",
            "toJid": to,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "output": stdout
        }
    
    def get_messages(self, contact_id: str, limit: int = 50) -> List[Dict]:
        """获取历史消息（从 WhatsApp 日志文件读取）"""
        print(f"📜 获取与 {contact_id} 的会话历史...")
        
        # user_number 已在 __init__ 中强制设置，这里直接使用
        # 不需要再从其他地方读取
        
        # 从日志文件中解析消息
        print("🔍 从 WhatsApp 日志文件读取消息...")
        try:
            messages = self.whatsapp_parser.parse_log_file(
                contact_filter=contact_id,
                max_lines=2000  # 最多处理2000行
            )
            
            if messages:
                print(f"✅ 从日志文件读取到 {len(messages)} 条消息")
                # 返回最近的 limit 条
                return messages[-limit:]
            else:
                print("⚠️  日志文件中暂无该联系人的消息")
        except Exception as e:
            print(f"⚠️  日志文件读取失败: {e}")
            import traceback
            traceback.print_exc()
        
        # 如果日志文件也没有，尝试从缓存读取
        print("🔍 尝试从本地缓存读取...")
        try:
            cached_messages = self.log_parser.message_cache.get_messages(contact_id, limit)
            
            if cached_messages:
                print(f"✅ 从缓存读取到 {len(cached_messages)} 条消息")
                return cached_messages
            else:
                print("⚠️  缓存中也暂无该联系人的消息")
        except Exception as e:
            print(f"⚠️  缓存读取失败: {e}")
        
        # 方法3: 如果都没有，返回提示信息
        messages = [{
            "role": "system",
            "content": f"💡 提示：暂无与 {contact_id} 的历史消息记录。\n\n可能的原因：\n1. 尚未与该联系人有过对话\n2. 日志监听器还未启动或未捕获到消息\n\n建议：\n- 发送一条新消息开始对话\n- 确保 start.sh 已正确启动日志监听器\n- 检查 whatsapp_messages.log 文件是否存在",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }]
        
        print(f"✅ 返回 {len(messages)} 条记录")
        return messages
    
    def select_contact(self, contact_id: str):
        """选择当前联系人"""
        self.current_contact = contact_id
        print(f"✅ 已选择联系人: {contact_id}")


# 全局变量
client = None
current_contact_name = ""
contact_buttons_state = []  # 存储联系人按钮组件引用


def init_client(user_number: str = None):
    """初始化客户端
    
    Args:
        user_number: 当前用户的号码（可选），如果提供则用于过滤联系人列表
    """
    global client, contact_buttons_state
    
    try:
        print("\n" + "="*60)
        print("🔄 正在初始化 ConnClaw...")
        if user_number:
            print(f"📌 用户号码: {user_number}")
        print("="*60)
        
        # 步骤 1: 创建客户端
        print("\n[1/3] 创建 CLI 客户端...")
        client = OpenClawCLI(user_number=user_number)
        
        # 步骤 2: 测试连接
        print("[2/3] 测试与 Open Claw Gateway 的连接...")
        if not client.connect():
            print("❌ 连接失败")
            return gr.update(choices=[]), "❌ 连接失败：无法连接到 Open Claw Gateway", gr.update(visible=False)
        
        # 步骤 3: 获取联系人列表（排除自己）
        print("[3/3] 获取联系人列表...")
        contacts = client.get_contacts_excluding_self()
        
        # 转换联系人格式以适应 Radio - 使用 tuple() 确保是元组
        contact_choices = [tuple([c['name'], c['id']]) for c in contacts]
        
        print("\n" + "="*60)
        print(f"✅ 初始化完成！找到 {len(contacts)} 个联系人")
        if user_number:
            print(f"   已排除自己的号码: {user_number}")
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
    def connect_with_user_number():
        """包装函数，初始化客户端（user_number 会在 OpenClawCLI.__init__ 中从环境变量自动读取）"""
        return init_client()  # 不传参数，让 __init__ 自动从环境变量读取
    
    connect_btn.click(
        fn=connect_with_user_number,
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
    import signal
    import sys
    
    def cleanup(signum=None, frame=None):
        """应用退出时清理资源"""
        print("\n\n" + "="*60)
        print("🛑 正在关闭应用...")
        
        if client and hasattr(client, 'log_parser'):
            print("💾 保存消息缓存...")
            client.log_parser.message_cache.save_all()
            print("✅ 缓存已保存")
        
        print("="*60)
        sys.exit(0)
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    
    # 从环境变量读取用户号码
    user_number = os.environ.get('CURRENT_USER_NUMBER')
    if user_number:
        print("=" * 60)
        print(f"📱 当前用户号码: {user_number}")
        print("=" * 60)
    
    print("=" * 60)
    print("🚀 ConnClaw Gradio 版本启动中... (CLI 模式)")
    print("=" * 60)
    print("✅ 使用 Open Claw CLI 进行消息收发")
    print("ℹ️  无需 WebSocket 设备配对")
    print("📇 联系人列表将自动排除当前用户")
    print("=" * 60)
    demo.launch(server_name="0.0.0.0", server_port=7689, share=False)
