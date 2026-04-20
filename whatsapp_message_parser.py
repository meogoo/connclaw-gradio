#!/usr/bin/env python3
"""
WhatsApp 消息日志解析器
从 whatsapp_messages.log 文件中解析好友交互消息
"""
import json
import re
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


class WhatsAppMessageParser:
    """WhatsApp 消息日志解析器"""
    
    def __init__(self, log_file: str = None):
        if log_file is None:
            # 默认使用项目根目录下的 whatsapp_messages.log
            self.log_file = Path(__file__).parent / "whatsapp_messages.log"
        else:
            self.log_file = Path(log_file)
        
        # 当前用户的号码（需要从配置中获取，这里暂时硬编码或从环境变量读取）
        self.user_number = None
    
    def set_user_number(self, number: str):
        """设置当前用户的号码"""
        self.user_number = number
    
    def parse_log_file(self, contact_filter: Optional[str] = None, max_lines: int = 1000) -> List[Dict]:
        """
        解析日志文件，提取消息
        
        Args:
            contact_filter: 联系人号码过滤（可选）
            max_lines: 最大处理行数
            
        Returns:
            消息列表，按时间戳排序
        """
        if not self.log_file.exists():
            print(f"⚠️  日志文件不存在: {self.log_file}")
            return []
        
        messages = []
        line_count = 0
        
        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line_count += 1
                    if line_count > max_lines:
                        break
                    
                    # 只处理包含 web-auto-reply 的行
                    if 'web-auto-reply' not in line:
                        continue
                    
                    # 解析单行日志
                    parsed = self._parse_line(line.strip())
                    if parsed:
                        # 如果指定了联系人过滤
                        if contact_filter:
                            from_num = parsed.get('from', '')
                            to_num = parsed.get('to', '')
                            # 检查是否与该联系人相关
                            if contact_filter not in from_num and contact_filter not in to_num:
                                continue
                        
                        messages.append(parsed)
        
        except Exception as e:
            print(f"❌ 读取日志文件失败: {e}")
            import traceback
            traceback.print_exc()
        
        # 按时间戳排序
        messages.sort(key=lambda x: x.get('timestamp', ''))
        
        print(f"✅ 解析完成，共找到 {len(messages)} 条消息（处理了 {line_count} 行）")
        
        return messages
    
    def _parse_line(self, line: str) -> Optional[Dict]:
        """
        解析单行日志
        
        格式示例:
        2026-04-15T02:43:41.434Z info web-auto-reply {"module":"web-auto-reply","runId":"..."} 
        {"connectionId":"...","correlationId":"...","from":"+8618510173921","to":"+8618610290897",
        "body":"[WhatsApp +8618510173921 +13s Wed 2026-04-15 10:43 GMT+8] 你能喝几斤",
        "mediaType":null,"mediaPath":null} inbound web message
        """
        try:
            # 提取时间戳
            ts_match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)', line)
            if not ts_match:
                return None
            
            timestamp_str = ts_match.group(1)
            
            # 查找 JSON 部分（第一个 { 到最后一个 }）
            start_idx = line.find('{')
            end_idx = line.rfind('}')
            
            if start_idx == -1 or end_idx == -1 or start_idx >= end_idx:
                return None
            
            # 可能有多个 JSON 对象，我们需要找到包含 from/to 字段的那个
            json_str = line[start_idx:end_idx + 1]
            
            # 尝试解析整个 JSON 字符串
            # 由于可能有多个 JSON 对象拼接，我们需要找到正确的那个
            data = None
            
            # 策略：查找所有可能的 JSON 对象
            remaining = json_str
            while remaining:
                try:
                    obj_start = remaining.find('{')
                    if obj_start == -1:
                        break
                    
                    # 找到匹配的 }
                    brace_count = 0
                    obj_end = -1
                    for i in range(obj_start, len(remaining)):
                        if remaining[i] == '{':
                            brace_count += 1
                        elif remaining[i] == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                obj_end = i
                                break
                    
                    if obj_end == -1:
                        break
                    
                    candidate = remaining[obj_start:obj_end + 1]
                    
                    # 尝试解析
                    obj = json.loads(candidate)
                    
                    # 检查是否包含我们需要的字段
                    if 'from' in obj and 'to' in obj:
                        data = obj
                        break
                    
                    # 继续查找下一个 JSON 对象
                    remaining = remaining[obj_end + 1:]
                
                except (json.JSONDecodeError, ValueError):
                    break
            
            if not data:
                return None
            
            from_number = data.get('from', '')
            to_number = data.get('to', '')
            
            # 忽略自己发给自己的消息
            if from_number == to_number:
                return None
            
            body = data.get('body', '')
            media_type = data.get('mediaType')
            
            # 从 body 中提取实际消息内容
            # 格式: [WhatsApp +8618510173921 +13s Wed 2026-04-15 10:43 GMT+8] 你能喝几斤
            content_match = re.search(r'\]\s*(.+)$', body)
            if content_match:
                content = content_match.group(1).strip()
            else:
                content = body
            
            # 如果是媒体消息
            if media_type and '<media:' in content:
                content = f"[媒体消息: {media_type}]"
            
            # 判断消息方向
            # 如果 from 是当前用户，则是发出的消息；否则是收到的消息
            direction = "outbound" if from_number == self.user_number else "inbound"
            
            # 转换时间戳格式
            try:
                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                formatted_time = timestamp_str
            
            return {
                "role": "user" if direction == "inbound" else "assistant",
                "content": content,
                "timestamp": formatted_time,
                "from": from_number,
                "to": to_number,
                "direction": direction,
                "messageId": data.get('correlationId', ''),
                "mediaType": media_type,
                "rawBody": body
            }
        
        except Exception as e:
            # 静默失败，避免刷屏
            # print(f"⚠️  解析失败: {e} | Line: {line[:100]}")
            return None


if __name__ == "__main__":
    # 测试代码
    parser = WhatsAppMessageParser()
    parser.set_user_number("+8618610290897")
    
    messages = parser.parse_log_file(contact_filter="+8618510173921")
    
    print(f"\n找到 {len(messages)} 条消息:\n")
    for msg in messages[:5]:  # 只显示前5条
        direction_icon = "📥" if msg['direction'] == 'inbound' else "📤"
        print(f"{direction_icon} [{msg['timestamp']}] {msg['from']} -> {msg['to']}")
        print(f"   内容: {msg['content'][:50]}")
        print()