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
    # 启动后台监听进程
    nohup bash -c "openclaw logs --follow 2>&1 | grep -i whatsapp | grep web-auto-reply >> '$LOG_FILE'" > /dev/null 2>&1 &
    LISTENER_PID=$!
    echo "✅ 日志监听器已启动 (PID: $LISTENER_PID)"
    echo "   日志文件: $LOG_FILE"
    
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

# 启动应用
python app.py