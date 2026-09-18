/**
  ******************************************************************************
  * @file    esp8266.c
  * @brief   ESP8266 ESP-01S WiFi模块驱动实现
  *          使用USART3接口 (PB10-TX, PB11-RX)
  ******************************************************************************
  */
#include "esp8266.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

extern UART_HandleTypeDef huart3;  // USART3用于ESP-01S

/* 接收缓冲区 */
static uint8_t rx_buffer[ESP8266_RX_BUF_SIZE];
static volatile uint16_t rx_write_idx = 0;
static volatile uint16_t rx_read_idx = 0;

/* 当前状态 */
static ESP8266_State_t esp_state = ESP8266_STATE_RESET;
static ESP8266_MQTT_MessageCallback_t mqtt_message_callback = NULL;

static void ESP8266_ClearRxBuffer(void)
{
    rx_write_idx = 0;
    rx_read_idx = 0;
    memset(rx_buffer, 0, ESP8266_RX_BUF_SIZE);
}

static uint8_t ESP8266_ParseSubRecvMessage(const char *message,
                                           char *topic,
                                           uint16_t topic_size,
                                           char *payload,
                                           uint16_t payload_size)
{
    const char *prefix;
    const char *cursor;
    const char *topic_start;
    const char *topic_end;
    const char *line_end;
    char *len_end = NULL;
    long payload_len;
    size_t topic_len;
    size_t available_len;
    size_t copy_len;

    if ((message == NULL) || (topic == NULL) || (payload == NULL) ||
        (topic_size == 0U) || (payload_size == 0U)) {
        return 1U;
    }

    prefix = strstr(message, "+MQTTSUBRECV:");
    if (prefix == NULL) {
        return 1U;
    }

    cursor = prefix + strlen("+MQTTSUBRECV:");
    cursor = strchr(cursor, ',');
    if (cursor == NULL) {
        return 1U;
    }
    cursor++;

    if (*cursor == '"') {
        cursor++;
        topic_start = cursor;
        topic_end = strchr(cursor, '"');
        if (topic_end == NULL) {
            return 1U;
        }
        cursor = topic_end + 1;
        if (*cursor != ',') {
            return 1U;
        }
    } else {
        topic_start = cursor;
        topic_end = strchr(cursor, ',');
        if (topic_end == NULL) {
            return 1U;
        }
        cursor = topic_end;
    }

    if (*cursor != ',') {
        return 1U;
    }
    cursor++;

    topic_len = (size_t)(topic_end - topic_start);
    if (topic_len >= topic_size) {
        return 1U;
    }

    memcpy(topic, topic_start, topic_len);
    topic[topic_len] = '\0';

    payload_len = strtol(cursor, &len_end, 10);
    if ((len_end == cursor) || (len_end == NULL) || (*len_end != ',') || (payload_len < 0)) {
        return 1U;
    }

    cursor = len_end + 1;
    line_end = strstr(cursor, "\r\n");
    available_len = (line_end != NULL) ? (size_t)(line_end - cursor) : strlen(cursor);
    copy_len = (size_t)payload_len;
    if (copy_len > available_len) {
        copy_len = available_len;
    }
    if (copy_len >= payload_size) {
        copy_len = payload_size - 1U;
    }

    memcpy(payload, cursor, copy_len);
    payload[copy_len] = '\0';
    return 0U;
}

/**
  * @brief  初始化ESP8266 GPIO
  */
void ESP8266_Init(void)
{
    /* IO0置高，进入正常工作模式 */
    ESP8266_IO0_HIGH();
    
    /* 先拉低复位引脚 */
    ESP8266_RST_LOW();
    ESP8266_EN_LOW();
    
    HAL_Delay(100);
    
    /* 使能模块 */
    ESP8266_Enable();
    
    esp_state = ESP8266_STATE_INIT;
}

/**
  * @brief  使能ESP8266
  */
void ESP8266_Enable(void)
{
    ESP8266_EN_HIGH();
    HAL_Delay(10);
    ESP8266_RST_HIGH();
    HAL_Delay(100);
}

/**
  * @brief  禁用ESP8266
  */
void ESP8266_Disable(void)
{
    ESP8266_EN_LOW();
    ESP8266_RST_LOW();
}

