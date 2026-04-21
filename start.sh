#!/bin/bash

echo "🚀 启动 ConnClaw Gradio 版本..."
echo ""

# ==========================================
# 信号处理与优雅退出
# ==========================================

# 存储所有子进程 PID
GRADIO_PID=""
LISTENER_PID=""

# 清理函数：优雅退出
cleanup() {
    echo ""
    echo "🛑 收到退出信号，正在清理资源..."
    
    # 停止 Gradio 应用
    if [ -n "$GRADIO_PID" ] && kill -0 $GRADIO_PID 2>/dev/null; then
        echo "   停止 Gradio 应用 (PID: $GRADIO_PID)..."
        kill $GRADIO_PID 2>/dev/null
        wait $GRADIO_PID 2>/dev/null
    fi
    
    # 停止日志监听器（优先使用保存的 PID）
    LISTENER_STOPPED=false
    
    if [ -n "$LISTENER_PID" ] && kill -0 $LISTENER_PID 2>/dev/null; then
        echo "   停止日志监听器 (PID: $LISTENER_PID)..."
        kill $LISTENER_PID 2>/dev/null
        wait $LISTENER_PID 2>/dev/null
        LISTENER_STOPPED=true
    fi
    
    # 如果 PID 变量为空或进程已不存在，尝试从 PID 文件读取
    if [ "$LISTENER_STOPPED" = false ] && [ -f "$(pwd)/.listener.pid" ]; then
        FILE_PID=$(cat "$(pwd)/.listener.pid" 2>/dev/null)
        if [ -n "$FILE_PID" ] && kill -0 $FILE_PID 2>/dev/null; then
            echo "   从 PID 文件停止日志监听器 (PID: $FILE_PID)..."
            kill $FILE_PID 2>/dev/null
            wait $FILE_PID 2>/dev/null
            LISTENER_STOPPED=true
        fi
    fi
    
    # 如果仍未停止，尝试通过进程名查找并停止
    if [ "$LISTENER_STOPPED" = false ]; then
        EXISTING_PIDS=$(pgrep -f "openclaw logs.*follow" || true)
        if [ -n "$EXISTING_PIDS" ]; then
            echo "   通过进程名查找并停止日志监听器..."
            echo "$EXISTING_PIDS" | while read pid; do
                echo "   - 停止进程 $pid..."
                kill $pid 2>/dev/null
            done
            sleep 0.5
            
            # 如果还有进程，强制杀死
            REMAINING_PIDS=$(pgrep -f "openclaw logs.*follow" || true)
            if [ -n "$REMAINING_PIDS" ]; then
                echo "   ⚠️  强制杀死残留的监听进程..."
                echo "$REMAINING_PIDS" | while read pid; do
                    kill -9 $pid 2>/dev/null
                done
            fi
        fi
    fi
    
    # 清理 PID 文件
    rm -f "$(pwd)/.gradio.pid"
    rm -f "$(pwd)/.listener.pid"
    
    echo "✅ 资源清理完成，服务已停止"
    exit 0
}

# 注册信号处理器（捕获 SIGINT, SIGTERM, SIGHUP）
trap cleanup SIGINT SIGTERM SIGHUP EXIT

# ==========================================
# 用户检查
# ==========================================

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

# ==========================================
# Conda 环境加载
# ==========================================

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

# ==========================================
# Python 检查
# ==========================================

if ! command -v python &> /dev/null; then
    echo "❌ 错误: 未找到 Python，请先安装 Python 3.8+"
    exit 1
fi

echo "✅ Python 版本: $(python --version)"
echo ""

# ==========================================
# 用户号码验证（从启动参数获取）
# ==========================================

echo "=========================================="
echo "📱 验证用户号码"
echo "=========================================="

# 检查是否提供了启动参数
if [ -z "$1" ]; then
    echo "❌ 错误: 缺少必需参数"
    echo ""
    echo "使用方法:"
    echo "  ./start.sh <WhatsApp号码>"
    echo ""
    echo "示例:"
    echo "  ./start.sh +8618610290897"
    echo ""
    echo "号码格式要求:"
    echo "  - 必须以 +86 开头"
    echo "  - 总共 13 位数字（+86 + 11位手机号）"
    echo ""
    exit 1
fi

USER_NUMBER="$1"

