// API 基础 URL
const API_BASE_URL = window.location.origin;

// WebSocket 连接
let socket = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;

// 设备状态缓存（用于检测变化）
let deviceStateCache = {};

// 初始化应用
document.addEventListener('DOMContentLoaded', function() {
    console.log('🏠 智能家居控制系统初始化...');
    
    // 初始化 WebSocket 连接
    initWebSocket();
    
    // 加载设备状态
    loadAllDevices();
    
    // 主动轮询：每1秒刷新一次，确保实时同步
    setInterval(function() {
        loadAllDevices();
    }, 1000);
});

// ==================== WebSocket 功能 ====================

function initWebSocket() {
    try {
        // 连接 Socket.IO
        socket = io(API_BASE_URL, {
            transports: ['websocket', 'polling'],
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionAttempts: MAX_RECONNECT_ATTEMPTS
        });
        
        // 连接成功
        socket.on('connect', function() {
            console.log('✅ WebSocket 已连接');
            reconnectAttempts = 0;
            updateConnectionStatus(true);
            // 不弹窗，只更新状态指示器
        });
        
        // 连接状态
        socket.on('connection_status', function(data) {
            console.log('📡 连接状态:', data);
        });
        
        // 接收初始状态
        socket.on('initial_state', function(data) {
            console.log('📥 接收初始状态');
            if (data.devices) {
                // 初始状态不做高亮
                updateDeviceUI(data.devices, { flash: false });
                updateLastUpdateTime();
            }
        });
        
        // 接收设备更新
        socket.on('device_update', function(data) {
            console.log('🔔 设备更新:', data.device_id, data);
            // 将更新以高亮方式呈现（无弹窗，只视觉反馈）
            updateDeviceUI({ [data.device_id]: data.device }, { flash: true });
            updateLastUpdateTime();
        });
        
        // 断开连接
        socket.on('disconnect', function(reason) {
            console.warn('⚠️ WebSocket 断开:', reason);
            updateConnectionStatus(false);
            
            if (reason === 'io server disconnect') {
                socket.connect();
            }
        });
        
        // 重连失败
        socket.on('reconnect_failed', function() {
            console.error('❌ WebSocket 重连失败');
            // 不弹窗，只在控制台记录
        });
        
        // 重连成功
        socket.on('reconnect', function(attemptNumber) {
            console.log('✅ WebSocket 重连成功 (尝试次数: ' + attemptNumber + ')');
            loadAllDevices();
        });
        
    } catch (error) {
        console.error('❌ WebSocket 初始化失败:', error);
        updateConnectionStatus(false);
    }
}

// 请求手动同步
function requestSync(deviceId = null) {
    console.log('🔄 正在刷新数据...');
    
    if (socket && socket.connected) {
        socket.emit('request_sync', { device_id: deviceId });
    } else {
        console.warn('WebSocket 未连接，使用 HTTP 同步');
        fetch(`${API_BASE_URL}/api/sync`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: deviceId })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                console.log('✅ 同步成功:', data.message);
                loadAllDevices();
            }
        })
        .catch(error => {
            console.error('同步失败:', error);
        });
    }
}

// ==================== UI 更新函数 ====================

// 连接状态缓存
let lastConnectionStatus = null;

// 更新连接状态显示（只在状态变化时更新DOM）
function updateConnectionStatus(isConnected) {
    // 状态没变化，不更新DOM
    if (lastConnectionStatus === isConnected) {
        return;
    }
    lastConnectionStatus = isConnected;
    
    const statusBadge = document.getElementById('connection-status');
    
    if (isConnected) {
        statusBadge.innerHTML = '<i class="fas fa-circle"></i> 已连接';
        statusBadge.querySelector('i').style.color = '#27ae60';
    } else {
        statusBadge.innerHTML = '<i class="fas fa-circle"></i> 未连接';
        statusBadge.querySelector('i').style.color = '#e74c3c';
    }
}

// 检查连接并刷新
function checkConnectionAndRefresh() {
    if (!socket || !socket.connected) {
        console.log('🔄 WebSocket 未连接，使用 HTTP 刷新');
        loadAllDevices();
    }
}

// 显示通知
function showNotification(message, isError = false) {
    const notification = document.getElementById('notification');
    notification.textContent = message;
    notification.className = 'notification show' + (isError ? ' error' : '');
    
    setTimeout(() => {
        notification.classList.remove('show');
    }, 3000);
}

// 更新最后更新时间（只在状态变化时调用）
function updateLastUpdateTime() {
    const now = new Date();
    const timeString = now.toLocaleTimeString('zh-CN');
    document.getElementById('last-update').textContent = `最后更新: ${timeString}`;
}