/**
  * @brief  复位ESP8266
  */
void ESP8266_Reset(void)
{
    ESP8266_RST_LOW();
    HAL_Delay(100);
    ESP8266_RST_HIGH();
    HAL_Delay(500);
    
    ESP8266_ClearRxBuffer();
}

/**
  * @brief  发送AT命令
  * @param  cmd: 命令字符串
  * @param  expected_resp: 期望响应
  * @param  timeout_ms: 超时时间
  * @retval 0:成功 1:失败
  */
uint8_t ESP8266_SendATCommand(const char *cmd, const char *expected_resp, uint32_t timeout_ms)
{
    uint8_t cmd_buf[ESP8266_TX_BUF_SIZE];
    uint32_t start_tick;
    
    /* 清空接收缓冲区 */
    ESP8266_ClearRxBuffer();
    
    /* 组装命令 */
    snprintf((char *)cmd_buf, ESP8266_TX_BUF_SIZE, "%s\r\n", cmd);
    
    /* 发送命令 */
    HAL_UART_Transmit(&huart3, cmd_buf, strlen((char *)cmd_buf), 1000);
    
    /* 等待响应 */
    start_tick = HAL_GetTick();
    while ((HAL_GetTick() - start_tick) < timeout_ms) {
        /* 检查期望响应 */
        if (expected_resp != NULL) {
            if (strstr((char *)rx_buffer, expected_resp) != NULL) {
                return 0;
            }
        }
        
        /* 检查错误响应 */
        if (strstr((char *)rx_buffer, "ERROR") != NULL) {
            return 1;
        }
        
        HAL_Delay(10);
    }
    
    return 1;  // 超时
}

/**
  * @brief  发送原始数据
  * @param  data: 数据指针
  * @param  len: 长度
  * @retval 0:成功 1:失败
  */
uint8_t ESP8266_SendData(uint8_t *data, uint16_t len)
{
    if (HAL_UART_Transmit(&huart3, data, len, 1000) == HAL_OK) {
        return 0;
    }
    return 1;
}

/**
  * @brief  初始化WiFi模块(AT测试)
  * @retval 0:成功 1:失败
  */
uint8_t ESP8266_WiFi_Init(void)
{
    uint8_t retry = 3;
    
    /* 关闭回显 */
    while (retry--) {
        if (ESP8266_SendATCommand("ATE0", "OK", 1000) == 0) {
            break;
        }
        HAL_Delay(500);
    }
    
    if (retry == 0) {
        return 1;
    }
    
    /* 设置模式为STA */
    if (ESP8266_SendATCommand("AT+CWMODE=1", "OK", 2000) != 0) {
        return 1;
    }
    
    /* 关闭DHCP(可选) */
    ESP8266_SendATCommand("AT+CWDHCP=1,1", "OK", 2000);
    
    return 0;
}

/**
  * @brief  连接WiFi
  * @param  ssid: WiFi名称
  * @param  password: WiFi密码
  * @retval 0:成功 1:失败
  */
uint8_t ESP8266_WiFi_Connect(const char *ssid, const char *password)
{
    char cmd[128];
    
    esp_state = ESP8266_STATE_WIFI_CONNECTING;
    
    /* 组装连接命令 */
    snprintf(cmd, sizeof(cmd), "AT+CWJAP=\"%s\",\"%s\"", ssid, password);
    
    if (ESP8266_SendATCommand(cmd, "WIFI GOT IP", 15000) != 0) {
        esp_state = ESP8266_STATE_ERROR;
        return 1;
    }
    
    esp_state = ESP8266_STATE_WIFI_CONNECTED;
    return 0;
}

/**
  * @brief  断开WiFi连接
  * @retval 0:成功 1:失败
  */
uint8_t ESP8266_WiFi_Disconnect(void)
{
    if (ESP8266_SendATCommand("AT+CWQAP", "OK", 5000) == 0) {
        esp_state = ESP8266_STATE_INIT;
        return 0;
    }
    return 1;
}

/**
  * @brief  检查WiFi连接状态
  * @retval 1:已连接 0:未连接
  */
