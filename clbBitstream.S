/**
 *  @file clbBitstream.S
 *  @brief CLB bitstream for the half-bridge design (PIC16F13145 family).
 *
 *  PLACEHOLDER. Replace the DW block below with the real bitstream produced by
 *  the CLB Synthesizer (online at logic.microchip.com/clbsynthesizer or in MCC)
 *  for clb/clb_halfbridge.v. The words are 14-bit program-memory values; the
 *  NVM scanner streams them into the CLB. The C side uses the addresses of the
 *  _start_clb_config / _end_clb_config symbols (size is derived from them), so
 *  the block may be any length — just paste the synthesized DW list here.
 *
 *  Assembled with C preprocessing (.S). Built via the assemblePreprocess rule.
 */
#include <xc.inc>

#if !( defined(_16F13113) || defined(_16F13114) || defined(_16F13115) || \
       defined(_16F13123) || defined(_16F13124) || defined(_16F13125) || \
       defined(_16F13143) || defined(_16F13144) || defined(_16F13145) )
    #error This file targets the PIC16F13145 device family only.
#endif

GLOBAL  _start_clb_config
GLOBAL  _end_clb_config

PSECT  clb_config,global,class=STRCODE,delta=2,noexec,optim=

_start_clb_config:
    ; --- placeholder: all-zero config (CLB does nothing until replaced) ---
    DW  0x0000
    DW  0x0000
    DW  0x0000
    DW  0x0000
_end_clb_config:
