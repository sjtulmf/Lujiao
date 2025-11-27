from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from datetime import datetime
import requests
import threading
import time
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'smart-home-secret-key-2024'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ==================== Home Assistant 配置 ====================
HOME_ASSISTANT_URL = "http://123.60.38.166:8123"
HOME_ASSISTANT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJhNzA4MzU1MWIxZGM0ODUzYmNmYjhiM2U3Y2NhMjM1OSIsImlhdCI6MTc2MzYyNzg2OCwiZXhwIjoyMDc4OTg3ODY4fQ.DOE7UIE6MBDNDPLVMUYx0nR8R0eVtDfbeMWRl_OoAyM"
HOME_ASSISTANT_HEADERS = {
    "Authorization": f"Bearer {HOME_ASSISTANT_TOKEN}",
    "Content-Type": "application/json"
}

# ==================== 模式和风速映射 ====================
# 空调模式映射 (HA状态 -> 内部英文)
AC_MODE_MAP = {
    "制冷": "cool",
    "制热": "heat", 
    "送风": "fan",
    "停止": "off",
    # 可能的英文变体
    "cool": "cool",
    "heat": "heat",
    "fan": "fan",
    "fan_only": "fan",
    "off": "off",
    "auto": "fan",  # 自动模式当作送风
    "dry": "fan",   # 除湿模式当作送风
}
# 内部英文 -> 中文显示
AC_MODE_DISPLAY = {
    "cool": "制冷",
    "heat": "制热",
    "fan": "送风",
    "off": "停止"
}
AC_MODE_REVERSE = {v: k for k, v in AC_MODE_DISPLAY.items()}

# 风速映射 (HA状态 -> 前端显示)
FAN_SPEED_MAP = {
    "低速": "low",
    "中速": "medium",
    "高速": "high"
}
FAN_SPEED_REVERSE = {v: k for k, v in FAN_SPEED_MAP.items()}

# ==================== 设备状态存储 ====================
devices = {
    "air_conditioner": {
        "id": "ac_001",
        "name": "客厅空调",
        "type": "air_conditioner",
        "is_on": False,
        "temperature": 26,
        "mode": "off",           # 内部使用英文: cool, heat, fan, off
        "mode_display": "停止",   # 显示用中文
        "fan_speed": "medium",   # 内部使用英文: low, medium, high
        "fan_speed_display": "中速",  # 显示用中文
        "last_updated": None,
        "ha_entity": "sensor.bedroom_ac_status",
        "read_only": True
    },
    "light_living": {
        "id": "light_001",
        "name": "客厅灯",
        "type": "light",
        "is_on": False,
        "last_updated": None,
        "ha_entity": "light.living_room_bulb",
        "read_only": True
    }
}

# ==================== Home Assistant 只读函数 ====================