uint8_t ESP8266_WiFi_IsConnected(void)
{
    char *resp;
    
    if (ESP8266_SendATCommand("AT+CIPSTATUS", "OK", 2000) != 0) {
        return 0;
    }
    
    resp = strstr((char *)rx_buffer, "STATUS:");
    if (resp != NULL) {
        int status = atoi(resp + 7);
        /* STATUS:2 获得IP, STATUS:3 已连接, STATUS:4 断开 */
        return (status == 2 || status == 3) ? 1 : 0;
    }
    
    return 0;
}

/**
  * @brief  初始化MQTT
  * @param  broker_ip: MQTT服务器IP
  * @param  port: 端口号
  * @retval 0:成功 1:失败
  */
uint8_t ESP8266_MQTT_Init(const char *broker_ip, uint16_t port)
{
    char cmd[64];
    
    /* 设置MQTT用户配置 */
    snprintf(cmd, sizeof(cmd), "AT+MQTTUSERCFG=0,1,\"%s\",\"%s\",\"%s\",0,0,\"\"",
             "medicine_box_001", "", "");
    
    if (ESP8266_SendATCommand(cmd, "OK", 5000) != 0) {
        return 1;
    }
    
    /* 设置MQTT连接 */
    snprintf(cmd, sizeof(cmd), "AT+MQTTCONNCFG=0,120,0,\"%s\",\"%s\",0,0",
             "medicine_box/lwt", "offline");
    
    if (ESP8266_SendATCommand(cmd, "OK", 5000) != 0) {
        return 1;
    }
    
    return 0;
}

/**
  * @brief  连接MQTT服务器
  * @param  client_id: 客户端ID
  * @param  username: 用户名
  * @param  password: 密码
  * @retval 0:成功 1:失败
  */
uint8_t ESP8266_MQTT_Connect(const char *client_id, const char *username, const char *password)
{
    char cmd[128];
    
    esp_state = ESP8266_STATE_MQTT_CONNECTING;
    
    /* 重新配置MQTT用户参数 */
    snprintf(cmd, sizeof(cmd), "AT+MQTTUSERCFG=0,1,\"%s\",\"%s\",\"%s\",0,0,\"\"",
             client_id, username ? username : "", password ? password : "");
    
    if (ESP8266_SendATCommand(cmd, "OK", 5000) != 0) {
        esp_state = ESP8266_STATE_ERROR;
        return 1;
    }
    
    /* 执行连接 (使用默认配置) */
    /* 实际连接命令需要在初始化后执行 */
    
    esp_state = ESP8266_STATE_MQTT_CONNECTED;
    return 0;
}

/**
  * @brief  连接到指定MQTT服务器
  * @param  broker_ip: 服务器IP
  * @param  port: 端口
  * @retval 0:成功 1:失败
  */
uint8_t ESP8266_MQTT_ConnectToBroker(const char *broker_ip, uint16_t port)
{
    char cmd[128];
    
    esp_state = ESP8266_STATE_MQTT_CONNECTING;

    snprintf(cmd, sizeof(cmd), "AT+MQTTCONN=0,\"%s\",%d,1", broker_ip, port);
    
    if (ESP8266_SendATCommand(cmd, "+MQTTCONNECTED", 10000) != 0) {
        /* 连接失败时仍保持WiFi已连接状态，便于上层重试 */
        esp_state = ESP8266_STATE_WIFI_CONNECTED;
        return 1;
    }

    esp_state = ESP8266_STATE_MQTT_CONNECTED;
    
    return 0;
}

/**
  * @brief  断开MQTT连接
  * @retval 0:成功 1:失败
  */
uint8_t ESP8266_MQTT_Disconnect(void)
{
    if (ESP8266_SendATCommand("AT+MQTTCLEAN=0", "OK", 5000) == 0) {
        if (esp_state == ESP8266_STATE_MQTT_CONNECTED) {
            esp_state = ESP8266_STATE_WIFI_CONNECTED;
        }
        return 0;
    }
    return 1;
}

/**
  * @brief  发布MQTT消息
  * @param  topic: 主题
  * @param  payload: 消息内容
  * @param  qos: QoS等级 (0-2)
  * @param  retain: 保留标志
  * @retval 0:成功 1:失败
  */
