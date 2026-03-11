# 光谱仪程序环境完全清理指南

## 清理目标
1. 清理冗余的脚本和测试文件
2. 清理不必要的Python依赖包
3. 恢复干净的运行环境

## 第一部分：文件清理

### 使用现有的清理脚本
已经创建了 `clean_environment.sh` 脚本，可以自动清理以下内容：

#### 清理内容：
- 冗余的脚本文件（各种fix_*.sh, test_*.sh等）
- 桌面启动器和自动启动文件
- 添加的环境变量（从.bashrc和.profile中移除）
- systemd用户服务
- Python缓存文件

#### 执行步骤：
```bash
# 1. 进入程序目录
cd ~/daq_tablet

# 2. 给脚本执行权限
chmod +x clean_environment.sh

# 3. 执行清理脚本（交互式，会询问确认）
./clean_environment.sh
```

#### 脚本会询问：
1. 是否确认执行清理操作
2. 是否恢复屏幕保护和电源管理设置
3. 是否清理日志文件

#### 清理后保留的核心文件：
- `main.py` - 主程序
- `requirements.txt` - 依赖列表
- `start_spectrometer.sh` - 启动脚本
- `start_spectrometer_rpi.sh` - 树莓派启动脚本
- `setup_ubuntu_autostart.sh` - 自启动设置脚本
- `fix_all_issues_enhanced.sh` - 问题修复脚本
- `fix_bottom_nav_complete.sh` - 图标修复脚本
- `spectrometer.desktop` - 桌面启动器
- `spectrometer.service` - 系统服务文件
- `core/` - 核心代码目录
- `data/` - 数据目录
- `README/` - 文档目录

## 第二部分：Python依赖清理

### 当前已安装的依赖分析
根据用户提供的列表，分析出以下依赖情况：

### 必需依赖（程序运行必须）：
- **PyQt5** - GUI框架
- **pyqtgraph** - 图表绘制  
- **pyserial** - 串口通信
- **numpy** - 数值计算
- **pandas** - 数据处理
- **scipy** - 科学计算
- **Flask, Flask-SocketIO** - WebSocket通信
- **pymongo** - MongoDB数据库连接（如果使用）
- **openpyxl** - Excel文件处理
- **python-dateutil** - 日期时间处理
- **psutil** - 系统监控
- **six** - Python 2/3兼容
- **colorama** - 控制台颜色输出
- **et_xmlfile** - XML文件处理
- **packaging** - 包版本处理

### 可能不需要的依赖：
#### **matplotlib相关依赖（程序未使用）**
- `matplotlib==3.10.8` - 图表库（程序使用pyqtgraph）
- `contourpy==1.3.3` - matplotlib依赖
- `cycler==0.12.1` - matplotlib依赖  
- `fonttools==4.61.1` - matplotlib依赖
- `kiwisolver==1.4.9` - matplotlib依赖
- `pyparsing==3.3.2` - matplotlib依赖

#### **其他可选依赖**
- `pillow==12.1.1` - 图像处理（PyQt5可能使用）
- `xlrd==2.0.2` - Excel读取（pandas可能使用openpyxl替代）
- `xlsxwriter==3.2.9` - Excel文件生成（可能有用）

### 清理方案

#### 方案A：最小化清理（推荐）
只移除确认不需要的matplotlib相关依赖：

```bash
# 备份当前环境
pip freeze > backup_requirements.txt

# 移除matplotlib及其相关依赖
pip uninstall matplotlib contourpy cycler fonttools kiwisolver pyparsing -y

# 可选：测试移除xlrd（如果不确定是否使用）
# pip uninstall xlrd -y

# 测试程序是否正常运行
./start_spectrometer_rpi.sh
```

#### 方案B：完整清理（重新安装）
如果希望完全重新开始：

```bash
# 1. 备份当前环境
pip freeze > backup_requirements.txt
pip freeze | grep -E "(PyQt5|pyqtgraph|pyserial|numpy|pandas|scipy|Flask)" > essential_backup.txt

# 2. 移除所有包（危险操作，确保有备份）
pip freeze | xargs pip uninstall -y

# 3. 重新安装必需依赖
pip install -r requirements.txt

# 4. 安装其他可能需要的包
pip install pillow xlsxwriter

# 5. 测试程序
./start_spectrometer_rpi.sh
```

#### 方案C：使用虚拟环境（最安全）
```bash
# 1. 创建新虚拟环境
python3 -m venv clean_env

# 2. 激活虚拟环境
source clean_env/bin/activate  # Linux/Mac

# 3. 安装必需依赖
pip install -r requirements.txt

# 4. 安装额外有用的包
pip install pillow xlsxwriter

# 5. 测试程序
./start_spectrometer_rpi.sh

# 6. 退出虚拟环境
deactivate
```

### 验证脚本
创建测试脚本验证依赖：

```bash
# test_dependencies.py
cat > test_dependencies.py << 'EOF'
import sys

essential_deps = [
    "PyQt5.QtCore", "PyQt5.QtWidgets", "PyQt5.QtGui",
    "pyqtgraph", "serial", "numpy", "pandas", "scipy",
    "flask", "flask_socketio", "pymongo", "openpyxl",
    "psutil"
]

print("=== 必需依赖检查 ===")
for dep in essential_deps:
    try:
        __import__(dep)
        print(f"? {dep}")
    except ImportError as e:
        print(f"? {dep} - 缺失: {e}")

# 检查可能不需要的依赖
optional_deps = ["matplotlib", "PIL", "xlrd", "xlsxwriter"]
print("\n=== 可选依赖检查 ===")
for dep in optional_deps:
    try:
        __import__(dep)
        print(f"? {dep} - 已安装")
    except ImportError:
        print(f"? {dep} - 未安装")
EOF

python3 test_dependencies.py
```

