#!/usr/bin/env python3
# 修改ADC_CHANNELS配置的脚本
# 用法: python change_adc_channels.py [value]
# 示例: python change_adc_channels.py 1024
#        python change_adc_channels.py 4096

import sys
from PyQt5.QtCore import QSettings

def change_adc_channels(value):
    """修改ADC_CHANNELS配置值"""
    try:
        # 验证输入值
        new_value = int(value)
        if new_value not in [1024, 4096]:
            print(f'警告: 建议使用1024或4096，当前设置为{new_value}')
        
        # 创建QSettings对象
        s = QSettings("Raysen", "Spectrometer")
        
        # 读取当前值
        current_value = s.value("ADC_CHANNELS", 4096, int)
        
        # 修改值
        s.setValue("ADC_CHANNELS", new_value)
        s.sync()
        
        # 验证修改
        verified_value = s.value("ADC_CHANNELS", 4096, int)
        
        print(f'配置修改成功!')
        print(f'原值: {current_value}')
        print(f'新值: {verified_value}')
        print(f'注意: 需要重启程序才能使更改生效')
        
        return True
        
    except ValueError:
        print(f'错误: 请输入有效的数字，收到: {value}')
        return False
    except Exception as e:
        print(f'错误: {e}')
        return False

def show_current_value():
    """显示当前配置值"""
    s = QSettings("Raysen", "Spectrometer")
    current_value = s.value("ADC_CHANNELS", 4096, int)
    print(f'当前ADC_CHANNELS配置值: {current_value}')
    return current_value

if __name__ == "__main__":
    if len(sys.argv) == 2:
        # 修改配置
        change_adc_channels(sys.argv[1])
    elif len(sys.argv) == 1:
        # 显示当前值
        show_current_value()
        print()
        print('使用方法:')
        print('  python change_adc_channels.py 1024  # 改为1024')
        print('  python change_adc_channels.py 4096  # 改为4096')
    else:
        print('错误: 参数过多')
        print('使用方法: python change_adc_channels.py [value]')