# 验证号码格式
if [[ ! "$USER_NUMBER" =~ ^\+86[0-9]{11}$ ]]; then
    echo "❌ 号码格式错误: $USER_NUMBER"
    echo ""
    echo "正确的格式应该是:"
    echo "  - 以 +86 开头"
    echo "  - 总共 13 位数字（+86 + 11位手机号）"
    echo ""
    echo "示例:"
    echo "  +8618610290897"
    echo ""
    exit 1
fi

echo "✅ 号码格式验证通过: $USER_NUMBER"
echo ""

# 验证号码是否在允许列表中
VALIDATED=false

# 验证1: 从 openclaw.json 检查
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
        echo "❌ 验证失败: $USER_NUMBER 不在任何允许的联系人列表中"
        if [ -n "$ALLOWED_FROM_STATUS" ]; then
            echo "   channels status allow 列表: $ALLOWED_FROM_STATUS"
        fi
        echo ""
        echo "请检查:"
        echo "  1. 号码是否正确"
        echo "  2. 是否在 openclaw.json 的 allowFrom 列表中"
        echo "  3. WhatsApp channel 是否已正确配置"
        echo ""
        exit 1
    fi
fi

echo ""
echo "✅ 用户号码配置完成: $USER_NUMBER"
echo ""

# ==========================================
# 依赖检查
# ==========================================

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

# ==========================================
# 启动日志监听器（强制重启）
# ==========================================

echo "🔍 启动 WhatsApp 日志监听器..."
LOG_FILE="$(pwd)/whatsapp_messages.log"

# 步骤1: 停止所有已有的日志监听进程
echo "   🛑 检查并停止已有的日志监听进程..."
EXISTING_PIDS=$(pgrep -f "openclaw logs.*follow" || true)

if [ -n "$EXISTING_PIDS" ]; then
    echo "   发现以下已有监听进程:"
    ps aux | grep "openclaw logs.*follow" | grep -v grep
    
    echo ""
    echo "   正在停止这些进程..."
    echo "$EXISTING_PIDS" | while read pid; do
        echo "   - 停止进程 $pid..."
        kill $pid 2>/dev/null
    done
    
    # 等待进程完全停止
    sleep 1
    
    # 如果还有进程未停止，强制杀死
    REMAINING_PIDS=$(pgrep -f "openclaw logs.*follow" || true)
    if [ -n "$REMAINING_PIDS" ]; then
        echo "   ⚠️  仍有进程未停止，强制杀死..."
        echo "$REMAINING_PIDS" | while read pid; do
            echo "   - 强制杀死进程 $pid..."
            kill -9 $pid 2>/dev/null
        done
        sleep 0.5
    fi
    
    echo "   ✅ 已有监听进程已停止"
else
    echo "   ✅ 未发现已有的监听进程"
fi

# 清理旧的 PID 文件
rm -f "$(pwd)/.listener.pid"

# 步骤2: 启动新的监听进程
echo "   🚀 启动新的日志监听进程..."

# 启动后台监听进程（使用 stdbuf 禁用缓冲，确保实时写入）
nohup bash -c "stdbuf -oL -eL openclaw logs --follow 2>&1 | stdbuf -oL grep -i whatsapp >> '$LOG_FILE'" > /dev/null 2>&1 &
LISTENER_PID=$!

# 验证进程是否成功启动
sleep 0.5
if kill -0 $LISTENER_PID 2>/dev/null; then
    echo "✅ 日志监听器已启动 (PID: $LISTENER_PID)"
    echo "   日志文件: $LOG_FILE"
    echo "   📌 已启用行缓冲模式，确保实时写入"
    
    # 保存 PID 到文件，方便后续管理
    echo $LISTENER_PID > "$(pwd)/.listener.pid"
else
    echo "❌ 日志监听器启动失败"
    exit 1
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

# ==========================================
# 设置环境变量并启动应用
# ==========================================

export CURRENT_USER_NUMBER="$USER_NUMBER"
echo "📤 已将用户号码传递给应用: $USER_NUMBER"
echo ""

# 启动 Gradio 应用（前台运行）
python app.py &
GRADIO_PID=$!
echo "✅ Gradio 应用已启动 (PID: $GRADIO_PID)"
echo $GRADIO_PID > "$(pwd)/.gradio.pid"

# 等待 Gradio 应用结束
wait $GRADIO_PID