## 第三部分：综合清理步骤

### 推荐的分步清理流程

#### 步骤1：备份当前状态
```bash
cd ~/daq_tablet

# 备份文件列表
ls -la > file_list_backup.txt

# 备份Python环境
pip freeze > python_env_backup.txt

# 备份重要配置文件
cp ~/.bashrc ~/.bashrc.backup
cp ~/.profile ~/.profile.backup
```

#### 步骤2：清理冗余文件
```bash
# 运行文件清理脚本
./clean_environment.sh

# 或者手动查看要删除的文件
./cleanup_scripts.sh
```

#### 步骤3：清理Python依赖
```bash
# 采用方案A：只移除matplotlib相关
pip uninstall matplotlib contourpy cycler fonttools kiwisolver pyparsing -y

# 测试程序
./start_spectrometer_rpi.sh

# 如果程序正常运行，考虑移除xlrd（可选）
# pip uninstall xlrd -y
# ./start_spectrometer_rpi.sh
```

#### 步骤4：创建清理后的requirements文件
```bash
# 生成清理后的依赖列表
pip freeze > cleaned_requirements.txt

# 查看清理效果
echo "=== 清理前/后对比 ==="
echo "原requirements.txt:"
grep -E "(matplotlib|contourpy|cycler|fonttools|kiwisolver|pyparsing|xlrd)" backup_requirements.txt || echo "未找到相关依赖"
echo ""
echo "清理后:"
grep -E "(matplotlib|contourpy|cycler|fonttools|kiwisolver|pyparsing|xlrd)" cleaned_requirements.txt || echo "相关依赖已清理"
```

#### 步骤5：验证清理效果
```bash
# 运行依赖测试
python3 test_dependencies.py

# 测试程序功能
./start_spectrometer_rpi.sh

# 检查程序日志
tail -f ~/spectrometer.log
```

## 清理后的预期效果

### 文件系统
```
~/daq_tablet/
├── main.py                    # 主程序
├── requirements.txt           # 依赖列表
├── start_spectrometer.sh      # 启动脚本
├── start_spectrometer_rpi.sh  # 树莓派启动脚本
├── setup_ubuntu_autostart.sh  # 自启动设置
├── fix_all_issues_enhanced.sh # 问题修复脚本
├── fix_bottom_nav_complete.sh # 图标修复脚本
├── spectrometer.desktop       # 桌面启动器
├── spectrometer.service       # 系统服务
├── clean_environment.sh       # 清理脚本
├── cleanup_scripts.sh         # 脚本清理工具
├── core/                      # 核心代码
├── data/                      # 数据目录
└── README/                    # 文档
```

### Python环境
```
清理前: ~25个包
清理后: ~15-18个包（移除matplotlib相关6个包）

节省空间: 约100-200MB
```

### 环境变量
- 从`.bashrc`和`.profile`中移除添加的环境变量
- 恢复默认的屏幕保护和电源管理设置
- 删除自动启动配置

## 故障排除

### 如果清理后程序无法启动

#### 检查缺失的依赖
```bash
# 重新安装requirements.txt中的所有依赖
pip install -r requirements.txt

# 检查关键依赖
python3 -c "import PyQt5, pyqtgraph, serial, numpy, pandas, scipy"
```

#### 恢复备份
```bash
# 恢复Python环境
pip install -r backup_requirements.txt

# 恢复配置文件
cp ~/.bashrc.backup ~/.bashrc
cp ~/.profile.backup ~/.profile
source ~/.bashrc
```

#### 检查错误日志
```bash
# 查看程序日志
cat ~/spectrometer.log

# 查看Python错误
cd ~/daq_tablet
python3 main.py --resizable 2>&1 | head -50
```

### 如果误删重要文件
```bash
# 从git恢复（如果有使用git）
git status
git checkout -- 文件名

# 从备份恢复
# 如果有之前的备份文件
```

## 最佳实践建议

### 1. 使用虚拟环境
```bash
# 创建专门的虚拟环境
python3 -m venv spectrometer_env
source spectrometer_env/bin/activate
pip install -r requirements.txt
```

### 2. 定期清理
- 每月检查一次依赖
- 删除不必要的日志文件
- 清理Python缓存

### 3. 版本控制
- 使用git管理代码
- 保持requirements.txt更新
- 记录重要的配置更改

### 4. 文档记录
- 记录所有环境更改
- 保存清理报告
- 更新README文件

## 总结

通过执行本指南，您可以：

1. **清理冗余文件**：移除50+个测试和调试文件
2. **优化Python环境**：移除不必要的matplotlib相关依赖（约6个包）
3. **恢复干净配置**：清理环境变量和自动启动设置
4. **保持核心功能**：确保程序正常运行

**建议操作顺序**：
1. 先备份当前环境
2. 运行`clean_environment.sh`清理文件
3. 使用方案A清理Python依赖
4. 测试程序功能
5. 如有问题，参考故障排除部分

清理后，您的光谱仪程序环境将更加整洁，运行效率更高，便于维护和问题排查。
