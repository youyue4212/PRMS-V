# Ubuntu虚拟键盘诊断指南

由于诊断脚本在Ubuntu系统中不存在，请按照以下步骤在Ubuntu系统中创建和运行诊断脚本。

## 步骤1：在Ubuntu中创建诊断脚本

在Ubuntu终端中，运行以下命令创建诊断脚本：

```bash
cat > ~/diagnose_keyboard_ubuntu.py << 'PYEOF'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ubuntu虚拟键盘诊断脚本
"""
import subprocess
import time
import os
import sys

def print_header(title):
    print(f"\n{'='*60}")
    print(f"{title}")
    print(f"{'='*60}")

def check_system():
    print_header("系统信息检查")
    print("Python信息:")
    print(f"  版本: {sys.version}")
    print(f"  编码: {sys.getdefaultencoding()}")
    print("\n环境变量:")
    env_vars = ['QT_QPA_PLATFORM', 'QT_IM_MODULE', 'GTK_IM_MODULE', 
                'DISPLAY', 'WAYLAND_DISPLAY', 'NO_AT_BRIDGE', 'LANG']
    for var in env_vars:
        value = os.environ.get(var, '未设置')
        print(f"  {var}: {value}")

def check_onboard():
    print_header("Onboard键盘检查")
    try:
        result = subprocess.run(['which', 'onboard'], 
                               capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            print("? Onboard 已安装")
            try:
                version_result = subprocess.run(['onboard', '--version'], 
                                              capture_output=True, text=True, timeout=2)
                if version_result.returncode == 0:
                    print(f"  版本: {version_result.stdout.strip()}")
            except:
                print("  版本: 未知")
            return True
        else:
            print("? Onboard 未安装")
            print("  建议: sudo apt install onboard")
            return False
    except Exception as e:
        print(f"? 检查失败: {e}")
        return False

def test_onboard_launch():
    print_header("Onboard启动测试")
    print("测试启动Onboard数字键盘布局...")
    try:
        proc = subprocess.Popen(['onboard', '--layout', 'Numpad', '--no-session'],
                               stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE,
                               text=True)
        time.sleep(1)
        if proc.poll() is None:
            print("  ? Onboard 启动成功")
            proc.terminate()
            proc.wait(timeout=1)
            print("  ? 已终止进程")
            return True
        else:
            stdout, stderr = proc.communicate()
            print(f"  ? Onboard 启动失败")
            if stderr:
                print(f"    错误: {stderr.strip()}")
            return False
    except Exception as e:
        print(f"  ? 测试失败: {e}")
        return False

def main():
    print("Ubuntu虚拟键盘诊断工具")
    print("时间: " + time.strftime("%Y-%m-%d %H:%M:%S"))
    # 设置环境变量用于测试
    os.environ["QT_IM_MODULE"] = ""
    os.environ["GTK_IM_MODULE"] = ""
    os.environ["NO_AT_BRIDGE"] = "1"
    if "WAYLAND_DISPLAY" in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "wayland"
        print("检测到Wayland，使用wayland平台")
    else:
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        print("使用X11平台 (xcb)")
    check_system()
    if check_onboard():
        test_onboard_launch()
    print_header("诊断建议")
    print("1. 设置环境变量:")
    print("   export QT_QPA_PLATFORM=xcb")
    print("   export QT_IM_MODULE=\"\"")
    print("   export GTK_IM_MODULE=\"\"")
    print("   export NO_AT_BRIDGE=1")
    print("2. 如果Onboard未安装: sudo apt install onboard")
    print("3. 启动光谱仪程序:")
    print("   cd /path/to/daq_tablet")
    print("   python3 main.py --resizable --keyboard-debug")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n诊断被用户中断")
    except Exception as e:
        print(f"\n\n诊断过程中出现错误: {e}")
PYEOF
```

## 步骤2：给脚本执行权限

```bash
chmod +x ~/diagnose_keyboard_ubuntu.py
```

## 步骤3：运行诊断脚本

```bash
python3 ~/diagnose_keyboard_ubuntu.py
```

