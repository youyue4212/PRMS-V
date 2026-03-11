# 光谱仪程序依赖分析报告

## 当前环境已安装的依赖（用户提供）
```
colorama==0.4.6
contourpy==1.3.3
cycler==0.12.1
et_xmlfile==2.0.0
fonttools==4.61.1
kiwisolver==1.4.9
matplotlib==3.10.8
numpy==2.4.2
openpyxl==3.1.5
packaging==26.0
pandas==3.0.1
pillow==12.1.1
psutil==7.2.2
pyparsing==3.3.2
pyqtgraph==0.14.0
pyserial==3.5
python-dateutil==2.9.0.post0
scipy==1.17.1
six==1.17.0
xlrd==2.0.2
xlsxwriter==3.2.9
```

## 程序requirements.txt中的核心依赖
```
PyQt5==5.15.11
pyqtgraph==0.13.7
pyserial==3.5
numpy==2.3.1
pandas==2.3.0
scipy==1.16.0
Flask==2.3.3
Flask-SocketIO==5.3.6
pymongo==4.5.0
openpyxl==3.1.5
python-dateutil==2.9.0.post0
psutil==7.2.1
six==1.17.0
colorama==0.4.6
et_xmlfile==2.0.0
packaging==25.0
```

## 依赖分类分析

### 1. 必需依赖（程序运行必须）
- **PyQt5** - GUI框架 ?
- **pyqtgraph** - 图表绘制 ?  
- **pyserial** - 串口通信 ?
- **numpy** - 数值计算 ?
- **pandas** - 数据处理 ?
- **scipy** - 科学计算 ?
- **Flask, Flask-SocketIO** - WebSocket通信 ?
- **pymongo** - MongoDB数据库连接 ?
- **openpyxl** - Excel文件处理 ?
- **python-dateutil** - 日期时间处理 ?
- **psutil** - 系统监控 ?
- **six** - Python 2/3兼容 ?
- **colorama** - 控制台颜色输出 ?
- **et_xmlfile** - XML文件处理（openpyxl依赖） ?
- **packaging** - 包版本处理 ?

### 2. 可能不需要的依赖（分析结果）

#### **matplotlib相关依赖（程序未使用）**
- `matplotlib==3.10.8` - **可能不需要**，代码搜索未发现使用
- `contourpy==1.3.3` - matplotlib依赖
- `cycler==0.12.1` - matplotlib依赖  
- `fonttools==4.61.1` - matplotlib依赖
- `kiwisolver==1.4.9` - matplotlib依赖
- `pyparsing==3.3.2` - matplotlib依赖
- **理由**：程序使用pyqtgraph进行图表绘制，未发现matplotlib导入

#### **图像处理相关**
- `pillow==12.1.1` - **可能需要**，PyQt5可能用于图像处理

#### **Excel处理相关**
- `xlrd==2.0.2` - **可能需要**，但pandas可能使用openpyxl替代
- `xlsxwriter==3.2.9` - **可能需要**，Excel文件生成

### 3. 版本差异分析

| 依赖包 | 环境版本 | requirements版本 | 建议 |
|--------|----------|------------------|------|
| numpy | 2.4.2 | 2.3.1 | ? 可保留新版 |
| pandas | 3.0.1 | 2.3.0 | ? 可保留新版 |
| scipy | 1.17.1 | 1.16.0 | ? 可保留新版 |
| pyqtgraph | 0.14.0 | 0.13.7 | ? 可保留新版 |
| psutil | 7.2.2 | 7.2.1 | ? 可保留新版 |
| packaging | 26.0 | 25.0 | ? 可保留新版 |

## 清理建议

### 方案A：最小化清理（只移除确认不需要的）
```bash
# 移除matplotlib及其相关依赖
pip uninstall matplotlib contourpy cycler fonttools kiwisolver pyparsing -y

# 可选：移除xlrd（如果确定不使用）
pip uninstall xlrd -y
```

### 方案B：完整清理（重新安装必需依赖）
```bash
# 1. 导出当前环境
pip freeze > current_env.txt

# 2. 备份当前环境（可选）
pip freeze | grep -E "(PyQt5|pyqtgraph|pyserial|numpy|pandas|scipy|Flask|Flask-SocketIO|pymongo|openpyxl|psutil)" > essential_backup.txt

# 3. 移除所有包
pip freeze | xargs pip uninstall -y

# 4. 重新安装必需依赖
pip install -r requirements.txt

# 5. 安装其他可能需要的包
pip install pillow xlsxwriter
```