def get_ha_state(entity_id):
    """从 Home Assistant 获取设备状态（只读 - 仅使用 GET）"""
    try:
        url = f"{HOME_ASSISTANT_URL}/api/states/{entity_id}"
        response = requests.get(url, headers=HOME_ASSISTANT_HEADERS, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            print("=" * 70)
            print(f"📥 从 Home Assistant 获取数据 [{entity_id}]")
            print("-" * 70)
            print(f"完整响应数据:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print("=" * 70)
            return data
        else:
            print(f"❌ 获取 HA 状态失败: {response.status_code}")
            print(f"   响应内容: {response.text}")
            return None
    except Exception as e:
        print(f"❌ 连接 Home Assistant 失败: {e}")
        return None

def sync_from_ha(device_id):
    """从 Home Assistant 同步设备状态到本地（只读）"""
    if device_id not in devices or "ha_entity" not in devices[device_id]:
        return False
    
    ha_entity = devices[device_id]["ha_entity"]
    ha_data = get_ha_state(ha_entity)
    
    if not ha_data:
        return False
    
    try:
        state = ha_data.get("state", "")
        attributes = ha_data.get("attributes", {})
        
        print(f"\n🔄 解析设备数据 [{device_id}]")
        print("-" * 70)
        
        if device_id == "air_conditioner":
            # 处理空调数据
            old_state = {
                "is_on": devices[device_id]["is_on"],
                "mode": devices[device_id]["mode"],
                "mode_display": devices[device_id]["mode_display"],
                "temperature": devices[device_id]["temperature"],
                "fan_speed": devices[device_id]["fan_speed"],
                "fan_speed_display": devices[device_id]["fan_speed_display"]
            }
            
            # 解析模式 - HA 可能返回中文或英文
            mode_raw = state.lower() if state else "off"
            
            # 统一映射到内部英文值
            if mode_raw in AC_MODE_MAP:
                mode_en = AC_MODE_MAP[mode_raw]
            elif state in AC_MODE_MAP:  # 尝试原始大小写
                mode_en = AC_MODE_MAP[state]
            else:
                # 未知值，打印日志并回退到 off
                print(f"⚠️ 未知的空调模式: '{state}'，回退到 off")
                mode_en = "off"
            
            # 获取中文显示名称
            mode_display = AC_MODE_DISPLAY.get(mode_en, state)

            devices[device_id]["is_on"] = mode_en != "off"
            devices[device_id]["mode"] = mode_en
            devices[device_id]["mode_display"] = mode_display
            
            # 解析温度
            devices[device_id]["temperature"] = int(attributes.get("temperature", 26))
            
            # 解析风速 - HA 可能返回中文（"低速","中速","高速"）或英文（"low","medium","high"）
            fan_raw = attributes.get("fan_mode", attributes.get("fan_speed", "中速"))
            if fan_raw in FAN_SPEED_MAP:
                fan_en = FAN_SPEED_MAP.get(fan_raw, "medium")
                fan_display = fan_raw
            elif fan_raw in FAN_SPEED_REVERSE:
                fan_en = fan_raw
                fan_display = FAN_SPEED_REVERSE.get(fan_raw, fan_raw)
            else:
                fan_en = "medium"
                fan_display = fan_raw

            devices[device_id]["fan_speed"] = fan_en
            devices[device_id]["fan_speed_display"] = fan_display
            
            new_state = {
                "is_on": devices[device_id]["is_on"],
                "mode": devices[device_id]["mode"],
                "mode_display": devices[device_id]["mode_display"],
                "temperature": devices[device_id]["temperature"],
                "fan_speed": devices[device_id]["fan_speed"],
                "fan_speed_display": devices[device_id]["fan_speed_display"]
            }
            
            print(f"📊 HA 原始状态: state='{state}' (模式)")
            print(f"📊 HA 属性数据:")
            print(f"   - temperature: {attributes.get('temperature', 'N/A')}")
            print(f"   - fan_mode: {attributes.get('fan_mode', 'N/A')} (风速)")
            print(f"   - friendly_name: {attributes.get('friendly_name', 'N/A')}")
            print(f"\n🔀 状态变化对比:")
            print(f"   旧状态: {json.dumps(old_state, ensure_ascii=False)}")
            print(f"   新状态: {json.dumps(new_state, ensure_ascii=False)}")
            
            if old_state != new_state:
                print(f"   ⚠️  检测到状态变化！")
                
        elif device_id == "light_living":
            # 处理灯泡数据
            old_state = {
                "is_on": devices[device_id]["is_on"]
            }
            
            # 解析状态 - state 字段是 "light_on" 或 "light_off"
            devices[device_id]["is_on"] = state == "light_on"
            
            new_state = {
                "is_on": devices[device_id]["is_on"]
            }
            
            print(f"📊 HA 原始状态: state='{state}'")
            print(f"📊 解析结果: is_on={devices[device_id]['is_on']}")
            print(f"\n🔀 状态变化对比:")
            print(f"   旧状态: {json.dumps(old_state, ensure_ascii=False)}")
            print(f"   新状态: {json.dumps(new_state, ensure_ascii=False)}")
            
            if old_state != new_state:
                print(f"   ⚠️  检测到状态变化！")
        
        devices[device_id]["last_updated"] = datetime.now().isoformat()
        print(f"\n✅ 同步完成: {device_id} <- Home Assistant (只读)")
        print(f"   更新时间: {devices[device_id]['last_updated']}")
        print("=" * 70)
        print()
        return True
    except Exception as e:
        print(f"❌ 同步数据解析失败: {e}")
        import traceback
        traceback.print_exc()
        return False

# ==================== 后台同步任务 ====================

def background_sync_task():
    """后台定时同步任务（只读模式）"""
    print("🔄 后台只读同步任务启动...")
    sync_count = 0
    
    while True:
        try:
            sync_count += 1
            print(f"\n{'='*70}")
            print(f"🔄 第 {sync_count} 次后台同步 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*70}")
            
            # 每10秒从 Home Assistant 同步一次状态
            for device_id in devices:
                if "ha_entity" in devices[device_id]:
                    # 保存完整的旧状态用于比较
                    old_state = {
                        k: v for k, v in devices[device_id].items() 
                        if k not in ['last_updated']
                    }
                    
                    if sync_from_ha(device_id):
                        # 保存新状态用于比较
                        new_state = {
                            k: v for k, v in devices[device_id].items() 
                            if k not in ['last_updated']
                        }
                        
                        # 如果状态有变化，推送给前端
                        if old_state != new_state:
                            print(f"📤 推送更新到前端: {device_id}")
                            socketio.emit('device_update', {
                                'device_id': device_id,
                                'device': devices[device_id],
                                'from_user': False
                            }, namespace='/')
                        else:
                            print(f"ℹ️  状态无变化，不推送: {device_id}")
            
            print(f"\n⏰ 等待1秒后进行下次同步...\n")
            time.sleep(1)
        except Exception as e:
            print(f"❌ 后台同步任务错误: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1)

# ==================== Flask 路由 ====================

@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')

@app.route('/api/devices', methods=['GET'])
def get_devices():
    """获取所有设备状态"""
    return jsonify({
        "success": True,
        "devices": devices,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/device/<device_id>', methods=['GET'])
def get_device(device_id):
    """获取单个设备状态"""
    if device_id in devices:
        return jsonify({
            "success": True,
            "device": devices[device_id]
        })
    return jsonify({
        "success": False,
        "message": "设备未找到"
    }), 404

@app.route('/api/sync', methods=['POST'])
def manual_sync():
    """手动触发同步（只读）"""
    device_id = request.json.get('device_id') if request.json else None
    
    print(f"\n🔄 手动同步请求")
    
    if device_id and device_id in devices:
        if sync_from_ha(device_id):
            socketio.emit('device_update', {
                'device_id': device_id,
                'device': devices[device_id],
                'from_user': False
            }, namespace='/')
            return jsonify({"success": True, "message": "同步成功（只读）"})
        else:
            return jsonify({"success": False, "message": "同步失败"}), 500
    else:
        # 同步所有设备
        success_count = 0
        for did in devices:
            if "ha_entity" in devices[did] and sync_from_ha(did):
                success_count += 1
        return jsonify({
            "success": True, 
            "message": f"已同步 {success_count} 个设备（只读）"
        })

# ==================== WebSocket 事件 ====================

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    print(f'\n✅ 客户端已连接')
    emit('connection_status', {'status': 'connected', 'message': '已连接到服务器（只读模式）'})
    
    # 连接时同步所有设备状态
    print(f'🔄 客户端连接，同步所有设备状态...')
    for device_id in devices:
        if "ha_entity" in devices[device_id]:
            sync_from_ha(device_id)
    
    # 发送当前所有设备状态
    emit('initial_state', {'devices': devices})
    print(f'📤 已发送初始状态到客户端\n')

@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开连接"""
    print('⚠️  客户端已断开\n')

@socketio.on('request_sync')
def handle_sync_request(data):
    """处理前端同步请求（只读）"""
    device_id = data.get('device_id') if data else None
    print(f"\n🔄 WebSocket同步请求: {device_id if device_id else '全部设备'}")
    
    if device_id and device_id in devices and "ha_entity" in devices[device_id]:
        if sync_from_ha(device_id):
            emit('device_update', {
                'device_id': device_id,
                'device': devices[device_id],
                'from_user': False
            }, broadcast=True)
    else:
        # 同步所有设备
        for did in devices:
            if "ha_entity" in devices[did]:
                sync_from_ha(did)

# ==================== 启动服务 ====================

if __name__ == '__main__':
    print("=" * 60)
    print("🏠 智能家居控制系统启动中（完全只读模式）...")
    print("=" * 60)
    print(f"📱 本地访问: http://localhost:5000")
    print(f"🌐 网络访问: http://0.0.0.0:5000")
    print(f"🔗 Home Assistant: {HOME_ASSISTANT_URL}")
    print(f"⚠️  完全只读模式：仅从 HA 读取数据，不发送任何控制命令")
    print("=" * 60)
    print(f"\n📋 设备列表:")
    print(f"   - 空调: sensor.living_room_ac_status (只读)")
    print(f"   - 灯泡: light.living_room_bulb (只读)")
    print(f"\n📋 空调支持的模式: 制冷、制热、送风、停止")
    print(f"📋 空调支持的风速: 低速、中速、高速")
    print(f"📋 灯泡支持的状态: light_on、light_off")
    print("=" * 60)
    
    # 启动时先同步一次
    print("\n🔄 初始同步 Home Assistant 状态（只读）...")
    for device_id in devices:
        if "ha_entity" in devices[device_id]:
            if sync_from_ha(device_id):
                print(f"  ✅ {devices[device_id]['name']} 🔒只读")
            else:
                print(f"  ⚠️  {devices[device_id]['name']} (无 HA 连接)")
    
    print("=" * 60)
    
    # 启动后台同步线程
    sync_thread = threading.Thread(target=background_sync_task, daemon=True)
    sync_thread.start()
    
    # 启动 Flask-SocketIO 服务器
    # 优先尝试绑定到 0.0.0.0:5000；若因权限/占用失败则回退到 127.0.0.1:5000/5001 便于排查
    try:
        socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
    except OSError as e:
        print(f"❌ 启动服务器时出现 OSError: {e}")
        print("   尝试回退到 127.0.0.1:5000 ...")
        try:
            socketio.run(app, debug=True, host='127.0.0.1', port=5000, allow_unsafe_werkzeug=True)
        except OSError as e2:
            print(f"❌ 回退到 127.0.0.1:5000 仍然失败: {e2}")
            print("   再尝试 127.0.0.1:5001 ...")
            try:
                socketio.run(app, debug=True, host='127.0.0.1', port=5001, allow_unsafe_werkzeug=True)
            except Exception as e3:
                print(f"❌ 无法启动服务器（多次尝试失败）：{e3}")
                print("请检查是否有其它进程占用端口、或以管理员身份运行，或调整防火墙/HTTP.sys 设置。")
