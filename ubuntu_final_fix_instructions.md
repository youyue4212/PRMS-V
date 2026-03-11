# Ubuntu系统虚拟键盘最终修复指南

根据您的测试，`core/ui_base.py`已经修复了`--no-session`参数问题。现在需要在Ubuntu系统中创建启动脚本和进行最终测试。

## 步骤1：在Ubuntu中创建修复后的启动脚本

在Ubuntu终端中，执行以下命令创建启动脚本：

```bash
cd ~/user/daq_tablet

cat > start_spectrometer_fixed.sh << 'EOF'
#!/bin/bash
# 光谱仪启动脚本 - 修复虚拟键盘问题

echo "========================================"
echo "光谱仪程序启动 (虚拟键盘修复版)"
echo "========================================"

# 设置正确的环境变量
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

# 虚拟键盘修复环境变量
export QT_QPA_PLATFORM=xcb
export QT_IM_MODULE=""
export GTK_IM_MODULE=""
export NO_AT_BRIDGE=1
export DISPLAY=:0

# 优化Qt环境
export QT_AUTO_SCREEN_SCALE_FACTOR=1
export QT_SCALE_FACTOR=1.0
export QT_FONT_DPI=96

echo "环境配置:"
echo "  显示服务器: $QT_QPA_PLATFORM"
echo "  输入法模块: QT=$QT_IM_MODULE, GTK=$GTK_IM_MODULE"
echo "  编码设置: LANG=$LANG, PYTHONIOENCODING=$PYTHONIOENCODING"
echo "  显示: $DISPLAY"

# 检查虚拟键盘
echo ""
echo "检查虚拟键盘..."
if command -v onboard >/dev/null 2>&1; then
    echo "? onboard 已安装"
    # 测试启动
    timeout 2 onboard --version >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "? onboard 可正常启动"
    else
        echo "? onboard 启动测试失败"
    fi
else
    echo "? onboard 未安装"
    echo "  可选安装: sudo apt install onboard"
fi

# 检查Python环境
echo ""
echo "检查Python环境..."
python3 -c "import sys; print(f'  Python版本: {sys.version}'); print(f'  系统编码: {sys.getdefaultencoding()}')" 2>/dev/null || echo "  ? Python检查失败"

echo ""
echo "工作目录: $(pwd)"

# 检查核心文件
echo ""
echo "检查核心文件..."
if [ -f "main.py" ]; then
    echo "? main.py 存在"
    
    # 检查编码
    if head -n 5 main.py | grep -q "coding: utf-8"; then
        echo "? main.py 有UTF-8编码声明"
    else
        echo "? main.py 缺少UTF-8编码声明"
    fi
else
    echo "? main.py 不存在"
    exit 1
fi

if [ -f "core/ui_base.py" ]; then
    echo "? core/ui_base.py 存在"
    
    # 检查是否已修复--no-session参数
    if grep -q "onboard.*--no-session" core/ui_base.py; then
        echo "? core/ui_base.py 仍然包含--no-session参数，需要修复"
    else
        echo "? core/ui_base.py 已修复（无--no-session参数）"
    fi
else
    echo "? core/ui_base.py 不存在"
fi

# 启动程序
echo ""
echo "启动光谱仪程序..."
echo "使用环境变量: QT_QPA_PLATFORM=$QT_QPA_PLATFORM, QT_IM_MODULE=$QT_IM_MODULE"

# 启动程序（带键盘调试）
python3 main.py --resizable --keyboard-debug

exit_code=$?

echo ""
echo "========================================"
if [ $exit_code -eq 0 ]; then
    echo "程序正常退出"
else
    echo "程序异常退出，代码: $exit_code"
    echo "建议:"
    echo "  1. 检查日志文件: tail -n 50 logs/*.log 2>/dev/null"
    echo "  2. 运行简单诊断: python3 diagnose_keyboard_simple.py"
fi
echo "========================================"
EOF

chmod +x start_spectrometer_fixed.sh
```

## 步骤2：创建简单诊断脚本

