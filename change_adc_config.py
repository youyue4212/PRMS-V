#!/usr/bin/env python3
# Script to change ADC_CHANNELS configuration
# Usage: python change_adc_config.py [value]
# Example: python change_adc_config.py 1024
#          python change_adc_config.py 4096

import sys
from PyQt5.QtCore import QSettings

def change_adc_channels(value):
    """Change ADC_CHANNELS configuration value"""
    try:
        # Validate input value
        new_value = int(value)
        if new_value not in [1024, 4096]:
            print(f'Warning: Recommended values are 1024 or 4096, setting to {new_value}')
        
        # Create QSettings object
        s = QSettings("Raysen", "Spectrometer")
        
        # Read current value
        current_value = s.value("ADC_CHANNELS", 4096, int)
        
        # Change value
        s.setValue("ADC_CHANNELS", new_value)
        s.sync()
        
        # Verify change
        verified_value = s.value("ADC_CHANNELS", 4096, int)
        
        print(f'Configuration changed successfully!')
        print(f'Old value: {current_value}')
        print(f'New value: {verified_value}')
        print(f'Note: Restart the program for changes to take effect')
        
        return True
        
    except ValueError:
        print(f'Error: Please enter a valid number, received: {value}')
        return False
    except Exception as e:
        print(f'Error: {e}')
        return False

def show_current_value():
    """Show current configuration value"""
    s = QSettings("Raysen", "Spectrometer")
    current_value = s.value("ADC_CHANNELS", 4096, int)
    print(f'Current ADC_CHANNELS configuration value: {current_value}')
    return current_value

if __name__ == "__main__":
    if len(sys.argv) == 2:
        # Change configuration
        change_adc_channels(sys.argv[1])
    elif len(sys.argv) == 1:
        # Show current value
        show_current_value()
        print()
        print('Usage:')
        print('  python change_adc_config.py 1024  # Change to 1024')
        print('  python change_adc_config.py 4096  # Change to 4096')
    else:
        print('Error: Too many arguments')
        print('Usage: python change_adc_config.py [value]')