// 加载所有设备状态
async function loadAllDevices() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/devices`);
        const data = await response.json();
        
        if (data.success) {
            let hasAnyChange = false;
            
            // 检测每个设备是否有变化，只更新变化的部分
            for (const deviceId in data.devices) {
                const newState = JSON.stringify(data.devices[deviceId]);
                const oldState = deviceStateCache[deviceId];
                
                // 只有状态真正变化时才更新UI
                if (oldState !== newState) {
                    if (oldState) {
                        // 有旧状态说明是更新，触发高亮
                        console.log('🔔 检测到变化:', deviceId);
                        updateDeviceUI({ [deviceId]: data.devices[deviceId] }, { flash: true });
                        hasAnyChange = true;
                    } else {
                        // 首次加载，不高亮
                        updateDeviceUI({ [deviceId]: data.devices[deviceId] }, { flash: false });
                    }
                    // 更新缓存
                    deviceStateCache[deviceId] = newState;
                }
                // 状态没变化时，什么都不做，保持界面稳定
            }
            
            // 只有真正有状态变化时才更新时间（且只更新一次）
            if (hasAnyChange) {
                updateLastUpdateTime();
            }
            
            updateConnectionStatus(true);
        }
    } catch (error) {
        console.error('加载设备失败:', error);
        updateConnectionStatus(false);
    }
}

// 更新设备 UI
// devices: 对象，opts: { flash: boolean }
function updateDeviceUI(devices, opts = { flash: false }) {
    // 更新空调
    if (devices.air_conditioner) {
        updateAirConditioner(devices.air_conditioner, opts);
    }
    
    // 更新客厅灯
    if (devices.light_living) {
        updateLight('light_living', devices.light_living, opts);
    }
}

// 更新空调 UI
function updateAirConditioner(device, opts = { flash: false }) {
    const card = document.getElementById('air_conditioner');
    const powerIndicator = document.getElementById('ac-power-indicator');
    const status = document.getElementById('ac-status');
    const controls = document.getElementById('ac-controls');
    const tempDisplay = document.getElementById('ac-temp');
    
    if (!card || !powerIndicator || !status || !controls) {
        console.error('空调UI元素未找到');
        return;
    }
    
    // 更新电源指示器
    if (device.is_on) {
        powerIndicator.classList.add('on');
    } else {
        powerIndicator.classList.remove('on');
    }
    
    // 更新状态文字
    if (device.is_on) {
        // 显示中文模式名称
        const modeText = device.mode_display || getModeDisplayText(device.mode);
        status.textContent = modeText;
        status.className = 'device-status on';
    } else {
        status.textContent = '关闭';
        status.className = 'device-status';
    }
    
    // 显示/隐藏控制面板
    if (device.is_on) {
        card.classList.add('active');
        controls.classList.add('active');
        
        // 移除所有模式类，添加当前模式类
        card.classList.remove('mode-cool', 'mode-heat', 'mode-fan', 'mode-off');
        if (device.mode) {
            card.classList.add('mode-' + device.mode);
        }
    } else {
        card.classList.remove('active', 'mode-cool', 'mode-heat', 'mode-fan', 'mode-off');
        controls.classList.remove('active');
    }
    
    // 更新温度显示
    if (tempDisplay) {
        tempDisplay.textContent = device.temperature || 26;
    }
    
    // 更新模式按钮高亮
    document.querySelectorAll('#air_conditioner .mode-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.mode === device.mode) {
            btn.classList.add('active');
        }
    });
    
    // 更新风速按钮高亮
    document.querySelectorAll('#air_conditioner .fan-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.speed === device.fan_speed) {
            btn.classList.add('active');
        }
    });

    // 如果这是来自实时更新，做高亮提示
    if (opts && opts.flash && card) {
        card.classList.add('highlight');
        if (powerIndicator) {
            powerIndicator.classList.add('pulse');
        }
        setTimeout(() => {
            card.classList.remove('highlight');
            if (powerIndicator) {
                powerIndicator.classList.remove('pulse');
            }
        }, 1200);
    }
}

// 获取模式显示文字
function getModeDisplayText(mode) {
    const modeMap = {
        'cool': '制冷',
        'heat': '制热',
        'fan': '送风',
        'off': '停止'
    };
    return modeMap[mode] || mode;
}

// 获取风速显示文字
function getFanSpeedDisplayText(speed) {
    const speedMap = {
        'low': '低速',
        'medium': '中速',
        'high': '高速'
    };
    return speedMap[speed] || speed;
}

// 更新灯光 UI
function updateLight(deviceId, device, opts = { flash: false }) {
    const card = document.getElementById(deviceId);
    const powerIndicator = document.getElementById(`${deviceId.replace(/_/g, '-')}-power-indicator`);
    const status = document.getElementById(`${deviceId.replace(/_/g, '-')}-status`);
    const indicator = document.getElementById(`${deviceId.replace(/_/g, '-')}-indicator`);
    const bar = document.getElementById(`${deviceId.replace(/_/g, '-')}-bar`);
    
    if (!card || !status) {
        console.error(`灯光UI元素未找到: ${deviceId}`);
        return;
    }
    
    // 更新电源指示器
    if (powerIndicator) {
        if (device.is_on) {
            powerIndicator.classList.add('on');
        } else {
            powerIndicator.classList.remove('on');
        }
    }
    
    // 更新状态文字
    status.textContent = device.is_on ? '开启' : '关闭';
    status.className = 'device-status' + (device.is_on ? ' on' : '');
    
    // 更新卡片样式
    if (device.is_on) {
        card.classList.add('active');
    } else {
        card.classList.remove('active');
    }
    
    // 更新状态指示条（使用 status-bar-inner 的 on/off class）
    if (bar) {
        bar.classList.remove('on', 'off');
        if (device.is_on) {
            bar.classList.add('on');
            bar.style.width = '100%';
        } else {
            bar.classList.add('off');
            bar.style.width = '0%';
        }
    }

    // 高亮反馈（实时更新时）
    if (opts && opts.flash && card) {
        card.classList.add('highlight');
        setTimeout(() => card.classList.remove('highlight'), 1000);
    }
}

// ==================== 键盘快捷键 ====================

document.addEventListener('keydown', function(e) {
    // Alt + S: 手动同步
    if (e.altKey && e.key.toLowerCase() === 's') {
        e.preventDefault();
        requestSync();
    }
});

console.log('✅ 智能家居控制系统就绪');
console.log('💡 快捷键: Alt+S (刷新数据)');
