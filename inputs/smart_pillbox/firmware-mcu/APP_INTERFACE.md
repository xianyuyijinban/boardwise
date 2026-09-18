# 智能药箱APP接口文档

## 1. 通信协议

- **协议**: MQTT over TCP
- **端口**: 1883 (默认)
- **编码**: UTF-8 JSON

### 1.1 MQTT连接参数建议

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| QoS | 0 | 传感器数据允许偶尔丢失，使用QoS 0降低开销 |
| KeepAlive | 20秒 | 建议设置为publish间隔的2-4倍 |
| Clean Session | true | APP端建议使用干净会话 |
| Connection Timeout | 10秒 | 连接超时时间 |
| Automatic Reconnect | true | 启用自动重连 |

### 1.2 离线检测机制

**心跳机制:**
- 设备每5秒发布一次传感器数据作为心跳
- 若APP在15秒内（3个publish间隔）未收到数据，可判定设备离线

**Last Will机制:**
- 设备连接时设置Will消息到 `medicine/{device_id}/status`
- Will消息: `{"status": "offline", "timestamp": 123456789}`
- 当设备异常断开且超过KeepAlive时间未发送消息时，Broker自动发布Will消息

**建议的离线判定逻辑:**
```kotlin
// 在APP中实现离线检测
private var lastDataTime = System.currentTimeMillis()
private val OFFLINE_TIMEOUT = 15000 // 15秒

fun checkOffline(): Boolean {
    return (System.currentTimeMillis() - lastDataTime) > OFFLINE_TIMEOUT
}

// 收到数据时更新
mqttClient.subscribe("medicine/$deviceId/sensors") { topic, message ->
    lastDataTime = System.currentTimeMillis()
    parseSensorData(message)
}
```

## 2. 主题(Topics)

### 2.1 数据发布主题 (药箱 → APP)

```
medicine/{device_id}/sensors
```

**示例数据格式:**

```json
{
    "timestamp": 123456789,
    "device_id": "medicine_box_001",
    "state": "closed",
    "environment": {
        "temperature": 25.30,
        "humidity": 55.50,
        "pressure": 101325.00,
        "altitude": 0.00
    },
    "environment_limits": {
        "temperature_rated": 15.00,
        "temperature_low": 10.50,
        "temperature_high": 19.50,
        "humidity_rated": 50.00,
        "humidity_low": 35.00,
        "humidity_high": 65.00
    },
    "motion": {
        "accel_x": 0.015,
        "accel_y": -0.008,
        "accel_z": 0.995,
        "gyro_x": 0.50,
        "gyro_y": -0.30,
        "gyro_z": 0.10,
        "pitch": 2.15,
        "roll": -1.02,
        "vibration": 0.005
    },
    "alerts": {
        "env_abnormal": 0,
        "temperature_abnormal": 0,
        "humidity_abnormal": 0
    },
    "valid": 1
}
```

### 2.2 状态主题 (药箱 → APP)

```
medicine/{device_id}/status
```

**上线消息 (retained):**
```json
{"status": "online", "timestamp": 123456789}
```

**离线消息 (will, retained):**
```json
{"status": "offline", "timestamp": 123456789}
```

**扩展状态消息 (包含设备信息):**
```json
{
    "status": "online",
    "timestamp": 123456789,
    "device_id": "medicine_box_001",
    "firmware_version": "1.0.0",
    "wifi_rssi": -65,
    "publish_interval": 5
}
```

### 2.3 控制主题 (APP → 药箱)

```
medicine/{device_id}/control
```

**支持的控制命令:**

| 命令 | 描述 | 示例 |
|------|------|------|
| `reset` | 重置设备 | `{"cmd": "reset"}` |
| `publish_now` | 立即上报数据 | `{"cmd": "publish_now"}` |
| `set_interval` | 设置上报间隔 | `{"cmd": "set_interval", "value": 10}` |
| `set_env_rated` | 设置温湿度额定值 | `{"cmd":"set_env_rated","temperature":15,"humidity":50}` |

额定值未设置时，设备默认使用 `15°C` 与 `50%RH`。设备会按额定值上下浮动 `30%` 判断异常。

### 2.4 告警主题 (药箱 → APP)

```
medicine/{device_id}/alert
```

