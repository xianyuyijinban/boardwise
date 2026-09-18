/**
  ******************************************************************************
  * @file    mpu6050.h
  * @brief   MPU6050 6轴姿态传感器驱动
  *          I2C地址: 0x68 (AD0=GND) 或 0x69 (AD0=VCC)
  ******************************************************************************
  */
#ifndef __MPU6050_H
#define __MPU6050_H

#include "main.h"
#include "i2c.h"

/* MPU6050 I2C地址 */
#define MPU6050_ADDR            0x68
#define MPU6050_ADDR_WRITE      (MPU6050_ADDR << 1)
#define MPU6050_ADDR_READ       ((MPU6050_ADDR << 1) | 1)

/* MPU6050寄存器定义 */
#define MPU6050_REG_SELF_TEST_X         0x0D
#define MPU6050_REG_SELF_TEST_Y         0x0E
#define MPU6050_REG_SELF_TEST_Z         0x0F
#define MPU6050_REG_SELF_TEST_A         0x10
#define MPU6050_REG_SMPLRT_DIV          0x19
#define MPU6050_REG_CONFIG              0x1A
#define MPU6050_REG_GYRO_CONFIG         0x1B
#define MPU6050_REG_ACCEL_CONFIG        0x1C
#define MPU6050_REG_ACCEL_XOUT_H        0x3B
#define MPU6050_REG_ACCEL_XOUT_L        0x3C
#define MPU6050_REG_ACCEL_YOUT_H        0x3D
#define MPU6050_REG_ACCEL_YOUT_L        0x3E
#define MPU6050_REG_ACCEL_ZOUT_H        0x3F
#define MPU6050_REG_ACCEL_ZOUT_L        0x40
#define MPU6050_REG_TEMP_OUT_H          0x41
#define MPU6050_REG_TEMP_OUT_L          0x42
#define MPU6050_REG_GYRO_XOUT_H         0x43
#define MPU6050_REG_GYRO_XOUT_L         0x44
#define MPU6050_REG_GYRO_YOUT_H         0x45
#define MPU6050_REG_GYRO_YOUT_L         0x46
#define MPU6050_REG_GYRO_ZOUT_H         0x47
#define MPU6050_REG_GYRO_ZOUT_L         0x48
#define MPU6050_REG_USER_CTRL           0x6A
#define MPU6050_REG_PWR_MGMT_1          0x6B
#define MPU6050_REG_PWR_MGMT_2          0x6C
#define MPU6050_REG_WHO_AM_I            0x75

/* MPU6050 ID */
#define MPU6050_ID              0x68

/* 加速度计量程 */
typedef enum {
    MPU6050_ACCEL_RANGE_2G  = 0,    // ±2g
    MPU6050_ACCEL_RANGE_4G  = 1,    // ±4g
    MPU6050_ACCEL_RANGE_8G  = 2,    // ±8g
    MPU6050_ACCEL_RANGE_16G = 3     // ±16g
} MPU6050_AccelRange_t;

/* 陀螺仪量程 */
typedef enum {
    MPU6050_GYRO_RANGE_250DPS  = 0, // ±250°/s
    MPU6050_GYRO_RANGE_500DPS  = 1, // ±500°/s
    MPU6050_GYRO_RANGE_1000DPS = 2, // ±1000°/s
    MPU6050_GYRO_RANGE_2000DPS = 3  // ±2000°/s
} MPU6050_GyroRange_t;

/* MPU6050数据结构 */
typedef struct {
    int16_t accel_x;        // X轴加速度原始值
    int16_t accel_y;        // Y轴加速度原始值
    int16_t accel_z;        // Z轴加速度原始值
    int16_t gyro_x;         // X轴陀螺仪原始值
    int16_t gyro_y;         // Y轴陀螺仪原始值
    int16_t gyro_z;         // Z轴陀螺仪原始值
    int16_t temp;           // 温度原始值
    
    float accel_x_g;        // X轴加速度 (g)
    float accel_y_g;        // Y轴加速度 (g)
    float accel_z_g;        // Z轴加速度 (g)
    float gyro_x_dps;       // X轴角速度 (°/s)
    float gyro_y_dps;       // Y轴角速度 (°/s)
    float gyro_z_dps;       // Z轴角速度 (°/s)
    float temp_c;           // 温度 (°C)
    
    float pitch;            // 俯仰角
    float roll;             // 横滚角
    
    MPU6050_AccelRange_t accel_range;
    MPU6050_GyroRange_t gyro_range;
} MPU6050_Data_t;

/* 函数声明 */
uint8_t MPU6050_Init(void);
uint8_t MPU6050_ReadID(void);
void MPU6050_SetAccelRange(MPU6050_AccelRange_t range);
void MPU6050_SetGyroRange(MPU6050_GyroRange_t range);
uint8_t MPU6050_ReadData(MPU6050_Data_t *data);
void MPU6050_CalculateAngles(MPU6050_Data_t *data);

#endif /* __MPU6050_H */
