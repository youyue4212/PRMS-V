
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

def get_overview_svg():
    """SVG for overview icon (bar chart)"""
    return """
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="4" y="14" width="4" height="7" rx="1" fill="currentColor"/>
        <rect x="10" y="9" width="4" height="12" rx="1" fill="currentColor"/>
        <rect x="16" y="4" width="4" height="17" rx="1" fill="currentColor"/>
    </svg>
    """

def get_spectrum_svg():
    """SVG for spectrum icon (line chart)"""
    return """
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M3 17l4-4 4 4 6-8 4 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
        <circle cx="3" cy="17" r="1.5" fill="currentColor"/>
        <circle cx="7" cy="13" r="1.5" fill="currentColor"/>
        <circle cx="11" cy="17" r="1.5" fill="currentColor"/>
        <circle cx="17" cy="9" r="1.5" fill="currentColor"/>
        <circle cx="21" cy="13" r="1.5" fill="currentColor"/>
    </svg>
    """

def get_clients_svg():
    """SVG for clients icon (users)"""
    return """
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="9" cy="7" r="3.5" fill="currentColor"/>
        <path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/>
        <circle cx="17" cy="7" r="2.5" fill="currentColor" opacity="0.6"/>
        <path d="M15 19c0-2.2 1.8-4 4-4s4 1.8 4 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none" opacity="0.6"/>
    </svg>
    """

def get_alarm_log_svg():
    """SVG for alarm log icon (bell)"""
    return """
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M12 3c-1.7 0-3 1.3-3 3v5c0 1.1-.4 2.1-1.2 2.8l-1.8 1.7c-.3.3-.5.7-.5 1.1 0 .8.7 1.4 1.5 1.4h11c.8 0 1.5-.6 1.5-1.4 0-.4-.2-.8-.5-1.1l-1.8-1.7c-.8-.7-1.2-1.7-1.2-2.8V6c0-1.7-1.3-3-3-3z" fill="currentColor"/>
        <path d="M10 19c0 1.1.9 2 2 2s2-.9 2-2" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/>
        <circle cx="18" cy="6" r="3" fill="#ff4444"/>
        <text x="18" y="8" text-anchor="middle" font-size="6" fill="white" font-weight="bold">!</text>
    </svg>
    """

def get_settings_svg():
    """SVG for settings icon (gear)"""
    return """
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M12 8c-2.2 0-4 1.8-4 4s1.8 4 4 4 4-1.8 4-4-1.8-4-4-4z" fill="currentColor"/>
        <path d="M19.4 13c.1-.3.1-.7.1-1s0-.7-.1-1l2.1-1.6c.2-.2.3-.5.2-.7l-2-3.5c-.1-.3-.4-.4-.7-.3l-2.5 1c-.5-.4-1.1-.7-1.7-1l-.4-2.6c0-.3-.3-.5-.6-.5h-4c-.3 0-.6.2-.6.5l-.4 2.6c-.6.2-1.2.6-1.7 1l-2.5-1c-.3-.1-.6 0-.7.3l-2 3.5c-.1.2 0 .5.2.7l2.1 1.6c-.1.3-.1.7-.1 1s0 .7.1 1l-2.1 1.6c-.2.2-.3.5-.2.7l2 3.5c.1.3.4.4.7.3l2.5-1c.5.4 1.1.7 1.7 1l.4 2.6c0 .3.3.5.6.5h4c.3 0 .6-.2.6-.5l.4-2.6c.6-.2 1.2-.6 1.7-1l2.5 1c.3.1.6 0 .7-.3l2-3.5c.1-.2 0-.5-.2-.7L19.4 13z" stroke="currentColor" stroke-width="1.5" fill="none"/>
    </svg>
    """