设备在温湿度异常时会立即发布 `env_abnormal` 事件，并触发本地蜂鸣器 `3` 次提示（每次间隔 `1` 秒）；恢复正常后发布 `env_recovered`。  
当检测到跌落（加速度 > `6G` 且持续 > `20ms`）时发布 `drop_detected`，并触发本地蜂鸣器持续报警（`5s` 响、`3s` 停，重复 `3` 次）。报警期间若用户按下 `KEY2(PB15)`，设备发布 `drop_alarm_cancelled`（`stop_push=1`）用于APP停止异常推送。

```json
{
    "event": "env_abnormal",
    "timestamp": 123456789,
    "temperature": 28.40,
    "humidity": 82.10,
    "rated_temperature": 15.00,
    "rated_humidity": 50.00,
    "temperature_abnormal": 1,
    "humidity_abnormal": 1
}

{
    "event": "drop_detected",
    "timestamp": 123456999,
    "accel_x": 6.80,
    "accel_y": 0.32,
    "accel_z": 1.12,
    "accel_magnitude": 6.90,
    "threshold_g": 6.0,
    "duration_ms": 20
}

{
    "event": "drop_alarm_cancelled",
    "timestamp": 123457100,
    "source": "key2",
    "stop_push": 1
}
```

**命令响应格式 (药箱 → APP):**

设备执行命令后，会在 `medicine/{device_id}/control/response` 主题发布响应：

```json
// 成功响应
{
    "cmd": "reset",
    "result": "ok",
    "timestamp": 123456789
}

// 失败响应
{
    "cmd": "set_interval",
    "result": "error",
    "error_code": 400,
    "error_msg": "Invalid interval value",
    "timestamp": 123456789
}
```

**错误码定义:**

| 错误码 | 描述 | 场景 |
|--------|------|------|
| 400 | 参数错误 | 命令参数无效或超出范围 |
| 401 | 权限错误 | 未授权的操作 |
| 500 | 设备错误 | 设备执行命令失败 |
| 503 | 服务不可用 | 设备当前状态不允许执行该命令 |

## 3. 状态说明

| state值 | 描述 | 触发条件 |
|---------|------|----------|
| `closed` | 药箱关闭 | Z轴加速度>0.7g，无倾斜 |
| `opened` | 药箱打开 | Z轴加速度<0.7g |
| `moving` | 移动中 | 振动强度>0.5g |
| `tilted` | 倾斜状态 | 俯仰角或横滚角>30° |

## 4. 数据字段说明

### 4.1 基础字段

| 字段 | 类型 | 说明 |
|------|------|------|
| timestamp | uint32 | 时间戳（毫秒，从设备启动开始计时） |
| device_id | string | 设备唯一标识符 |
| state | string | 药箱状态：closed/opened/moving/tilted |
| valid | uint8 | 数据有效性标志：1=有效，0=无效 |
| firmware_version | string | 固件版本号（仅在状态消息中） |
| wifi_rssi | int8 | WiFi信号强度（dBm，仅在状态消息中） |
| publish_interval | uint16 | 当前数据上报间隔（秒，仅在状态消息中） |

### 4.2 环境数据 (environment)

| 字段 | 单位 | 范围 | 精度 | 说明 |
|------|------|------|------|------|
| temperature | °C | -40~85 | 0.01 | 温度（AHT20+BMP280平均值） |
| humidity | %RH | 0~100 | 0.01 | 相对湿度（AHT20） |
| pressure | Pa | 30000~110000 | 0.01 | 大气压强（BMP280） |
| altitude | m | -500~9000 | 0.01 | 海拔高度（基于气压估算） |

### 4.3 运动数据 (motion)

| 字段 | 单位 | 范围 | 精度 | 说明 |
|------|------|------|------|------|
| accel_x/y/z | g | -2~2 | 0.001 | 三轴加速度 |
| gyro_x/y/z | °/s | -250~250 | 0.01 | 三轴角速度 |
| pitch | ° | -90~90 | 0.01 | 俯仰角 |
| roll | ° | -180~180 | 0.01 | 横滚角 |
| vibration | g | 0~10 | 0.001 | 振动强度（平均加速度变化率） |

### 4.4 环境阈值数据 (environment_limits)

| 字段 | 单位 | 说明 |
|------|------|------|
| temperature_rated | °C | 当前温度额定值（默认15） |
| temperature_low/high | °C | 温度异常下限/上限（额定值±30%） |
| humidity_rated | %RH | 当前湿度额定值（默认50） |
| humidity_low/high | %RH | 湿度异常下限/上限（额定值±30%） |

### 4.5 告警状态 (alerts)

