/**
  ******************************************************************************
  * @file    bmp280.h
  * @brief   BMP280 气压温度传感器驱动
  *          I2C地址: 0x76 (SDO=GND) 或 0x77 (SDO=VCC)
  ******************************************************************************
  */
#ifndef __BMP280_H
#define __BMP280_H

#include "main.h"
#include "i2c.h"

/* BMP280 I2C地址 */
#define BMP280_ADDR             0x76
#define BMP280_ADDR_WRITE       (BMP280_ADDR << 1)
#define BMP280_ADDR_READ        ((BMP280_ADDR << 1) | 1)

/* BMP280寄存器定义 */
#define BMP280_REG_DIG_T1       0x88
#define BMP280_REG_DIG_T2       0x8A
#define BMP280_REG_DIG_T3       0x8C
#define BMP280_REG_DIG_P1       0x8E
#define BMP280_REG_DIG_P2       0x90
#define BMP280_REG_DIG_P3       0x92
#define BMP280_REG_DIG_P4       0x94
#define BMP280_REG_DIG_P5       0x96
#define BMP280_REG_DIG_P6       0x98
#define BMP280_REG_DIG_P7       0x9A
#define BMP280_REG_DIG_P8       0x9C
#define BMP280_REG_DIG_P9       0x9E
#define BMP280_REG_CHIPID       0xD0
#define BMP280_REG_VERSION      0xD1
#define BMP280_REG_SOFTRESET    0xE0
#define BMP280_REG_CAL26        0xE1
#define BMP280_REG_STATUS       0xF3
#define BMP280_REG_CONTROL      0xF4
#define BMP280_REG_CONFIG       0xF5
#define BMP280_REG_PRESS_MSB    0xF7
#define BMP280_REG_PRESS_LSB    0xF8
#define BMP280_REG_PRESS_XLSB   0xF9
#define BMP280_REG_TEMP_MSB     0xFA
#define BMP280_REG_TEMP_LSB     0xFB
#define BMP280_REG_TEMP_XLSB    0xFC

/* BMP280 ID */
#define BMP280_CHIP_ID          0x58

/* 过采样设置 */
typedef enum {
    BMP280_OVERSAMPLING_SKIP = 0x00,
    BMP280_OVERSAMPLING_X1   = 0x01,
    BMP280_OVERSAMPLING_X2   = 0x02,
    BMP280_OVERSAMPLING_X4   = 0x03,
    BMP280_OVERSAMPLING_X8   = 0x04,
    BMP280_OVERSAMPLING_X16  = 0x05
} BMP280_Oversampling_t;

/* 工作模式 */
typedef enum {
    BMP280_MODE_SLEEP  = 0x00,
    BMP280_MODE_FORCED = 0x01,
    BMP280_MODE_NORMAL = 0x03
} BMP280_Mode_t;

/* 滤波器设置 */
typedef enum {
    BMP280_FILTER_OFF = 0x00,
    BMP280_FILTER_X2  = 0x01,
    BMP280_FILTER_X4  = 0x02,
    BMP280_FILTER_X8  = 0x03,
    BMP280_FILTER_X16 = 0x04
} BMP280_Filter_t;

/* 校准参数结构体 */
typedef struct {
    uint16_t dig_T1;
    int16_t  dig_T2;
    int16_t  dig_T3;
    uint16_t dig_P1;
    int16_t  dig_P2;
    int16_t  dig_P3;
    int16_t  dig_P4;
    int16_t  dig_P5;
    int16_t  dig_P6;
    int16_t  dig_P7;
    int16_t  dig_P8;
    int16_t  dig_P9;
} BMP280_CalibData_t;

/* BMP280数据结构 */
typedef struct {
    int32_t temp_raw;       // 温度原始值
    int32_t press_raw;      // 气压原始值
    int32_t t_fine;         // 校准参数
    float temperature;      // 温度值 (°C)
    float pressure;         // 气压值 (Pa)
    float altitude;         // 海拔高度 (m)
} BMP280_Data_t;

/* 函数声明 */
uint8_t BMP280_Init(void);
uint8_t BMP280_ReadID(void);
void BMP280_Reset(void);
uint8_t BMP280_ReadCalibrationData(void);
void BMP280_SetConfig(BMP280_Oversampling_t temp_os, 
                      BMP280_Oversampling_t press_os,
                      BMP280_Mode_t mode);
void BMP280_SetFilter(BMP280_Filter_t filter);
uint8_t BMP280_ReadData(BMP280_Data_t *data);
float BMP280_CalculateAltitude(float pressure_pa, float sea_level_pa);

#endif /* __BMP280_H */