def get_occupancy_active_svg():
    """SVG for active occupancy (walking person in green/blue)"""
    return """
    <svg width="80" height="80" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="12" cy="12" r="11" fill="#2196F3" fill-opacity="0.2"/>
        <circle cx="12" cy="12" r="9" fill="#2196F3" fill-opacity="0.4"/>
        <!-- Head -->
        <circle cx="13" cy="4.5" r="1.5" fill="#2196F3"/>
        <!-- Body & Limbs -->
        <path d="M13 6.5c-.6 0-1.2.3-1.5.8l-2.2 3c-.3.4-.3.9-.1 1.3l1.8 3.4V20c0 .6.4 1 1 1s1-.4 1-1v-4.5l-1.4-2.7 1.4-1.9 1.5 2.2c.2.3.6.5 1 .5h1.5c.6 0 1-.4 1-1s-.4-1-1-1h-1l-1.8-2.6V8c0-.8-.7-1.5-1.5-1.5z" fill="#2196F3"/>
    </svg>
    """

def get_occupancy_inactive_svg():
    """SVG for inactive occupancy (standing person in grey)"""
    return """
    <svg width="80" height="80" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="12" cy="12" r="11" fill="#555555" fill-opacity="0.2"/>
        <!-- Head -->
        <circle cx="12" cy="5" r="2" fill="#aaaaaa"/>
        <!-- Body & Limbs -->
        <path d="M12 8c-1.1 0-2 .9-2 2v4c0 .6.4 1 1 1h2c.6 0 1-.4 1-1v-4c0-1.1-.9-2-2-2zM10.5 16v4c0 .6.4 1 1 1s1-.4 1-1v-4h-2z" fill="#aaaaaa"/>
    </svg>
    """

def get_occupancy_flashing_svg():
    """SVG for flashing occupancy (walking person with motion lines)"""
    return """
    <svg width="80" height="80" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="12" cy="12" r="11" fill="#2196F3" fill-opacity="0.3"/>
        <circle cx="12" cy="12" r="10" fill="#2196F3" fill-opacity="0.6"/>
        <!-- Head -->
        <circle cx="13" cy="4.5" r="1.5" fill="#2196F3"/>
        <!-- Body & Limbs -->
        <path d="M13 6.5c-.6 0-1.2.3-1.5.8l-2.2 3c-.3.4-.3.9-.1 1.3l1.8 3.4V20c0 .6.4 1 1 1s1-.4 1-1v-4.5l-1.4-2.7 1.4-1.9 1.5 2.2c.2.3.6.5 1 .5h1.5c.6 0 1-.4 1-1s-.4-1-1-1h-1l-1.8-2.6V8c0-.8-.7-1.5-1.5-1.5z" fill="#2196F3"/>
        <!-- Motion lines -->
        <path d="M4 8h2M3 12h3M4 16h2" stroke="#2196F3" stroke-width="1.5" stroke-linecap="round"/>
    </svg>
    """

def get_lock_svg():
    """SVG for lock icon (padlock)"""
    return """
    <svg width="80" height="80" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="12" cy="12" r="11" fill="#ff9800" fill-opacity="0.15"/>
        <rect x="6" y="10" width="12" height="10" rx="2" stroke="#ff9800" stroke-width="2" fill="none"/>
        <path d="M9 10V7a3 3 0 0 1 6 0v3" stroke="#ff9800" stroke-width="2" stroke-linecap="round" fill="none"/>
        <circle cx="12" cy="14" r="1.5" fill="#ff9800"/>
        <line x1="12" y1="15.5" x2="12" y2="17.5" stroke="#ff9800" stroke-width="1.5" stroke-linecap="round"/>
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
    elif tag == 'occupancy_active':
        svg=get_occupancy_active_svg().encode()
    elif tag == 'occupancy_inactive':
        svg=get_occupancy_inactive_svg().encode()
    elif tag == 'occupancy_flashing':
        svg=get_occupancy_flashing_svg().encode()
    elif tag == 'overview':
        svg=get_overview_svg().encode()
    elif tag == 'spectrum':
        svg=get_spectrum_svg().encode()
    elif tag == 'clients':
        svg=get_clients_svg().encode()
    elif tag == 'alarm_log':
        svg=get_alarm_log_svg().encode()
    elif tag == 'settings':
        svg=get_settings_svg().encode()
    elif tag == 'lock':
        svg=get_lock_svg().encode()
    return svg
