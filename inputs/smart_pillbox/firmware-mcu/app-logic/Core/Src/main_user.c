/**
  ******************************************************************************
  * @file    main_user.c
  * @brief   用户主程序 - 需要合并到CubeMX生成的main.c中
  *          将此代码添加到main.c的对应位置
  ******************************************************************************
  */

/* ==================== 需要添加到main.c顶部的include ==================== */
/* 
 * 在 main.c 的 Private includes 部分添加:
 *
 * // 传感器驱动
 * #include "mpu6050.h"
 * #include "aht20.h"
 * #include "bmp280.h"
 * #include "sensor_manager.h"
 * 
 * // 通信驱动
 * #include "esp8266.h"
 * #include "app_tasks.h"
 */

/* ==================== 需要修改MX_FREERTOS_Init函数 ==================== */
/* 
 * 在 main.c 中，注释掉自动生成的MX_FREERTOS_Init调用，
 * 改为调用 App_Init 和 App_StartTasks
 *
 * 原代码:
 *   // MX_FREERTOS_Init();
 * 
 * 改为:
 *   App_Init();
 *   App_StartTasks();
 */

/* ==================== USART3中断处理 (用于ESP8266) ==================== */
/* 
 * 在 stm32g4xx_it.c 中添加USART3中断处理:
 *
 * void USART3_IRQHandler(void)
 * {
 *   HAL_UART_IRQHandler(&huart3);
 * }
 * 
 * 并在 HAL_UART_RxCpltCallback 中添加:
 * 
 * void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
 * {
 *   if (huart->Instance == USART3)
 *   {
 *     ESP8266_UART_RxCallback(rx_byte);
 *     HAL_UART_Receive_IT(&huart3, &rx_byte, 1);  // 重新启动接收
 *   }
 * }
 */

/* ==================== 完整main函数示例 ==================== */
#if 0  // 这是示例代码，不要直接编译

#include "main.h"
#include "cmsis_os.h"
#include "i2c.h"
#include "rtc.h"
#include "spi.h"
#include "tim.h"
#include "usart.h"
#include "gpio.h"

// 用户驱动
#include "mpu6050.h"
#include "aht20.h"
#include "bmp280.h"
#include "sensor_manager.h"
#include "esp8266.h"
#include "app_tasks.h"

void SystemClock_Config(void);

int main(void)
{
    HAL_Init();
    SystemClock_Config();
    
    // 初始化外设
    MX_GPIO_Init();
    MX_RTC_Init();
    MX_SPI1_Init();
    MX_I2C2_Init();      // MPU6050
    MX_I2C3_Init();      // AHT20 + BMP280
    MX_USART1_UART_Init(); // 调试串口
    // USART3已在CubeMX配置，用于ESP-01S
    MX_TIM1_Init();
    
    // 启动USART3接收中断 (ESP8266)
    uint8_t rx_byte;
    HAL_UART_Receive_IT(&huart3, &rx_byte, 1);
    
    // 初始化FreeRTOS和应用程序
    osKernelInitialize();
    App_Init();
    App_StartTasks();
    
    // 启动调度器
    osKernelStart();
    
    // 不会到达这里
    while (1);
}

#endif
