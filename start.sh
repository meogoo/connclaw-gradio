#!/bin/bash

echo "🚀 启动 ConnClaw Gradio 版本..."
echo ""

# 检查当前用户
CURRENT_USER=$(whoami)
if [ "$CURRENT_USER" = "root" ]; then
    echo "❌ 错误: 不能使用 root 账户运行此应用"
    echo "💡 提示: 请切换到 admin 账户后重新执行"
    echo "   切换命令: su - admin"
    exit 1
fi

if [ "$CURRENT_USER" != "admin" ]; then
    echo "⚠️  警告: 当前用户是 $CURRENT_USER，建议使用 admin 账户"
    echo "💡 提示: 如需切换到 admin 账户，请执行: su - admin"
    echo ""
fi

# 加载 conda 虚拟环境 conclaw
echo "📦 加载 conda 虚拟环境: conclaw"
source ~/miniconda3/etc/profile.d/conda.sh 2>/dev/null || source ~/anaconda3/etc/profile.d/conda.sh 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ 错误: 未找到 conda 安装路径"
    echo "💡 提示: 请确保已正确安装 conda"
    exit 1
fi

conda activate conclaw
if [ $? -ne 0 ]; then
    echo "❌ 错误: 无法激活 conda 环境 conclaw"
    echo "💡 提示: 请先创建环境: conda create -n conclaw python=3.8"
    exit 1
fi

echo "✅ Conda 环境 conclaw 已激活"
echo ""

# 检查 Python
if ! command -v python &> /dev/null; then
    echo "❌ 错误: 未找到 Python，请先安装 Python 3.8+"
    exit 1
fi

echo "✅ Python 版本: $(python --version)"
echo ""

# 配置当前用户号码
echo "=========================================="
echo "📱 配置当前用户号码"
echo "=========================================="

while true; do
    USER_NUMBER=""
    
    # 提示用户输入号码
    read -p "请输入您的 WhatsApp 号码 (+86xxxxxxxxxxx): " USER_NUMBER
    
    # 验证号码格式
    if [[ ! "$USER_NUMBER" =~ ^\+86[0-9]{11}$ ]]; then
        echo "❌ 号码格式错误！应该是 +86 开头的 13 位数字"
        echo "   例如: +8618610290897"
        echo ""
        continue
    fi
    
    echo "✅ 您输入的号码: $USER_NUMBER"
    echo ""
    
    # 验证1: 从 openclaw.json 检查
    VALIDATED=false
    CONFIG_PATHS=(
        "$(pwd)/openclaw.json"
        "$HOME/.openclaw/openclaw.json"
    )
    
    for config_path in "${CONFIG_PATHS[@]}"; do
        if [ -f "$config_path" ]; then
            ALLOWED_FROM_JSON=$(python3 -c "
import json
try:
    with open('$config_path', 'r') as f:
        config = json.load(f)
    whatsapp_config = config.get('channels', {}).get('whatsapp', {}) or config.get('whatsapp', {})
    allow_from = (
        whatsapp_config.get('allowFrom') or
        whatsapp_config.get('allow_from') or
        whatsapp_config.get('allowedNumbers') or
        whatsapp_config.get('contacts') or
        []
    )
    if isinstance(allow_from, list) and '$USER_NUMBER' in [str(x) for x in allow_from]:
        print('FOUND')
except:
    pass
" 2>/dev/null)
            
            if [ "$ALLOWED_FROM_JSON" = "FOUND" ]; then
                echo "✅ 验证通过: $USER_NUMBER 在 $config_path 中"
                VALIDATED=true
                break
            fi
        fi
    done
    
    # 验证2: 如果配置文件未找到，从 channels status 检查
    if [ "$VALIDATED" = false ]; then
        echo "🔍 检查 channels status..."
        ALLOWED_FROM_STATUS=$(openclaw channels status 2>&1 | grep -i whatsapp | grep -oP 'allow:\s*\K.*' || echo "")
        
        if [ -n "$ALLOWED_FROM_STATUS" ] && echo "$ALLOWED_FROM_STATUS" | grep -q "$USER_NUMBER"; then
            echo "✅ 验证通过: $USER_NUMBER 在 channels status 的 allow 列表中"
            echo "   allow 列表: $ALLOWED_FROM_STATUS"
            VALIDATED=true
        else
            echo "⚠️  验证失败: $USER_NUMBER 不在任何允许的联系人列表中"
            if [ -n "$ALLOWED_FROM_STATUS" ]; then
                echo "   channels status allow 列表: $ALLOWED_FROM_STATUS"
            fi
        fi
    fi
    
    # 根据验证结果决定下一步
    if [ "$VALIDATED" = true ]; then
        echo ""
        echo "✅ 用户号码配置完成: $USER_NUMBER"
        break
    else
        echo ""
        echo "请选择:"
        echo "  1. 重新输入号码"
        echo "  2. 退出启动"
        read -p "请输入选项 (1/2): " CHOICE
        
        if [ "$CHOICE" = "2" ]; then
            echo "❌ 用户取消启动"
            exit 1
        fi
        echo ""
    fi
done

echo ""

# 检查依赖
if [ ! -d "__pycache__" ]; then
    echo "📦 检查依赖..."
    pip install -r requirements.txt
fi

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "⚠️  警告: 未找到 .env 文件"
    echo "请创建 .env 文件并配置 OPENCLAW_HOST"
    exit 1
fi

# 启动 WhatsApp 日志监听器（后台进程）
echo "🔍 启动 WhatsApp 日志监听器..."
LOG_FILE="$(pwd)/whatsapp_messages.log"

# 检查是否已有监听进程在运行
if pgrep -f "openclaw logs.*grep.*whatsapp.*web-auto-reply" > /dev/null; then
    echo "⚠️  检测到已有的日志监听进程，跳过启动"
else
    # 启动后台监听进程（使用 stdbuf 禁用缓冲，确保实时写入）
    nohup bash -c "stdbuf -oL -eL openclaw logs --follow 2>&1 | stdbuf -oL grep -i whatsapp | stdbuf -oL grep web-auto-reply >> '$LOG_FILE'" > /dev/null 2>&1 &
    LISTENER_PID=$!
    echo "✅ 日志监听器已启动 (PID: $LISTENER_PID)"
    echo "   日志文件: $LOG_FILE"
    echo "   📌 已启用行缓冲模式，确保实时写入"
    
    # 保存 PID 到文件，方便后续管理
    echo $LISTENER_PID > "$(pwd)/.listener.pid"
fi

echo ""
echo "=========================================="
echo "✅ 准备就绪！"
echo "=========================================="
echo ""
echo "🌐 Web 界面将在 http://localhost:7689 启动"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

# 定义清理函数
cleanup() {
    echo ""
    echo "🛑 正在关闭服务..."
    
    # 停止日志监听器
    if [ -f "$(pwd)/.listener.pid" ]; then
        LISTENER_PID=$(cat "$(pwd)/.listener.pid")
        if kill -0 $LISTENER_PID 2>/dev/null; then
            echo "   停止日志监听器 (PID: $LISTENER_PID)..."
            kill $LISTENER_PID 2>/dev/null
            rm -f "$(pwd)/.listener.pid"
        fi
    fi
    
    echo "✅ 服务已停止"
    exit 0
}

# 注册信号处理器
trap cleanup SIGINT SIGTERM

# 设置环境变量，将用户号码传递给 Python 应用
export CURRENT_USER_NUMBER="$USER_NUMBER"
echo "📤 已将用户号码传递给应用: $USER_NUMBER"
echo ""

# 启动应用
python app.py