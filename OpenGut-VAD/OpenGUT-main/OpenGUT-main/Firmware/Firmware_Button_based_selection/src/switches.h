#ifndef SWICTHES_H
#define SWICTHES_H

#include <stdbool.h>
#include <stdint.h>

int Switches_Init(void);
bool Switch_Pressed(uint8_t switch_number);
bool Switch_Is_Down(uint8_t switch_number);
void Switches_Clear_All(void);

#endif /* SWICTHES_H */
