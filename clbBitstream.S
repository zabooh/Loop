/*
    © [2026] Microchip Technology Inc. and its subsidiaries.

    Subject to your compliance with these terms, you may use this Microchip
    software and any derivatives exclusively with Microchip products.
    You are responsible for complying with third party license terms
    applicable to your use of third party software (including open source
    software) that may accompany this Microchip software. SOFTWARE IS "AS IS."
    NO WARRANTIES, WHETHER EXPRESS, IMPLIED OR STATUTORY, APPLY TO THIS
    SOFTWARE, INCLUDING ANY IMPLIED WARRANTIES OF NON-INFRINGEMENT,
    MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE. IN NO EVENT
    WILL MICROCHIP BE LIABLE FOR ANY INDIRECT, SPECIAL, PUNITIVE,
    INCIDENTAL OR CONSEQUENTIAL LOSS, DAMAGE, COST OR EXPENSE OF ANY
    KIND WHATSOEVER RELATED TO THE SOFTWARE, HOWEVER CAUSED, EVEN IF
    MICROCHIP HAS BEEN ADVISED OF THE POSSIBILITY OR THE DAMAGES ARE
    FORESEEABLE. TO THE FULLEST EXTENT ALLOWED BY LAW, MICROCHIP'S
    TOTAL LIABILITY ON ALL CLAIMS RELATED TO THE SOFTWARE WILL NOT
    EXCEED AMOUNT OF FEES, IF ANY, YOU PAID DIRECTLY TO MICROCHIP FOR
    THIS SOFTWARE.

    CLB bitstream data for PIC16F13145 family devices.

    If the CLB data must be at a particular address, define the
    'CLB_CONFIG_ADDR' C macro to set the address. If the location of the data
    does not matter, then leave this macro undefined. The compiler will
    automatically find an optimal place in program memory.

    If the CLB_CONFIG_ADDR macro is not being used, the data may be
    referenced in C with the 'start_clb_config' symbol.
    For example:
        extern uint16_t start_clb_config;
        uint16_t addr;
        addr = &start_clb_config;

    NOTE: Always use the address of this symbol and not the value.

    This module requires C preprocessing.
    This can be enabled via the command line option: -xassembler-with-cpp
*/

#include "clb1_defs.h"

// #define CLB_CONFIG_ADDR <address of bitstream>

#if !(defined(_16F13113) || defined(_16F13114) || defined(_16F13115) \
    || defined(_16F13123) || defined(_16F13124) || defined(_16F13125) \
    || defined(_16F13143) || defined(_16F13144) || defined(_16F13145))
    #error This module is only suitable for PIC16F13145 family devices
#endif

// Check to verify that the header file matches the generated bitstream
#if CLB_BITSTREAM_LENGTH != 102
    #error The CLB module for this device has a 102 words long bitstream
#endif

#ifdef CLB_CONFIG_ADDR
    psect clb_config,global,class=STRCODE,abs,ovrld,delta=2,noexec,split=0,merge=0,keep
#else
    psect clb_config,global,class=STRCODE,delta=2,noexec,split=0,merge=0,keep
#endif

global _start_clb_config

psect   clb_config
#ifdef CLB_CONFIG_ADDR
    ORG CLB_CONFIG_ADDR
#endif

_start_clb_config:
    dw  0x2814;
    dw  0x1D42;
    dw  0x2C20;
    dw  0x3E1F;
    dw  0x03F0;
    dw  0x3E1F;
    dw  0x03E1;
    dw  0x3E1F;
    dw  0x33F8;
    dw  0x059F;
    dw  0x19F0;
    dw  0x3FFF;
    dw  0x008F;
    dw  0x3E1F;
    dw  0x03E1;
    dw  0x3E1F;
    dw  0x28D5;
    dw  0x3D46;
    dw  0x2A6A;
    dw  0x0F5F;
    dw  0x17F5;
    dw  0x0A1F;
    dw  0x03E1;
    dw  0x3E1F;
    dw  0x3098;
    dw  0x0581;
    dw  0x2C50;
    dw  0x3E1F;
    dw  0x03F0;
    dw  0x3E1F;
    dw  0x03E1;
    dw  0x3E1F;
    dw  0x03E1;
    dw  0x3C1F;
    dw  0x21F0;
    dw  0x3E1F;
    dw  0x03F0;
    dw  0x3E1F;
    dw  0x03E1;
    dw  0x3E1F;
    dw  0x33E6;
    dw  0x1D82;
    dw  0x27F0;
    dw  0x3E1F;
    dw  0x03F0;
    dw  0x3E07;
    dw  0x03F5;
    dw  0x3D43;
    dw  0x3FE1;
    dw  0x3DE2;
    dw  0x21F0;
    dw  0x3E1F;
    dw  0x03F0;
    dw  0x3F44;
    dw  0x2BF4;
    dw  0x06A5;
    dw  0x03E1;
    dw  0x3C1F;
    dw  0x21F0;
    dw  0x3E1F;
    dw  0x3FEF;
    dw  0x0A1F;
    dw  0x03E1;
    dw  0x3E1F;
    dw  0x03E1;
    dw  0x3C1F;
    dw  0x21F0;
    dw  0x3E1F;
    dw  0x03F0;
    dw  0x3E1F;
    dw  0x30FE;
    dw  0x0A62;
    dw  0x00F5;
    dw  0x3DE6;
    dw  0x2A30;
    dw  0x3E1F;
    dw  0x03F0;
    dw  0x3E00;
    dw  0x00E0;
    dw  0x0902;
    dw  0x00E0;
    dw  0x0404;
    dw  0x1030;
    dw  0x3E1F;
    dw  0x03F0;
    dw  0x3F1F;
    dw  0x23F1;
    dw  0x3D1F;
    dw  0x23F1;
    dw  0x3D1F;
    dw  0x11F8;
    dw  0x3F1F;
    dw  0x23E8;
    dw  0x3F1F;
    dw  0x23F1;
    dw  0x3D1F;
    dw  0x0160;
    dw  0x0000;
    dw  0x0000;
    dw  0x0000;
    dw  0x3800;
    dw  0x0000;

