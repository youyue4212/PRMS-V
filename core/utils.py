import psutil

def get_battery_percentage():
    """
    Returns battery status as a tuple: (percentage:int, charging:bool)
    If no battery is detected, returns (None, None)
    """
    battery = psutil.sensors_battery()
    if battery:
        return int(battery.percent), battery.power_plugged
    else:
        return None, None