```bash
cat > diagnose_keyboard_simple.py << 'EOF'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单虚拟键盘诊断脚本
"""
import subprocess
import time
import os
import sys

def main():
    print("=== 虚拟键盘简单诊断 ===")
    
    # 检查Onboard
    print("1. 检查Onboard键盘...")
    try:
        result = subprocess.run(['which', 'onboard'], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            print("   ? Onboard 已安装")
            
            # 测试启动
            print("   测试启动...")
            proc = subprocess.Popen(['onboard', '--layout', 'Numpad'],
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE,
                                   text=True)
            time.sleep(1.5)
            if proc.poll() is None:
                print("    ? Onboard 启动成功")
                proc.terminate()
                proc.wait(timeout=1)
            else:
                stdout, stderr = proc.communicate()
                print("    ? Onboard 启动失败")
                if stderr:
                    print(f"       错误: {stderr.strip()}")
        else:
            print("   ? Onboard 未安装")
            print("     安装命令: sudo apt install onboard")
    except Exception as e:
        print(f"   ? 检查失败: {e}")
    
    # 检查环境变量
    print("\n2. 检查环境变量...")
    env_vars = ['QT_QPA_PLATFORM', 'QT_IM_MODULE', 'GTK_IM_MODULE', 'DISPLAY']
    for var in env_vars:
        value = os.environ.get(var, '未设置')
        print(f"   {var}: {value}")
    
    # 检查ui_base.py
    print("\n3. 检查core/ui_base.py修复情况...")
    try:
        with open('core/ui_base.py', 'r', encoding='utf-8') as f:
            content = f.read()
            if '--no-session' in content:
                print("   ? 发现--no-session参数，需要修复")
            else:
                print("   ? 未发现--no-session参数，已修复")
    except Exception as e:
        print(f"   ? 无法检查core/ui_base.py: {e}")
    
    print("\n=== 诊断完成 ===")
    print("建议:")
    print("  1. 设置环境变量:")
    print("     export QT_QPA_PLATFORM=xcb")
    print("     export QT_IM_MODULE=\"\"")
    print("     export GTK_IM_MODULE=\"\"")
    print("     export NO_AT_BRIDGE=1")
    print("  2. 使用修复后的启动脚本: ./start_spectrometer_fixed.sh")

if __name__ == "__main__":
    main()
EOF

chmod +x diagnose_keyboard_simple.py
```

## 步骤3：运行诊断脚本

```bash
python3 diagnose_keyboard_simple.py
```

## 步骤4：使用修复后的脚本启动程序

```bash
# 确保在项目目录
cd ~/user/daq_tablet

# 运行修复后的启动脚本
./start_spectrometer_fixed.sh
```

## 步骤5：测试虚拟键盘功能

程序启动后，请测试以下功能：

1. **点击输入框**：Onboard虚拟键盘应该自动弹出
2. **键盘输入**：在Onboard上点击数字，应该能输入到输入框中
3. **焦点恢复**：关闭Onboard后，焦点应该能正确返回输入框

## 如果Onboard仍然无法输入

如果Onboard可以启动但无法输入，请尝试以下方法：

### 方法1：手动设置环境变量后启动

```bash
cd ~/user/daq_tablet

# 设置环境变量
export QT_QPA_PLATFORM=xcb
export QT_IM_MODULE=""
export GTK_IM_MODULE=""
export NO_AT_BRIDGE=1
export DISPLAY=:0
export LANG=en_US.UTF-8

# 启动程序（带键盘调试）
python3 main.py --resizable --keyboard-debug
```

### 方法2：使用软件键盘备选方案

如果Onboard仍然无法工作，可以使用软件键盘备选方案：

```bash
cd ~/user/daq_tablet
export USE_SOFTWARE_KEYBOARD=1
python3 main.py --resizable
```

## 验证修复

从之前的测试中，我们已经确认：
1. `core/ui_base.py`中已经移除了`--no-session`参数
2. Onboard可以正常启动（不再报参数错误）

现在需要验证的是：
1. Onboard启动后是否能正确接收输入
2. 焦点管理是否正常工作

## 常见问题解决

### 1. Onboard启动后立即退出
- 检查是否有其他Onboard进程在运行：`pkill onboard`
- 尝试使用简单命令启动：`onboard --layout Numpad`

### 2. 按键无响应
- 确保环境变量正确设置
- 检查输入焦点：点击输入框后，Onboard应该弹出

### 3. 程序启动失败
- 检查Python依赖：`pip install -r requirements.txt`
- 检查文件权限：`chmod +x *.sh`

## 最终验证命令

运行以下命令进行最终验证：

```bash
cd ~/user/daq_tablet

# 验证修复
echo "1. 验证core/ui_base.py修复..."
grep -n "onboard.*--no-session" core/ui_base.py
echo "   （应该没有输出）"

echo "2. 测试Onboard启动..."
timeout 3 onboard --layout Numpad &
sleep 2
pkill onboard
echo "   Onboard测试完成"

echo "3. 设置环境变量..."
export QT_QPA_PLATFORM=xcb
export QT_IM_MODULE=""
export GTK_IM_MODULE=""
export NO_AT_BRIDGE=1

echo "4. 启动程序测试..."
echo "   请观察Onboard是否能正常弹出并接收输入"
python3 main.py --resizable --keyboard-debug
```

如果按照以上步骤仍然无法解决问题，请提供以下信息：
1. Ubuntu版本：`lsb_release -a`
2. Onboard版本：`onboard --version 2>/dev/null || echo "未安装"`
3. 错误信息：程序启动时的完整错误信息
4. 环境变量：`env | grep -E "QT|GTK|DISPLAY"`