## 步骤4：在Ubuntu中修复虚拟键盘问题

### 4.1 首先设置正确的环境变量

在启动光谱仪程序之前，运行以下命令设置环境变量：

```bash
# 设置环境变量
export QT_QPA_PLATFORM=xcb
export QT_IM_MODULE=""
export GTK_IM_MODULE=""
export NO_AT_BRIDGE=1
export DISPLAY=:0

# 设置Python编码
export LANG=en_US.UTF-8
export PYTHONIOENCODING=utf-8
```

### 4.2 检查Onboard键盘是否安装

```bash
# 检查Onboard是否安装
which onboard

# 如果未安装，安装Onboard
sudo apt update
sudo apt install onboard
```

### 4.3 测试Onboard键盘

```bash
# 测试Onboard键盘启动
onboard --layout Numpad --no-session &

# 等待2秒查看是否启动成功
sleep 2

# 检查进程
ps aux | grep onboard

# 关闭测试的Onboard
pkill onboard
```

### 4.4 修复core/ui_base.py文件（如果已在Ubuntu中）

如果已经在Ubuntu中有了项目文件，确保`core/ui_base.py`文件中的`restore_focus`函数正确。该函数应该如下所示：

```python
def restore_focus(self):
    """恢复焦点到当前输入框，确保键盘输入能够被接收"""
    try:
        if self.current_focused_obj is not None:
            # 重新设置焦点到输入框
            self.current_focused_obj.setFocus()
            log_inst.info("Restored focus to input field after keyboard launch")
    except Exception as e:
        log_inst.error(f"Error restoring focus: {e}")
    finally:
        self.current_focused_obj = None
```

**注意：** 不应该有 `return super().eventFilter(obj, event)` 这一行。

### 4.5 启动光谱仪程序

```bash
# 进入项目目录
cd ~/user/daq_tablet

# 设置环境变量
export QT_QPA_PLATFORM=xcb
export QT_IM_MODULE=""
export GTK_IM_MODULE=""
export NO_AT_BRIDGE=1
export DISPLAY=:0

# 启动程序（带键盘调试）
python3 main.py --resizable --keyboard-debug
```

## 步骤5：如果Onboard仍然无法输入，使用软件键盘备选方案

如果Onboard键盘仍然无法输入，可以使用软件键盘备选方案：

```bash
# 设置使用软件键盘的环境变量
export USE_SOFTWARE_KEYBOARD=1

# 启动程序
python3 main.py --resizable
```

软件键盘将显示为程序内置的数字键盘界面。

## 常见问题解决

### 1. Onboard启动后立即退出
- 检查`--no-session`参数是否正确使用
- 检查是否有其他Onboard进程在运行：`pkill onboard`

### 2. 按键无响应
- 确保环境变量`QT_IM_MODULE`和`GTK_IM_MODULE`设置为空
- 检查输入焦点是否正确传递

### 3. 键盘不弹出
- 检查`DISPLAY`环境变量是否正确设置：`echo $DISPLAY`
- 检查Qt平台插件：`export QT_QPA_PLATFORM=xcb`

### 4. 编码问题
- 确保Python文件都有UTF-8编码声明：`# -*- coding: utf-8 -*-`
- 设置正确的语言环境：`export LANG=en_US.UTF-8`

## 快速测试命令

这里是一个快速测试虚拟键盘是否可用的命令：

```bash
# 测试环境变量
echo "QT_QPA_PLATFORM=$QT_QPA_PLATFORM"
echo "QT_IM_MODULE=$QT_IM_MODULE"
echo "DISPLAY=$DISPLAY"

# 测试Onboard启动
timeout 3 onboard --layout Numpad --no-session &
sleep 2
pkill onboard
echo "Onboard测试完成"
```

## 联系支持

如果按照以上步骤仍然无法解决问题，请提供以下信息：
1. 诊断脚本的输出
2. Ubuntu版本：`lsb_release -a`
3. Python版本：`python3 --version`
4. Onboard版本：`onboard --version 2>/dev/null || echo "未安装"`
5. 错误日志：程序启动时的错误信息
