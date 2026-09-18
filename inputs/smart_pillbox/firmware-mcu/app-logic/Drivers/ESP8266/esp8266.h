/**
  ******************************************************************************
  * @file    esp8266.h
  * @brief   ESP8266 ESP-01S WiFi模块驱动
  *          使用USART3接口 (PB10-TX, PB11-RX)
  *          控制引脚: PD2-WIFIEN, PC12-WIFIRST, PB3-IO0
  ******************************************************************************
  */
#ifndef __ESP8266_H
#define __ESP8266_H

#include "main.h"
#include "usart.h"
#include <stdbool.h>

/* ESP8266控制引脚 */
#define ESP8266_EN_GPIO         GPIOD
#define ESP8266_EN_PIN          GPIO_PIN_2
#define ESP8266_RST_GPIO        GPIOC
#define ESP8266_RST_PIN         GPIO_PIN_12
#define ESP8266_IO0_GPIO        GPIOB
#define ESP8266_IO0_PIN         GPIO_PIN_3

#define ESP8266_EN_HIGH()       HAL_GPIO_WritePin(ESP8266_EN_GPIO, ESP8266_EN_PIN, GPIO_PIN_SET)
#define ESP8266_EN_LOW()        HAL_GPIO_WritePin(ESP8266_EN_GPIO, ESP8266_EN_PIN, GPIO_PIN_RESET)
#define ESP8266_RST_HIGH()      HAL_GPIO_WritePin(ESP8266_RST_GPIO, ESP8266_RST_PIN, GPIO_PIN_SET)
#define ESP8266_RST_LOW()       HAL_GPIO_WritePin(ESP8266_RST_GPIO, ESP8266_RST_PIN, GPIO_PIN_RESET)
#define ESP8266_IO0_HIGH()      HAL_GPIO_WritePin(ESP8266_IO0_GPIO, ESP8266_IO0_PIN, GPIO_PIN_SET)
#define ESP8266_IO0_LOW()       HAL_GPIO_WritePin(ESP8266_IO0_GPIO, ESP8266_IO0_PIN, GPIO_PIN_RESET)

/* 缓冲区大小 */
#define ESP8266_RX_BUF_SIZE     1024
#define ESP8266_TX_BUF_SIZE     512
#define ESP8266_CMD_TIMEOUT     5000    // 命令超时时间(ms)
#define ESP8266_RESP_TIMEOUT    10000   // 响应超时时间(ms)

/* MQTT配置结构体 */
typedef struct {
    char broker_ip[32];         // MQTT服务器IP
    uint16_t broker_port;       // MQTT服务器端口
    char client_id[32];         // 客户端ID
    char username[32];          // 用户名
    char password[32];          // 密码
    uint16_t keepalive;         // 保活时间(秒)
} ESP8266_MQTT_Config_t;

/* WiFi配置结构体 */
typedef struct {
    char ssid[32];              // WiFi名称
    char password[64];          // WiFi密码
} ESP8266_WiFi_Config_t;

/* 连接状态 */
typedef enum {
    ESP8266_STATE_RESET = 0,
    ESP8266_STATE_INIT,
    ESP8266_STATE_WIFI_CONNECTING,
    ESP8266_STATE_WIFI_CONNECTED,
    ESP8266_STATE_MQTT_CONNECTING,
    ESP8266_STATE_MQTT_CONNECTED,
    ESP8266_STATE_ERROR
} ESP8266_State_t;

typedef void (*ESP8266_MQTT_MessageCallback_t)(const char *topic, const char *payload);

/* 函数声明 */
void ESP8266_Init(void);
void ESP8266_Reset(void);
void ESP8266_Enable(void);
void ESP8266_Disable(void);
uint8_t ESP8266_SendATCommand(const char *cmd, const char *expected_resp, uint32_t timeout_ms);
uint8_t ESP8266_SendData(uint8_t *data, uint16_t len);

/* WiFi功能 */
uint8_t ESP8266_WiFi_Init(void);
uint8_t ESP8266_WiFi_Connect(const char *ssid, const char *password);
uint8_t ESP8266_WiFi_Disconnect(void);
uint8_t ESP8266_WiFi_IsConnected(void);

/* MQTT功能 */
uint8_t ESP8266_MQTT_Init(const char *broker_ip, uint16_t port);
uint8_t ESP8266_MQTT_Connect(const char *client_id, const char *username, const char *password);
uint8_t ESP8266_MQTT_ConnectToBroker(const char *broker_ip, uint16_t port);
uint8_t ESP8266_MQTT_Disconnect(void);
uint8_t ESP8266_MQTT_Publish(const char *topic, const char *payload, uint8_t qos, uint8_t retain);
uint8_t ESP8266_MQTT_Subscribe(const char *topic, uint8_t qos);
uint8_t ESP8266_MQTT_Unsubscribe(const char *topic);
void ESP8266_RegisterMQTTMessageCallback(ESP8266_MQTT_MessageCallback_t callback);

/* 状态获取 */
ESP8266_State_t ESP8266_GetState(void);
const char* ESP8266_GetStateString(void);

/* 数据接收处理 */
void ESP8266_UART_RxCallback(uint8_t data);
void ESP8266_ProcessRxData(void);

#endif /* __ESP8266_H */
