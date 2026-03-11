
def get_connected_svg():
    """SVG for connected state (link icon)"""
    return """
    <svg width="80" height="80" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M8 8c-2.248 0-4 1.752-4 4s1.752 4 4 4h2a1 1 0 1 1 0 2H8c-3.352 0-6-2.648-6-6s2.648-6 6-6h2a1 1 0 1 1 0 2H8zm5-1a1 1 0 0 1 1-1h2c3.352 0 6 2.648 6 6s-2.648 6-6 6h-2a1 1 0 1 1 0-2h2c2.248 0 4-1.752 4-4s-1.752-4-4-4h-2a1 1 0 0 1-1-1zm-6 5a1 1 0 0 1 1-1h8a1 1 0 1 1 0 2H8a1 1 0 0 1-1-1z" fill="#27ae60"/>
    </svg>
    """

def get_disconnected_svg():
    """SVG for disconnected state (link slash icon)"""
    return """
    <svg width="80" height="80" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M8 8c-2.248 0-4 1.752-4 4s1.752 4 4 4h2a1 1 0 1 1 0 2H8c-3.352 0-6-2.648-6-6s2.648-6 6-6h2a1 1 0 1 1 0 2H8zm5-1a1 1 0 0 1 1-1h2c3.352 0 6 2.648 6 6s-2.648 6-6 6h-2a1 1 0 1 1 0-2h2c2.248 0 4-1.752 4-4s-1.752-4-4-4h-2a1 1 0 0 1-1-1zm-6 5a1 1 0 0 1 1-1h8a1 1 0 1 1 0 2H8a1 1 0 0 1-1-1z" fill="#e74c3c"/>
        <line x1="3" y1="3" x2="21" y2="21" stroke="#e74c3c" stroke-width="2" stroke-linecap="round"/>
    </svg>
    """



def get_alarm_active_svg():
    """SVG for active alarm state (red warning triangle with exclamation mark) - Optimized version"""
    return """
    <svg width="80" height="80" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <!-- Outer glow effect for better visibility -->
        <circle cx="12" cy="12" r="11" fill="#ff4444" fill-opacity="0.2"/>
        <!-- Main warning triangle -->
        <path d="M12 2L1 21h22L12 2z" fill="#ff4444"/>
        <!-- Inner highlight for 3D effect -->
        <path d="M12 4L3.5 19h17L12 4z" fill="#ff6666" fill-opacity="0.7"/>
        <!-- Exclamation mark -->
        <rect x="11" y="7" width="2" height="8" rx="1" fill="#ffffff"/>
        <circle cx="12" cy="18" r="1.5" fill="#ffffff"/>
        <!-- Pulsing animation indicator -->
        <circle cx="12" cy="12" r="10" fill="none" stroke="#ffffff" stroke-width="1" stroke-opacity="0.5" stroke-dasharray="2,2"/>
    </svg>
    """

def get_alarm_inactive_svg():
    """SVG for inactive alarm state (green checkmark in circle) - Optimized version"""
    return """
    <svg width="80" height="80" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <!-- Outer circle with subtle gradient -->
        <defs>
            <linearGradient id="gradient_inactive" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#4caf50" stop-opacity="0.9"/>
                <stop offset="100%" stop-color="#2e7d32" stop-opacity="0.9"/>
            </linearGradient>
        </defs>
        <circle cx="12" cy="12" r="11" fill="url(#gradient_inactive)" stroke="#ffffff" stroke-width="1"/>
        <!-- Checkmark with smooth curve -->
        <path d="M7 12l3.5 3.5L17 9" stroke="#ffffff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
        <!-- Inner circle for depth -->
        <circle cx="12" cy="12" r="8" fill="none" stroke="#ffffff" stroke-width="0.5" stroke-opacity="0.3"/>
    </svg>
    """

def get_alarm_flashing_svg():
    """SVG for flashing alarm state (pulsing red alert icon) - Optimized version"""
    return """
    <svg width="80" height="80" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <!-- Outer pulsing circle -->
        <circle cx="12" cy="12" r="11" fill="#ff4444" fill-opacity="0.3">
            <animate attributeName="r" values="11;12;11" dur="1s" repeatCount="indefinite"/>
            <animate attributeName="fill-opacity" values="0.3;0.5;0.3" dur="1s" repeatCount="indefinite"/>
        </circle>
        <!-- Middle pulsing circle -->
        <circle cx="12" cy="12" r="9" fill="#ff4444" fill-opacity="0.6">
            <animate attributeName="r" values="9;10;9" dur="1s" repeatCount="indefinite" begin="0.2s"/>
            <animate attributeName="fill-opacity" values="0.6;0.8;0.6" dur="1s" repeatCount="indefinite" begin="0.2s"/>
        </circle>
        <!-- Main alert icon -->
        <path d="M12 2L1 21h22L12 2z" fill="#ff0000"/>
        <!-- Inner highlight -->
        <path d="M12 4L3.5 19h17L12 4z" fill="#ff6666" fill-opacity="0.7"/>
        <!-- Exclamation mark -->
        <rect x="11" y="7" width="2" height="8" rx="1" fill="#ffffff"/>
        <circle cx="12" cy="18" r="1.5" fill="#ffffff"/>
        <!-- Inner circle for contrast -->
        <circle cx="12" cy="12" r="7" fill="none" stroke="#ffffff" stroke-width="0.5" stroke-opacity="0.5"/>
    </svg>
    """

def get_icon_svg(tag, w=14,h=14):
    svg = None
    if tag =='disconnected':
        svg=get_disconnected_svg().encode()
    elif tag =='connected':
        svg=get_connected_svg().encode()
    elif tag == 'alarm_active':
        svg=get_alarm_active_svg().encode()
    elif tag == 'alarm_inactive':
        svg=get_alarm_inactive_svg().encode()
    elif tag == 'alarm_flashing':
        svg=get_alarm_flashing_svg().encode()
    return svg