| 字段 | 类型 | 说明 |
|------|------|------|
| env_abnormal | uint8 | 温湿度是否异常（1=异常，0=正常） |
| temperature_abnormal | uint8 | 温度是否异常 |
| humidity_abnormal | uint8 | 湿度是否异常 |

## 5. APP开发建议

### 5.1 推荐开发框架

- **Android**: Kotlin + MQTT-Client库
- **iOS**: Swift + CocoaMQTT
- **跨平台**: Flutter + mqtt_client

### 5.2 界面建议

```
┌─────────────────────────────┐
│      智能药箱监控           │
├─────────────────────────────┤
│  状态: [●] 正常 / [!] 异常  │
├─────────────────────────────┤
│  🌡️ 温度: 25.3°C           │
│  💧 湿度: 55.5%             │
│  🌀 气压: 1013.25 hPa       │
├─────────────────────────────┤
│  📦 药箱状态: 已关闭        │
│  📳 振动: 正常              │
│  📐 倾斜: 正常              │
├─────────────────────────────┤
│      [刷新]  [设置]         │
└─────────────────────────────┘
```

### 5.3 告警建议

| 告警条件 | 级别 | 建议动作 |
|----------|------|----------|
| 温度超出额定值±30% | 警告 | 推送通知 |
| 湿度超出额定值±30% | 警告 | 推送通知 |
| 加速度>6G且持续>20ms | 严重 | 立即推送通知栏 |
| 药箱被打开(state=opened) | 信息 | 记录日志 |
| 药箱移动中(state=moving) | 注意 | 可选通知 |
| 设备离线 | 严重 | 推送+短信 |

## 6. MQTT Broker推荐

### 6.1 本地部署
```bash
# 使用Mosquitto
docker run -d -p 1883:1883 -p 9001:9001 eclipse-mosquitto
```

### 6.2 云服务
- **EMQX Cloud**: https://www.emqx.com/
- **阿里云IoT**: https://iot.aliyun.com/
- **OneNET**: https://open.iot.10086.cn/

## 7. 示例代码 (Android/Kotlin)

```kotlin
import org.eclipse.paho.client.mqttv3.*

class MedicineBoxClient {
    private val broker = "tcp://192.168.1.100:1883"
    private val clientId = "AndroidApp_001"
    private val deviceId = "medicine_box_001"
    
    private lateinit var mqttClient: MqttClient
    
    fun connect() {
        mqttClient = MqttClient(broker, clientId, null)
        val options = MqttConnectOptions().apply {
            isAutomaticReconnect = true
            isCleanSession = true
            connectionTimeout = 10
            keepAliveInterval = 20
        }
        mqttClient.connect(options)
        
        // 订阅数据主题
        mqttClient.subscribe("medicine/$deviceId/sensors") { topic, message ->
            val json = String(message.payload)
            parseSensorData(json)
        }
        
        // 订阅状态主题
        mqttClient.subscribe("medicine/$deviceId/status") { topic, message ->
            val json = String(message.payload)
            updateDeviceStatus(json)
        }

        // 订阅命令响应主题
        mqttClient.subscribe("medicine/$deviceId/control/response") { topic, message ->
            val json = String(message.payload)
            handleCommandResponse(json)
        }

        // 订阅环境告警主题（用于通知栏推送）
        mqttClient.subscribe("medicine/$deviceId/alert") { topic, message ->
            val json = String(message.payload)
            handleEnvAlert(json)
        }
    }

    fun sendCommand(cmd: String, value: Any? = null) {
        val payload = JSONObject().apply {
            put("cmd", cmd)
            value?.let { put("value", it) }
        }
        val message = MqttMessage(payload.toString().toByteArray())
        mqttClient.publish("medicine/$deviceId/control", message)
    }

    private fun handleCommandResponse(json: String) {
        val response = JSONObject(json)
        val cmd = response.getString("cmd")
        val result = response.getString("result")

        if (result == "ok") {
            println("命令 $cmd 执行成功")
        } else {
            val errorCode = response.getInt("error_code")
            val errorMsg = response.getString("error_msg")
            println("命令 $cmd 执行失败: [$errorCode] $errorMsg")
        }
    }

    private fun handleEnvAlert(json: String) {
        val alert = JSONObject(json)
        if (alert.getString("event") == "env_abnormal") {
            // 这里触发通知栏推送
            println("收到环境异常告警: $json")
        }
    }
}
```