### 方案C：创建干净的虚拟环境（推荐）
```bash
# 1. 创建新虚拟环境
python3 -m venv clean_env

# 2. 激活虚拟环境
source clean_env/bin/activate  # Linux/Mac
# 或
clean_env\Scripts\activate  # Windows

# 3. 安装必需依赖
pip install -r requirements.txt

# 4. 安装额外有用的包
pip install pillow xlsxwriter

# 5. 测试程序
./start_spectrometer_rpi.sh
```

## 依赖验证测试

创建测试脚本验证每个依赖是否被使用：

```python
# test_dependencies.py
import sys

dependencies = {
    "PyQt5": ["PyQt5.QtCore", "PyQt5.QtWidgets", "PyQt5.QtGui"],
    "pyqtgraph": ["pyqtgraph"],
    "pyserial": ["serial"],
    "numpy": ["numpy"],
    "pandas": ["pandas"],
    "scipy": ["scipy"],
    "Flask": ["flask"],
    "Flask-SocketIO": ["flask_socketio"],
    "pymongo": ["pymongo"],
    "openpyxl": ["openpyxl"],
    "matplotlib": ["matplotlib"],
}

print("=== 依赖使用检查 ===")
for dep, modules in dependencies.items():
    try:
        for module in modules:
            __import__(module)
        print(f"? {dep} - 已安装且可用")
    except ImportError:
        print(f"? {dep} - 未安装")
    except Exception as e:
        print(f"? {dep} - 错误: {e}")

# 检查实际代码中是否导入
print("\n=== 代码导入检查 ===")
import_search = {
    "matplotlib": False,
    "PIL": False,  # pillow
}

for search_term in import_search.keys():
    # 这里可以添加代码搜索逻辑
    print(f"{search_term}: 需要手动检查代码")
```

## 清理后的最小依赖列表

基于程序实际需求，最小依赖列表应为：

```txt
# 最小必需依赖
PyQt5>=5.15.0
pyqtgraph>=0.13.0
pyserial>=3.5
numpy>=2.3.0
pandas>=2.3.0
scipy>=1.16.0
Flask>=2.3.0
Flask-SocketIO>=5.3.0
pymongo>=4.5.0  # 可选，如果使用MongoDB
openpyxl>=3.1.0
python-dateutil>=2.8.0
psutil>=7.2.0
six>=1.16.0
colorama>=0.4.0
et_xmlfile>=2.0.0
packaging>=25.0

# 可选依赖（根据功能需要）
pillow>=12.0.0  # 图像处理
xlsxwriter>=3.2.0  # Excel导出
```

## 执行步骤

1. **备份当前环境**
   ```bash
   pip freeze > backup_requirements.txt
   ```

2. **测试移除matplotlib**
   ```bash
   pip uninstall matplotlib -y
   ./start_spectrometer_rpi.sh
   ```

3. **如果程序正常运行，继续移除相关依赖**
   ```bash
   pip uninstall contourpy cycler fonttools kiwisolver pyparsing -y
   ```

4. **测试xlrd（如果不确定是否使用）**
   ```bash
   # 先注释掉可能的导入，测试程序
   pip uninstall xlrd -y
   ./start_spectrometer_rpi.sh
   ```

5. **创建清理后的requirements文件**
   ```bash
   pip freeze > cleaned_requirements.txt
   ```

## 注意事项

1. **谨慎操作**：如果程序通过其他方式间接使用某些包，移除可能导致问题
2. **测试验证**：每次移除后都要测试程序功能
3. **虚拟环境**：建议在虚拟环境中测试，避免影响系统环境
4. **版本兼容性**：新版依赖可能引入不兼容问题，建议先测试

## 结论

根据代码分析，**matplotlib及其相关依赖**（contourpy, cycler, fonttools, kiwisolver, pyparsing）**很可能是不需要的**，可以安全移除。

其他依赖如pillow、xlrd、xlsxwriter需要根据实际功能需求决定是否保留。建议先移除matplotlib相关包，测试程序功能，再根据实际情况决定是否移除其他包。
