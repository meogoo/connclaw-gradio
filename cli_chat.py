#!/usr/bin/env python3
"""
ConnClaw CLI 聊天工具
通过 Open Claw CLI 实现 WhatsApp 收发消息功能
"""

import subprocess
import json
import sys
import os
from datetime import datetime
from typing import List, Dict, Optional


class ConnClawCLI:
    """ConnClaw CLI 聊天客户端"""
    
    def __init__(self):
        self.channel = "whatsapp"
        self.contacts_cache = []
        
    def run_command(self, cmd: str, capture_output: bool = True) -> tuple:
        """执行 Open Claw CLI 命令"""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=capture_output,
                text=True,
                timeout=60  # 增加到 60 秒
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "命令执行超时（60秒）"
        except Exception as e:
            return -1, "", f"执行错误: {str(e)}"
    
    def get_sessions(self) -> List[Dict]:
        """获取会话列表"""
        print("📋 正在获取会话列表...")
        
        code, stdout, stderr = self.run_command("openclaw sessions 2>&1 | grep -v 'Config warnings'")
        
        if code != 0:
            print(f"❌ 获取会话失败: {stderr}")
            return []
        
        sessions = []
        lines = stdout.strip().split('\n')
        
        # 跳过标题行和空行
        for line in lines[2:]:  # 跳过前两行（store info 和 header）
            if not line.strip() or line.startswith('Session store:'):
                continue
            
            parts = line.split()
            if len(parts) >= 4:
                session = {
                    'kind': parts[0],
                    'key': parts[1],
                    'age': parts[2],
                    'model': parts[3] if len(parts) > 3 else 'unknown',
                    'raw': line
                }
                sessions.append(session)
        
        print(f"✅ 找到 {len(sessions)} 个会话")
        return sessions
    
    def send_message(self, target: str, message: str) -> bool:
        """发送消息到指定号码"""
        print(f"📤 发送消息到 {target}...")
        
        # 转义消息中的特殊字符
        escaped_message = message.replace('"', '\\"').replace('$', '\\$')
        
        cmd = f'openclaw message send --channel {self.channel} --target {target} --message "{escaped_message}" --json 2>&1 | grep -v "Config warnings"'
        
        code, stdout, stderr = self.run_command(cmd)
        
        if code != 0:
            print(f"❌ 发送失败: {stderr}")
            return False
        
        try:
            # 解析 JSON 输出
            result = json.loads(stdout)
            
            if result.get('payload', {}).get('result'):
                msg_result = result['payload']['result']
                print(f"   Run ID: {msg_result.get('runId', 'N/A')}")
                print(f"   Message ID: {msg_result.get('messageId', 'N/A')}")
                print(f"   To JID: {msg_result.get('toJid', 'N/A')}")
                return True
            else:
                print(f"❌ 发送失败: 未收到确认")
                return False
                
        except json.JSONDecodeError:
            print(f"❌ 解析响应失败")
            print(f"输出: {stdout}")
            return False
    
    def list_contacts(self) -> List[str]:
        """从配置中获取允许的联系人列表"""
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
                    # 解析 allow:+8618610290897,+8618510173921
                    try:
                        numbers = line.split('allow:')[1].strip()
                        contacts = [num.strip() for num in numbers.split(',') if num.strip()]
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
                    # 匹配类似 whats...290897 的模式
                    if 'whats' in line.lower():
                        # 提取号码部分
                        import re
                        matches = re.findall(r'whats\.\.\.(\d+)', line)
                        if matches:
                            # 添加 +86 前缀（中国号码）
                            for match in matches:
                                contact = f"+86{match}"
                                if contact not in contacts:
                                    contacts.append(contact)
        
        # 方法3: 硬编码已知联系人（作为最后的备选）
        if not contacts:
            print("⚠️  自动检测失败，使用默认联系人列表...")
            # 这些是从之前测试中已知的联系人
            contacts = ["+8618610290897", "+8618510173921"]
        
        if contacts:
            print(f"✅ 找到 {len(contacts)} 个联系人:")
            for i, contact in enumerate(contacts, 1):
                print(f"   {i}. {contact}")
        else:
            print("❌ 未找到任何联系人")
            print("💡 提示: 请确保 WhatsApp 通道已正确配置并有会话历史")
        
        self.contacts_cache = contacts
        return contacts
    
    def interactive_chat(self, target: str = None):
        """交互式聊天模式"""
        print("\n" + "="*60)
        print("💬 ConnClaw 交互式聊天")
        print("="*60)
        
        # 如果没有指定目标，让用户选择
        if not target:
            contacts = self.list_contacts()
            if not contacts:
                print("\n❌ 没有可用的联系人")
                return
            
            print("\n请选择联系人:")
            for i, contact in enumerate(contacts, 1):
                print(f"  {i}. {contact}")
            
            try:
                choice = input("\n输入序号 (或输入完整号码): ").strip()
                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(contacts):
                        target = contacts[idx]
                    else:
                        print("❌ 无效的选择")
                        return
                else:
                    target = choice
            except KeyboardInterrupt:
                return
        
        print(f"\n🗨️  正在与 {target} 聊天")
        print("输入消息后按 Enter 发送")
        print("输入 'quit' 或 'exit' 退出")
        print("输入 'history' 查看会话历史")
        print("-" * 60)
        
        while True:
            try:
                message = input("\n您: ").strip()
                
                if not message:
                    continue
                
                # 退出命令
                if message.lower() in ['quit', 'exit', 'q']:
                    break
                
                # 查看历史
                if message.lower() == 'history':
                    self.show_session_history(target)
                    continue
                
                # 发送消息
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{timestamp}] 发送中...")
                
                success = self.send_message(target, message)
                
                if success:
                    print(f"[{timestamp}] ✓ 已发送")
                else:
                    print(f"[{timestamp}] ✗ 发送失败")
                    
            except KeyboardInterrupt:
                break
            except EOFError:
                break
    
    def show_session_history(self, target: str):
        """显示会话历史"""
        print(f"\n📜 查看与 {target} 的会话历史...")
        
        cmd = f"openclaw sessions 2>&1 | grep '{target}'"
        code, stdout, stderr = self.run_command(cmd)
        
        if code == 0 and stdout.strip():
            print(stdout)
        else:
            print("⚠️  未找到该联系人的会话记录")
            print("💡 提示: 需要先发送至少一条消息才会创建会话")
    
    def quick_send(self, target: str, message: str):
        """快速发送消息（非交互模式）"""
        print(f"📤 发送消息到 {target}")
        print(f"内容: {message}\n")
        
        success = self.send_message(target, message)
        
        if success:
            print("\n✅ 完成")
            sys.exit(0)
        else:
            print("\n❌ 失败")
            sys.exit(1)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='ConnClaw CLI 聊天工具 - WhatsApp 消息收发',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 交互式聊天
  python cli_chat.py
  
  # 快速发送消息
  
  # 查看联系人
  python cli_chat.py --list
  
  # 查看会话历史
  python cli_chat.py --sessions
        """
    )
    
    parser.add_argument('--to', '-t', help='目标号码 (E.164 格式, 如 +8618610290897)')
    parser.add_argument('--message', '-m', help='消息内容')
    parser.add_argument('--list', '-l', action='store_true', help='列出联系人')
    parser.add_argument('--sessions', '-s', action='store_true', help='查看会话列表')
    
    args = parser.parse_args()
    
    cli = ConnClawCLI()
    
    # 列出联系人
    if args.list:
        cli.list_contacts()
        return
    
    # 查看会话
    if args.sessions:
        cli.get_sessions()
        return
    
    # 快速发送
    if args.to and args.message:
        cli.quick_send(args.to, args.message)
        return
    
    # 只提供了目标，进入交互模式
    if args.to:
        cli.interactive_chat(args.to)
        return
    
    # 默认进入交互模式
    cli.interactive_chat()


if __name__ == "__main__":
    main()
