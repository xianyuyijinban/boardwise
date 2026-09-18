/**
  ******************************************************************************
  * @file    aht20.c
  * @brief   AHT20 温湿度传感器驱动实现
  *          使用I2C3接口 (PC8-SCL, PC9-SDA)
  ******************************************************************************
  */
#include "aht20.h"

extern I2C_HandleTypeDef hi2c3;

/**
  * @brief  向AHT20写入命令
  * @param  cmd: 命令缓冲区
  * @param  len: 长度
  * @retval HAL状态
  */
static HAL_StatusTypeDef AHT20_WriteCmd(uint8_t *cmd, uint8_t len)
{
    return HAL_I2C_Master_Transmit(&hi2c3, AHT20_ADDR_WRITE, cmd, len, 100);
}

/**
  * @brief  从AHT20读取数据
  * @param  buf: 数据缓冲区
  * @param  len: 读取长度
  * @retval HAL状态
  */
static HAL_StatusTypeDef AHT20_ReadData(uint8_t *buf, uint8_t len)
{
    return HAL_I2C_Master_Receive(&hi2c3, AHT20_ADDR_READ, buf, len, 100);
}

/**
  * @brief  初始化AHT20
  * @retval 0:成功 1:失败
  */
uint8_t AHT20_Init(void)
{
    uint8_t cmd[3];
    uint8_t status;
    
    HAL_Delay(100);  // 上电等待
    
    /* 软复位 */
    AHT20_SoftReset();
    HAL_Delay(20);
    
    /* 读取状态 */
    if (AHT20_ReadStatus(&status) != HAL_OK) {
        return 1;
    }
    
    /* 检查校准状态 */
    if ((status & 0x08) == 0) {
        /* 发送初始化命令 */
        cmd[0] = AHT20_CMD_INIT;
        cmd[1] = 0x08;
        cmd[2] = 0x00;
        if (AHT20_WriteCmd(cmd, 3) != HAL_OK) {
            return 1;
        }
        HAL_Delay(10);
    }
    
    return 0;
}

/**
  * @brief  软复位AHT20
  * @retval 0:成功 1:失败
  */
uint8_t AHT20_SoftReset(void)
{
    uint8_t cmd = AHT20_CMD_SOFT_RESET;
    if (AHT20_WriteCmd(&cmd, 1) != HAL_OK) {
        return 1;
    }
    return 0;
}

/**
  * @brief  读取状态字
  * @param  status: 状态字节指针
  * @retval 0:成功 1:失败
  */
uint8_t AHT20_ReadStatus(uint8_t *status)
{
    uint8_t cmd = AHT20_CMD_STATUS;
    
    if (HAL_I2C_Master_Transmit(&hi2c3, AHT20_ADDR_WRITE, &cmd, 1, 100) != HAL_OK) {
        return 1;
    }
    
    if (AHT20_ReadData(status, 1) != HAL_OK) {
        return 1;
    }
    
    return 0;
}

/**
  * @brief  检查是否已校准
  * @retval 1:已校准 0:未校准
  */
uint8_t AHT20_ReadCalibrationEnabled(void)
{
    uint8_t status;
    if (AHT20_ReadStatus(&status) != HAL_OK) {
        return 0;
    }
    return (status & 0x08) ? 1 : 0;
}

/**
  * @brief  启动一次测量
  * @retval 0:成功 1:失败
  */
uint8_t AHT20_StartMeasurement(void)
{
    uint8_t cmd[3];
    cmd[0] = AHT20_CMD_TRIG;
    cmd[1] = 0x33;
    cmd[2] = 0x00;
    
    if (AHT20_WriteCmd(cmd, 3) != HAL_OK) {
        return 1;
    }
    
    return 0;
}

/**
  * @brief  读取传感器数据 (非阻塞，需要先启动测量)
  * @param  data: 数据结构指针
  * @retval 0:成功 1:失败 2:正在测量中
  */
uint8_t AHT20_ReadData(AHT20_Data_t *data)
{
    uint8_t buf[7];
    uint32_t humidity, temperature;
    
    /* 读取7字节数据 */
    if (AHT20_ReadData(buf, 7) != HAL_OK) {
        return 1;
    }
    
    data->status = buf[0];
    
    /* 检查BUSY位 */
    if (data->status & 0x80) {
        return 2;  // 正在测量中
    }
    
    /* 提取湿度数据 (20bit) */
    humidity = ((uint32_t)buf[1] << 12) | ((uint32_t)buf[2] << 4) | ((uint32_t)buf[3] >> 4);
    data->humidity_raw = humidity;
    
    /* 提取温度数据 (20bit) */
    temperature = ((uint32_t)(buf[3] & 0x0F) << 16) | ((uint32_t)buf[4] << 8) | buf[5];
    data->temp_raw = temperature;
    
    /* 转换为物理量 */
    /* 湿度公式: RH = (raw / 2^20) * 100 */
    data->humidity = ((float)humidity / 1048576.0f) * 100.0f;
    
    /* 温度公式: T = (raw / 2^20) * 200 - 50 */
    data->temperature = ((float)temperature / 1048576.0f) * 200.0f - 50.0f;
    
    return 0;
}

/**
  * @brief  读取传感器数据 (阻塞式，自动启动测量并等待完成)
  * @param  data: 数据结构指针
  * @param  timeout_ms: 超时时间(毫秒)
  * @retval 0:成功 1:失败
  */
uint8_t AHT20_ReadDataBlocking(AHT20_Data_t *data, uint32_t timeout_ms)
{
    uint32_t start_tick;
    uint8_t result;
    
    /* 启动测量 */
    if (AHT20_StartMeasurement() != 0) {
        return 1;
    }
    
    /* 等待测量完成 (典型80ms) */
    start_tick = HAL_GetTick();
    while ((HAL_GetTick() - start_tick) < timeout_ms) {
        result = AHT20_ReadData(data);
        if (result == 0) {
            return 0;  // 成功
        }
        if (result == 1) {
            return 1;  // I2C错误
        }
        /* result == 2 表示仍在测量中，继续等待 */
        HAL_Delay(5);
    }
    
    return 1;  // 超时
}
