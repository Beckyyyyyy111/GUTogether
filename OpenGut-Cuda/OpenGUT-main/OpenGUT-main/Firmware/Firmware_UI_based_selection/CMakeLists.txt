#
# Copyright (c) 2025 Nordic Semiconductor ASA
#
# SPDX-License-Identifier: LicenseRef-Nordic-5-Clause
#

cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(JSON)

target_sources(app PRIVATE
  src/main.c
  src/app_config.c
  src/led.c
  src/PDM.c
  src/Playback.c
  src/SD.c
)