uint8_t ESP8266_MQTT_Publish(const char *topic, const char *payload, uint8_t qos, uint8_t retain)
{
    char cmd[ESP8266_TX_BUF_SIZE];
    
    snprintf(cmd, sizeof(cmd), "AT+MQTTPUB=0,\"%s\",\"%s\",%d,%d",
             topic, payload, qos, retain);
    
    if (ESP8266_SendATCommand(cmd, "OK", 5000) == 0) {
        return 0;
    }
    
    return 1;
}

/**
  * @brief  订阅MQTT主题
  * @param  topic: 主题
  * @param  qos: QoS等级
  * @retval 0:成功 1:失败
  */
uint8_t ESP8266_MQTT_Subscribe(const char *topic, uint8_t qos)
{
    char cmd[128];
    
    snprintf(cmd, sizeof(cmd), "AT+MQTTSUB=0,\"%s\",%d", topic, qos);
    
    if (ESP8266_SendATCommand(cmd, "OK", 5000) == 0) {
        return 0;
    }
    
    return 1;
}

/**
  * @brief  取消订阅MQTT主题
  * @param  topic: 主题
  * @retval 0:成功 1:失败
  */
uint8_t ESP8266_MQTT_Unsubscribe(const char *topic)
{
    char cmd[128];
    
    snprintf(cmd, sizeof(cmd), "AT+MQTTUNSUB=0,\"%s\"", topic);
    
    if (ESP8266_SendATCommand(cmd, "OK", 5000) == 0) {
        return 0;
    }
    
    return 1;
}

void ESP8266_RegisterMQTTMessageCallback(ESP8266_MQTT_MessageCallback_t callback)
{
    mqtt_message_callback = callback;
}

/**
  * @brief  获取当前状态
  * @retval 状态枚举
  */
ESP8266_State_t ESP8266_GetState(void)
{
    return esp_state;
}

/**
  * @brief  获取状态字符串
  * @retval 状态描述
  */
const char* ESP8266_GetStateString(void)
{
    switch (esp_state) {
        case ESP8266_STATE_RESET:           return "RESET";
        case ESP8266_STATE_INIT:            return "INIT";
        case ESP8266_STATE_WIFI_CONNECTING: return "WIFI_CONNECTING";
        case ESP8266_STATE_WIFI_CONNECTED:  return "WIFI_CONNECTED";
        case ESP8266_STATE_MQTT_CONNECTING: return "MQTT_CONNECTING";
        case ESP8266_STATE_MQTT_CONNECTED:  return "MQTT_CONNECTED";
        case ESP8266_STATE_ERROR:           return "ERROR";
        default:                            return "UNKNOWN";
    }
}

/**
  * @brief  UART接收回调函数 (需要在HAL_UART_RxCpltCallback中调用)
  * @param  data: 接收到的字节
  */
void ESP8266_UART_RxCallback(uint8_t data)
{
    rx_buffer[rx_write_idx] = data;
    rx_write_idx = (rx_write_idx + 1) % ESP8266_RX_BUF_SIZE;
    
    /* 检查缓冲区溢出 */
    if (rx_write_idx == rx_read_idx) {
        rx_read_idx = (rx_read_idx + 1) % ESP8266_RX_BUF_SIZE;
    }
}

/**
  * @brief  处理接收到的数据
  * @note   可在FreeRTOS任务中调用
  */
void ESP8266_ProcessRxData(void)
{
    char topic[128];
    char payload[256];
    
    if (strstr((char *)rx_buffer, "+MQTTSUBRECV:") != NULL) {
        if (ESP8266_ParseSubRecvMessage((const char *)rx_buffer,
                                        topic, sizeof(topic),
                                        payload, sizeof(payload)) == 0U) {
            if (mqtt_message_callback != NULL) {
                mqtt_message_callback(topic, payload);
            }
        }
        ESP8266_ClearRxBuffer();
    }
    
    if (strstr((char *)rx_buffer, "WIFI DISCONNECT") != NULL) {
        esp_state = ESP8266_STATE_INIT;
        ESP8266_ClearRxBuffer();
    }
    
    if (strstr((char *)rx_buffer, "+MQTTDISCONNECTED") != NULL) {
        esp_state = ESP8266_STATE_WIFI_CONNECTED;
        ESP8266_ClearRxBuffer();
    }
}
