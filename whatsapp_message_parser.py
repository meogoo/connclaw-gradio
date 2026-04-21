#!/usr/bin/env python3
"""
WhatsApp 消息日志解析器
从 whatsapp_messages.log 文件中解析好友交互消息
"""
import json
import re
import time
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


class WhatsAppMessageParser:
    """WhatsApp 消息日志解析器（带缓存）"""
    
    def __init__(self, log_file: str = None):
        if log_file is None:
            # 默认使用项目根目录下的 whatsapp_messages.log
            self.log_file = Path(__file__).parent / "whatsapp_messages.log"
        else:
            self.log_file = Path(log_file)
        
        # 当前用户的号码（需要从配置中获取，这里暂时硬编码或从环境变量读取）
        self.user_number = None
        
        # 缓存机制
        self._cache = {}  # {contact_id: {"messages": [...], "last_update": timestamp}}
        self._cache_ttl = 2  # 缓存有效期（秒）
        self._last_file_size = 0  # 上次文件大小（用于检测文件变化）
        self._last_parse_time = 0  # 上次解析时间
    
    def set_user_number(self, number: str):
        """设置当前用户的号码"""
        self.user_number = number
    
    def parse_log_file(self, contact_filter: Optional[str] = None, max_lines: int = 1000, force_refresh: bool = False) -> List[Dict]:
        """
        解析日志文件，提取消息（带缓存）
        
        Args:
            contact_filter: 联系人号码过滤（可选）
            max_lines: 最大处理行数
            force_refresh: 强制刷新（忽略缓存）
            
        Returns:
            消息列表，按时间戳排序
        """
        current_time = time.time()
        
        # 检查缓存是否有效
        cache_key = contact_filter or "__all__"
        if not force_refresh and cache_key in self._cache:
            cache_entry = self._cache[cache_key]
            # 缓存未过期且文件未变化
            if (current_time - cache_entry["last_update"] < self._cache_ttl and
                self._check_file_unchanged()):
                print(f"✅ [缓存命中] {cache_key} - 返回 {len(cache_entry['messages'])} 条消息")
                return cache_entry["messages"]
            else:
                if current_time - cache_entry["last_update"] >= self._cache_ttl:
                    print(f"⏰ [缓存过期] {cache_key} - 已存在 {int(current_time - cache_entry['last_update'])} 秒 (TTL: {self._cache_ttl}秒)")
                else:
                    print(f"📄 [文件变化] {cache_key} - 检测到日志文件大小变化")
        
        # 缓存无效，重新解析
        print(f"\n{'='*60}")
        print(f"🔍 [开始解析] 日志文件: {self.log_file}")
        print(f"   用户号码: {self.user_number}")
        if contact_filter:
            print(f"   联系人过滤: {contact_filter}")
        print(f"   最大行数: {max_lines}")
        print(f"{'='*60}")
        
        if not self.log_file.exists():
            print(f"⚠️  日志文件不存在: {self.log_file}")
            return []
        
        # 显示文件大小
        file_size = self.log_file.stat().st_size
        print(f"📊 日志文件大小: {file_size} 字节 ({file_size/1024:.2f} KB)")
        
        messages = []
        line_count = 0
        parsed_count = 0
        filtered_count = 0
        web_auto_reply_count = 0
        
        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line_count += 1
                    if line_count > max_lines:
                        print(f"⚠️  达到最大行数限制: {max_lines}")
                        break
                    
                    # 只处理包含 web-auto-reply 的行
                    if 'web-auto-reply' not in line:
                        continue
                    
                    web_auto_reply_count += 1
                    
                    # 解析单行日志
                    parsed = self._parse_line(line.strip())
                    if parsed:
                        parsed_count += 1
                        
                        # 如果指定了联系人过滤
                        if contact_filter:
                            from_num = parsed.get('from', '')
                            to_num = parsed.get('to', '')
                            # 检查是否与该联系人相关
                            if contact_filter not in from_num and contact_filter not in to_num:
                                filtered_count += 1
                                continue
                        
                        messages.append(parsed)
        
        except Exception as e:
            print(f"❌ 读取日志文件失败: {e}")
            import traceback
            traceback.print_exc()
        
        # 按时间戳排序
        messages.sort(key=lambda x: x.get('timestamp', ''))
        
        # 更新缓存
        self._cache[cache_key] = {
            "messages": messages,
            "last_update": current_time
        }
        self._last_file_size = self.log_file.stat().st_size if self.log_file.exists() else 0
        self._last_parse_time = current_time
        
        # 打印解析统计
        print(f"\n{'='*60}")
        print(f"✅ [解析完成]")
        print(f"   总行数: {line_count}")
        print(f"   web-auto-reply 行: {web_auto_reply_count}")
        print(f"   成功解析: {parsed_count}")
        if contact_filter:
            print(f"   被过滤: {filtered_count}")
        print(f"   最终消息数: {len(messages)}")
        print(f"   缓存已更新 (TTL: {self._cache_ttl}秒)")
        print(f"{'='*60}\n")
        
        return messages
    
    def _check_file_unchanged(self) -> bool:
        """检查文件是否未变化"""
        if not self.log_file.exists():
            return False
        
        current_size = self.log_file.stat().st_size
        return current_size == self._last_file_size
    
    def clear_cache(self):
        """清除所有缓存"""
        self._cache.clear()
        self._last_file_size = 0
        self._last_parse_time = 0
    
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
            except Exception as e:
                print(f"⚠️  时间戳转换失败: {e}, 原始值: {timestamp_str}")
                formatted_time = timestamp_str
            
            # 调试日志：显示解析结果
            print(f"📨 [解析成功] {direction} | From: {from_number} -> To: {to_number} | Content: {content[:50]}{'...' if len(content) > 50 else ''}")
            
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
            # 打印解析失败的详细信息，便于调试
            print(f"⚠️  [解析失败] {type(e).__name__}: {e}")
            print(f"   Line preview: {line[:150]}...")
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