/**
  ******************************************************************************
  * @file    aht20.h
  * @brief   AHT20 温湿度传感器驱动
  *          I2C地址: 0x38
  ******************************************************************************
  */
#ifndef __AHT20_H
#define __AHT20_H

#include "main.h"
#include "i2c.h"

/* AHT20 I2C地址 */
#define AHT20_ADDR              0x38
#define AHT20_ADDR_WRITE        (AHT20_ADDR << 1)
#define AHT20_ADDR_READ         ((AHT20_ADDR << 1) | 1)

/* AHT20命令 */
#define AHT20_CMD_INIT          0xBE    // 初始化命令: 0xBE 0x08 0x00
#define AHT20_CMD_TRIG          0xAC    // 触发测量: 0xAC 0x33 0x00
#define AHT20_CMD_SOFT_RESET    0xBA    // 软复位
#define AHT20_CMD_STATUS        0x71    // 读取状态字

/* AHT20数据结构 */
typedef struct {
    uint8_t status;         // 状态字节
    uint32_t humidity_raw;  // 湿度原始值 (20bit)
    uint32_t temp_raw;      // 温度原始值 (20bit)
    float humidity;         // 湿度值 (%RH)
    float temperature;      // 温度值 (°C)
} AHT20_Data_t;

/* 函数声明 */
uint8_t AHT20_Init(void);
uint8_t AHT20_SoftReset(void);
uint8_t AHT20_ReadStatus(uint8_t *status);
uint8_t AHT20_ReadCalibrationEnabled(void);
uint8_t AHT20_StartMeasurement(void);
uint8_t AHT20_ReadData(AHT20_Data_t *data);
uint8_t AHT20_ReadDataBlocking(AHT20_Data_t *data, uint32_t timeout_ms);

#endif /* __AHT20_H */
